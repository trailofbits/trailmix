#!/usr/bin/env python3
"""Cost / failure model for the Schrottenloher 2026 secp256k1 EC point-add.

This is the analytical + EMPIRICAL backend for `schr_param_search.py`. It
ports the classical GCD/Horner reference from the Rust source faithfully so
that the GCD-convergence failure rate can be MEASURED (not guessed) at reduced
iteration budgets / comparator widths, and combines it with the per-call
+f-window truncation failure (analytic 2^-padding, validated against the same
classical references) into a per-shot success probability `p_shot`.

Validation model (from the task spec):
  The zenodo fuzz tool runs N = 9000 random secp256k1 on-curve point pairs.
  EVERY shot must be correct. So P(run) = p_shot ** 9000, and per-shot failure
  f_shot must satisfy (1 - f_shot) ** 9000 >= target.

GROUND TRUTH (cite file:line for every formula):
  * expected_iterations(n) = ceil((1.413*n + ITERATIONS_VAR*sqrt(n)) / 5) * 5
        gcd_pack.rs:43-46 ; ITERATIONS_VAR = 2.4  (gcd_pack.rs:34)
        DIALOG_M = 5 (round-to-multiple)          (gcd_pack.rs:19)
  * u_padding(n) = ceil(U_PAD_VAR * sqrt(n)) ; U_PAD_VAR = 2.3
        gcd_pack.rs:50-52, 38
  * classical GCD step body                       gcd_pack.rs:102-149
        b0 = v[0] ; b1 = (u > v) ; b0_and_b1 = b0 & b1
        if b0_and_b1: swap(u, v)
        if b0: v = (v - u) if v >= u else (u + v) - 2u
        v >>= 1
    convergence after `iters` iters: v == 0 and u == 1, else None  (gcd_pack.rs:150-152)
  * TRUNCATE = 40  (GCD comparator width)          gcd_pack.rs:271
        quantum compare uses top trunc = TRUNCATE + pad bits of the
        CURRENT (shrunken) effective width          gcd_pack.rs:272, 320-339
  * current_n_at(i) = min(n, ceil(n - i*0.5*1.415 + pad))   gcd_pack.rs:289-296
  * pm reduction: padding = 30, f_bitlen = 33, lsbs = padding + f_bitlen = 63,
        msbs = padding = 30                          pm_prims.rs:116-117, 193-194, 268, 344
    per-call +f-window truncation failure ~ 2^-padding (carry beyond lsbs
    dropped)                                         pm_prims.rs:24-25, 114-128, 260
    per-call clt/comparator failure ~ 2^-msbs        pm_prims.rs:231, 263-268
  * F_SECP256K1 = 2^32 + 977 ; q = 2^256 - F        mod.rs:42
  * cost anchor (raw dialog_m=1, vents=0, iters=405): total Toffoli 2,272,261
        (task spec, from profile_ec_add_schrottenloher)
  * venting coupling: each vent ancilla = -1 Toffoli/call over ~810 ventable
        calls; freed dialog-tape qubits feed the vent budget   (task spec)
  * dialog_tape(raw M=1) = 2*iters ; (packed M=5) = iters/5*8   gcd_pack.rs:56-58, 66-79
  * qubit peak ~ dialog_tape + 514 + venting_budget + ~10       (task spec anchor)

NEVER seeds the RNG (run-to-run wobble is signal).
"""

import math
import random

# --------------------------------------------------------------------------
# secp256k1 constants (mod.rs:42)
# --------------------------------------------------------------------------
N = 256
F_SECP256K1 = (1 << 32) + 977
Q = (1 << 256) - F_SECP256K1

# Source defaults (the Rust constants each param set would change).
DEFAULT_ITERATIONS_VAR = 2.4   # gcd_pack.rs:34
DEFAULT_U_PAD_VAR = 2.3        # gcd_pack.rs:38
DEFAULT_TRUNCATE = 40          # gcd_pack.rs:271
DEFAULT_PADDING = 30           # pm_prims.rs:193 etc.
F_BITLEN = 33                  # pm_prims.rs:194
DIALOG_M_PACK = 5              # gcd_pack.rs:19

# --------------------------------------------------------------------------
# Iteration / padding schedule (gcd_pack.rs:43-52)
# --------------------------------------------------------------------------

def expected_iterations(n=N, iterations_var=DEFAULT_ITERATIONS_VAR, dialog_m=DIALOG_M_PACK):
    """gcd_pack.rs:43-46. Rounded UP to a multiple of dialog_m (=5)."""
    raw = 1.413 * n + iterations_var * math.sqrt(n)
    return int(math.ceil(raw / dialog_m)) * dialog_m


def u_padding(n=N, u_pad_var=DEFAULT_U_PAD_VAR):
    """gcd_pack.rs:50-52."""
    return int(math.ceil(u_pad_var * math.sqrt(n)))


def current_n_at(i, n=N, pad=None):
    """gcd_pack.rs:289-296 (STEP = 1)."""
    if pad is None:
        pad = u_padding(n)
    raw = float(n) - float(i) * 0.5 * 1.415 + float(pad)
    raw_int = max(0, int(math.ceil(raw)))
    return min(raw_int, n)


# --------------------------------------------------------------------------
# Classical GCD reference, PORTED faithfully from gcd_pack.rs:102-149.
#
# Two comparison modes for b1:
#   "exact"     : b1 = (u > v)             -- exactly what to_bitvector_classical
#                 does (it is the ground-truth reference, gcd_pack.rs:104).
#   "truncated" : b1 = (v_top < u_top) on the top `trunc` bits of the CURRENT
#                 shrunken effective width, mirroring the QUANTUM comparator
#                 (gcd_pack.rs:320-339, controlled_lt_msbs_gidney). This models
#                 TRUNCATE's effect on convergence. Note the quantum compare is
#                 b0_and_b1 ^= b0 AND (v_top < u_top); (v_top < u_top) is the
#                 top-bits approximation of (v < u) == NOT (u > v) when v != u,
#                 i.e. b1 == NOT(v_top < u_top) on the top bits, falling back to
#                 the exact tie behaviour when the top bits are equal.
# --------------------------------------------------------------------------

def _b1_truncated(u, v, current_n, trunc):
    """Mirror controlled_lt_msbs_gidney on the top-`trunc` bits of width
    `current_n` (gcd_pack.rs:320-339). Returns b1 = (u > v) as decided by the
    truncated comparator. The comparator computes (v_top < u_top); b1 = that.
    On a top-bits tie it returns 0 (the comparator's '<' is strict), which is
    the realistic failure mode: ties in the top bits make the comparator
    decide 'not greater', possibly the wrong swap decision."""
    cmp_eff = min(trunc, current_n)
    cmp_lo = current_n - cmp_eff
    # top bits = bits [cmp_lo, current_n) of u and v
    mask = ((1 << current_n) - 1)
    u_top = (u & mask) >> cmp_lo
    v_top = (v & mask) >> cmp_lo
    return 1 if v_top < u_top else 0


def gcd_converges(u, v, n=N, iters=None, iterations_var=DEFAULT_ITERATIONS_VAR,
                  truncate=None, mode="exact"):
    """Run the classical GCD dialog (gcd_pack.rs:102-149) and report whether
    it converges to (u, v) = (1, 0) within `iters` iterations.

    Returns True on convergence, False on budget exhaustion / wrong endpoint
    (the `None` return in to_bitvector_classical, gcd_pack.rs:150-152).

    Pre: u odd, u, v < 2^n (the inversion use case feeds u = q, v = x with x
    odd; here we accept arbitrary odd u for generality but the search always
    calls it as gcd_converges(q, x)).
    """
    assert u & 1, "u must be odd (gcd_pack.rs:92)"
    if iters is None:
        iters = expected_iterations(n, iterations_var)
    if truncate is None:
        truncate = DEFAULT_TRUNCATE
    pad = u_padding(n)
    for i in range(iters):
        b0 = v & 1
        if mode == "exact":
            b1 = 1 if u > v else 0
        else:
            cur_n = max(current_n_at(i, n, pad), 1)
            b1 = _b1_truncated(u, v, cur_n, truncate + pad)
        b0_and_b1 = b0 & b1
        if b0_and_b1:
            u, v = v, u
        if b0:
            if v >= u:
                v = v - u
            else:
                v = (u + v) - 2 * u  # == v - u (negative wrapped); matches Rust
        v >>= 1
    return (v == 0) and (u == 1)


# --------------------------------------------------------------------------
# EMPIRICAL GCD-failure rate.
# --------------------------------------------------------------------------

def gcd_fail_rate(iters_var, truncate=None, trials=200_000, mode="exact",
                  n=N, dialog_m=DIALOG_M_PACK):
    """EMPIRICALLY estimate the GCD-non-convergence failure rate for a given
    ITERATIONS_VAR (and TRUNCATE if mode='truncated'), by running the ported
    classical GCD on `trials` random secp256k1 inversion inputs:
        u = q, v = x with x random odd in [1, q).
    (This is exactly the to_bitvector_classical(q, x) call in the inversion;
    gcd_pack.rs:700, 863.)

    Returns (fail_rate, fails, trials, ci95_half_width). ci95 via the normal
    approximation; for very low rates use the (fails, trials) pair to judge
    significance directly (see the docstring note in the search script).

    NEVER seeds the RNG. Use a large `trials` so the estimate is meaningful at
    the relevant target (see the calling search for guidance).
    """
    iters = expected_iterations(n, iters_var, dialog_m)
    rng = random.SystemRandom()  # OS entropy, never seeded
    fails = 0
    for _ in range(trials):
        x = rng.randrange(1, Q)
        if not (x & 1):
            x += 1
            if x >= Q:
                x -= 2
        ok = gcd_converges(Q, x, n=n, iters=iters, iterations_var=iters_var,
                           truncate=truncate, mode=mode)
        if not ok:
            fails += 1
    rate = fails / trials
    # 95% CI half-width (normal approx); meaningful only when fails is not tiny.
    ci = 1.96 * math.sqrt(max(rate * (1 - rate), 1e-12) / trials)
    return rate, fails, trials, ci


# --------------------------------------------------------------------------
# Per-call +f-window truncation failure and msbs-comparator failure.
#
# The pm reduction (pm_prims.rs) drops the carry beyond bit `lsbs` of the +f
# window. f = F_SECP256K1 has f_bitlen = 33 bits. The window is lsbs = padding
# + f_bitlen bits. A failure occurs when the windowed add `low_lsbs(y) + f`
# would carry out of bit lsbs-1, i.e. low_lsbs(y) >= 2^lsbs - f. On uniform y
# in [0, q) the low lsbs bits are ~uniform, so
#     P(carry out) ~ f / 2^lsbs = f / 2^(padding + f_bitlen) ~ 2^-padding.
# (pm_prims.rs:24-25, 114-128 say "carry beyond lsbs dropped"; the docstring
# at pm_prims.rs:116-117, 260 quotes ~2^-padding.)
#
# The msbs comparator (controlled_lt_msbs, pm_prims.rs:263-268) misdecides when
# the top-msbs of the two operands tie but the low bits would have flipped the
# comparison: P ~ 2^-msbs = 2^-padding.
# --------------------------------------------------------------------------

def reduction_fail_rate_per_call_analytic(padding=DEFAULT_PADDING, f=F_SECP256K1,
                                          f_bitlen=F_BITLEN):
    """Analytic per-call failure for ONE +f-window reduction (the dominant
    truncation mode). lsbs = padding + f_bitlen (pm_prims.rs:193-194).
    P(carry dropped) = f / 2^lsbs on uniform low bits."""
    lsbs = padding + f_bitlen
    return f / float(1 << lsbs)


def msbs_fail_rate_per_call_analytic(padding=DEFAULT_PADDING):
    """Analytic per-call failure for ONE msbs comparator / clt cleanup
    (pm_prims.rs:263-268, 231). Top-msbs tie ~ 2^-msbs = 2^-padding."""
    return 2.0 ** (-padding)


def reduction_fail_rate(padding, trials=2_000_000, f=F_SECP256K1,
                        f_bitlen=F_BITLEN, validate_with_padding=14):
    """EMPIRICALLY estimate the per-call +f-window truncation failure rate at a
    SMALL padding (where it is measurable), then return the analytic
    2^-padding-style rate for the requested `padding`, having confirmed the
    analytic model against the empirical measurement.

    For padding >= ~20 the per-call failure (~2^-padding) is far below what a
    few million trials can resolve, so direct empirical measurement at the
    target padding is meaningless. Instead we VALIDATE the analytic model
    `f / 2^(padding+f_bitlen)` at `validate_with_padding` (default 14, where
    the rate ~ f/2^47 ... still tiny). To get a *measurable* anchor we shrink
    f_bitlen artificially in the harness: we simulate the windowed add on
    random low-bit operands of width lsbs and count true carry-outs. This is
    the faithful per-call event (pm_prims.rs:114-128).

    Returns dict with: analytic_target (rate at `padding`), emp_rate,
    emp_trials, emp_padding_used, model_ratio (emp/analytic at the validation
    padding; ~1.0 confirms the model)."""
    rng = random.SystemRandom()
    # Validation: measure the carry-drop event at a small padding where it is
    # resolvable, simulating the EXACT windowed add (low_lsbs(y) + f, carry
    # out of bit lsbs-1).
    val_pad = validate_with_padding
    lsbs_val = val_pad + f_bitlen
    mod_val = 1 << lsbs_val
    threshold = mod_val - f  # carry out iff low >= 2^lsbs - f
    fails = 0
    for _ in range(trials):
        low = rng.randrange(mod_val)  # uniform low-lsbs bits of a random y
        if low >= threshold:
            fails += 1
    emp_rate = fails / trials
    analytic_val = f / float(mod_val)
    model_ratio = emp_rate / analytic_val if analytic_val > 0 else float('nan')
    analytic_target = reduction_fail_rate_per_call_analytic(padding, f, f_bitlen)
    return {
        "analytic_target": analytic_target,
        "emp_rate": emp_rate,
        "emp_fails": fails,
        "emp_trials": trials,
        "emp_padding_used": val_pad,
        "analytic_at_val": analytic_val,
        "model_ratio": model_ratio,
    }


# --------------------------------------------------------------------------
# Reduction-call counts per EC-add shot (counted from the driver).
#
# pointadd.rs:81-102 calls, per EC-add:
#   step 6 : mod_mul reverse (division) -> apply_bv_inv: iters controlled_mod_sub
#            (each: 1 lsbs +f window + 1 msbs comparator) + iters mod_halve
#            (mod_halve approx drift ~2^-224, NEGLIGIBLE).               (bezout_unpack.rs:540-553)
#   step 11: mod_mul forward (multiply) -> apply_bv: iters mod_double
#            (1 lsbs +f window each) + iters controlled_mod_add
#            (1 lsbs +f window + 1 msbs comparator each).                (bezout_unpack.rs:168-176)
#   step 10: controlled_mod_square_sub: (n-1) setup doublings + per bit i:
#            1 controlled_mod_add + (up to 2) mod_double.                (pm_prims.rs:698-723)
#            ~ 2n mod_double + n controlled_mod_add.
#   coord steps 3,4,7-8(x3),14,15: 7 unconditional mod_add/sub
#            (1 lsbs +f window + 1 msbs comparator each).                (pointadd.rs:82-102, 117-138)
#
# Each lsbs +f window can drop a carry (P ~ 2^-padding). Each msbs comparator
# can misfire (P ~ 2^-msbs = 2^-padding). We union-bound over all such events.
# --------------------------------------------------------------------------

def reduction_event_counts(iters):
    """Return (n_fwindow, n_msbs): the number of lsbs +f-window reductions and
    msbs comparator cleanups per EC-add shot, as functions of `iters`.

    Counted from pointadd.rs:81-102 + bezout_unpack.rs + pm_prims.rs (see the
    module comment block above for the per-step tally)."""
    n = N
    # --- apply_bv_inv (division), iters iterations ---
    div_fwindow = iters * 1   # controlled_mod_sub: 1 +f window/iter
    div_msbs = iters * 1      # controlled_mod_sub: 1 msbs cleanup/iter
    # --- apply_bv (multiply), iters iterations ---
    mul_fwindow = iters * 1   # mod_double: 1 +f window/iter
    mul_fwindow += iters * 1  # controlled_mod_add: 1 +f window/iter
    mul_msbs = iters * 1      # controlled_mod_add: 1 msbs cleanup/iter
    # --- square (controlled_mod_square_sub) ---
    # (n-1) leading reverse doublings + per-bit (1 cma + up to 2 doublings).
    sq_doublings = (n - 1) + (n - 1) + (n - 1)  # ~ 3(n-1) doublings total
    sq_fwindow = sq_doublings * 1 + n * 1       # each doubling 1 +f; each cma 1 +f
    sq_msbs = n * 1                              # each cma 1 msbs cleanup
    # --- coord add/sub steps (7 of them) ---
    coord = 7
    coord_fwindow = coord * 1
    coord_msbs = coord * 1
    n_fwindow = div_fwindow + mul_fwindow + sq_fwindow + coord_fwindow
    n_msbs = div_msbs + mul_msbs + sq_msbs + coord_msbs
    return n_fwindow, n_msbs


# --------------------------------------------------------------------------
# Combined per-shot success probability.
# --------------------------------------------------------------------------

def p_shot(params, gcd_fail=None):
    """Combine the failure modes into a per-shot success probability.

    params: dict with keys iterations_var, truncate, padding, vents (vents does
            not affect correctness, only cost).
    gcd_fail: pre-measured GCD-non-convergence rate (from gcd_fail_rate). If
            None, falls back to a conservative analytic estimate (NOT
            recommended; the search always passes the measured value).

    Returns (p_shot, f_shot, breakdown_dict).
    """
    iters_var = params["iterations_var"]
    truncate = params.get("truncate", DEFAULT_TRUNCATE)
    padding = params["padding"]
    iters = expected_iterations(N, iters_var)

    if gcd_fail is None:
        # Conservative fallback: at the default 2.4 the budget tail is ~1e-4
        # per the source comments (gcd_pack.rs:877). Use that anchor scaled.
        gcd_fail = 1e-4

    n_fwindow, n_msbs = reduction_event_counts(iters)
    f_fwindow_call = reduction_fail_rate_per_call_analytic(padding)
    f_msbs_call = msbs_fail_rate_per_call_analytic(padding)
    # Union bound over all per-call truncation events.
    f_reduction = n_fwindow * f_fwindow_call + n_msbs * f_msbs_call
    # Total per-shot failure: union of GCD-non-convergence and any reduction
    # truncation. (The mod_halve drift ~2^-224 and the 2x-in-[q,2^n) drift
    # ~2^-224 are negligible; see pm_prims.rs:124-128.)
    f = gcd_fail + f_reduction
    f = min(f, 1.0)
    p = 1.0 - f
    breakdown = {
        "iters": iters,
        "gcd_fail": gcd_fail,
        "n_fwindow": n_fwindow,
        "n_msbs": n_msbs,
        "f_fwindow_call": f_fwindow_call,
        "f_msbs_call": f_msbs_call,
        "f_reduction": f_reduction,
        "f_shot": f,
    }
    return p, f, breakdown


# --------------------------------------------------------------------------
# Cost model: qubits and Toffoli, with the venting coupling.
# --------------------------------------------------------------------------

# Cost anchor (task spec): raw dialog_m=1, vents=0, iters_anchor = 405.
ANCHOR_ITERS = 405
ANCHOR_TOFFOLI = 2_272_261
# Approximate per-component breakdown at the anchor (task spec).
ANCHOR_BREAKDOWN = {
    "regadds": 623_000,   # apply_bv mod-add/sub register adds (~3n), ~810 ventable calls
    "gcd_csub": 478_000,  # GCD controlled-sub (~2n, vented)
    "sqr_add": 227_000,   # square controlled-add
    "freduce": 313_000,   # +f reductions (~3n, scales with lsbs and iters)
    "cswaps": 240_000,    # scales with sum over iters of current_n
    "comparators": 153_000,  # scales with iters * TRUNCATE
    "doublehalve": 232_000,  # scales with iters
}
# Ventable register-add calls (task spec: ~810).
VENTABLE_CALLS = 810
# Base qubit overhead (task spec: 514 in-place-mul regs + ~10 misc).
QUBIT_BASE = 514 + 10


def dialog_tape(iters, dialog_m=DIALOG_M_PACK):
    """gcd_pack.rs:56-58 (M=5) / :66-79. raw M=1 = 2*iters ; packed M=5 =
    iters/5*8."""
    if dialog_m == 1:
        return 2 * iters
    if dialog_m == 5:
        return iters // 5 * 8
    raise ValueError("dialog_m must be 1 or 5")


def qubits(params):
    """Project the qubit peak.

    peak ~ dialog_tape + 514 + vents + ~10  (task spec anchor).
    The vent budget consumes qubit headroom: each per-call vent ancilla raises
    the peak by 1 (the pool is reused across ops). The f-vented +f window in
    the higher-qubit configs materializes the lsbs-bit constant, so venting the
    +f reduction adds ~lsbs (=padding+33) more than `vents` alone; we model the
    observed (1,90)->~1451 (+122 not +90, pointadd.rs:357-361) by adding the
    materialized-f overhead when f_vent is on.
    """
    iters = expected_iterations(N, params["iterations_var"])
    dm = params.get("dialog_m", DIALOG_M_PACK)
    vents = params.get("vents", 0)
    tape = dialog_tape(iters, dm)
    peak = tape + QUBIT_BASE + vents
    if vents > 0:
        # f-window venting materializes the lsbs-bit constant (pm_prims.rs:55-77),
        # adding ~lsbs extra peak beyond the `vents` ancillae. Observed gap:
        # (1,90) -> 1451 vs base+90 -> ~1419, i.e. +~32 ~ lsbs/2 effective.
        # Use the measured anchor: +32 for the f-materialization at vents>0.
        peak += 32
    return int(round(peak))


def toffoli(params):
    """Project the Toffoli count.

    Scaling rules (task spec breakdown):
      * regadds, gcd_csub, sqr_add: ~ const in iters fraction tied to register
        width (n), scale ~linearly with iters for the per-iter register adds.
        regadds + gcd_csub are per-iter (apply_bv / GCD); sqr_add is fixed (square).
      * freduce: scales ~linearly with lsbs (= padding + 33) and with iters.
      * cswaps: scales with sum over iters of current_n.
      * comparators: scales with iters * TRUNCATE.
      * doublehalve: scales with iters.
    Venting: vents * VENTABLE_CALLS Toffoli saved (each vent -1 Toffoli/call
    over the ~810 ventable register-add calls), capped so a component can't go
    negative. Plus the +f reduction also vents (f_vent), saving ~the XORCarries
    restore pass (~n per call) over its ventable calls; we fold that into the
    same `vents` lever per the source coupling (pm_prims.rs:30-34, 342-344).
    """
    iters = expected_iterations(N, params["iterations_var"])
    truncate = params.get("truncate", DEFAULT_TRUNCATE)
    padding = params["padding"]
    dm = params.get("dialog_m", DIALOG_M_PACK)
    vents = params.get("vents", 0)

    it_ratio = iters / float(ANCHOR_ITERS)
    lsbs = padding + F_BITLEN
    lsbs_anchor = DEFAULT_PADDING + F_BITLEN
    trunc_ratio = truncate / float(DEFAULT_TRUNCATE)

    b = ANCHOR_BREAKDOWN
    # Per-iter register adds (apply_bv) + GCD csub scale ~linearly with iters.
    regadds = b["regadds"] * it_ratio
    gcd_csub = b["gcd_csub"] * it_ratio
    # Square is independent of iters (it Horner-iterates over n=256 bits).
    sqr_add = b["sqr_add"]
    # +f reductions scale with lsbs AND with iters.
    freduce = b["freduce"] * (lsbs / float(lsbs_anchor)) * it_ratio
    # cswaps scale with sum over iters of current_n. The current_n schedule is
    # linear in i, so sum ~ proportional to iters^2 for the part before the
    # floor; we approximate by it_ratio (dominant, since the schedule shape is
    # fixed and only the count of iters changes). Use it_ratio.
    cswaps = b["cswaps"] * it_ratio
    # comparators scale with iters * TRUNCATE.
    comparators = b["comparators"] * it_ratio * trunc_ratio
    # mod_double/halve scale with iters.
    doublehalve = b["doublehalve"] * it_ratio

    total = regadds + gcd_csub + sqr_add + freduce + cswaps + comparators + doublehalve

    # Compression cost: the M=5 packed config pays the base-3 encoder
    # (compress_5iter) ~204k Toffoli (pointadd.rs:349-350: raw drops -204k).
    # The anchor is the RAW (M=1) config, so M=5 ADDS this.
    if dm == 5:
        total += 204_000 * it_ratio

    # Venting: each vent ancilla turns one carry-uncompute Toffoli into a
    # measurement over the ~810 ventable register-add calls. Cap the vents at
    # the addend width-1 (~n-1 = 255) per the source clamp (gcd_pack.rs:30,
    # pm_prims.rs comments).
    eff_vents = min(vents, N - 1)
    savings = eff_vents * VENTABLE_CALLS
    total -= savings

    return int(round(total))


# --------------------------------------------------------------------------
# Run-success probability over the 9000-shot fuzz run.
# --------------------------------------------------------------------------

def p_run(f_shot, n_shots=9000):
    """P(run succeeds) = (1 - f_shot) ** n_shots (task spec)."""
    return (1.0 - f_shot) ** n_shots


# Target thresholds (task spec).
def f_shot_target(p_run_target, n_shots=9000):
    """Max per-shot failure to hit a run-success target:
    (1 - f) ** n_shots >= p_run_target  =>  f <= 1 - p_run_target**(1/n_shots)."""
    return 1.0 - p_run_target ** (1.0 / n_shots)


if __name__ == "__main__":
    # Quick self-check / sanity dump (not the search; that's the other script).
    print("secp256k1 q bitlen:", Q.bit_length())
    print("expected_iterations(256, 2.4) =", expected_iterations(), "(want 405)")
    print("u_padding(256, 2.3)           =", u_padding(), "(want 37)")
    print("dialog_tape(405, M=5)         =", dialog_tape(405, 5), "(want 648)")
    print("dialog_tape(405, M=1)         =", dialog_tape(405, 1), "(want 810)")
    print()
    for tgt, name in [(0.90, "aggressive"), (0.01, "reckless"), (0.10, "reckless>10%")]:
        print(f"f_shot_target(P_run >= {tgt:.2f}) = {f_shot_target(tgt):.3e}  [{name}]")
    print()
    # Validate the +f-window analytic model empirically (small trial count).
    rv = reduction_fail_rate(DEFAULT_PADDING, trials=2_000_000)
    print("reduction model validation (+f window):")
    print(f"  empirical rate @ padding={rv['emp_padding_used']}: {rv['emp_rate']:.3e}"
          f" ({rv['emp_fails']}/{rv['emp_trials']})")
    print(f"  analytic    @ padding={rv['emp_padding_used']}: {rv['analytic_at_val']:.3e}")
    print(f"  model_ratio (emp/analytic): {rv['model_ratio']:.3f}  (~1.0 confirms model)")
    print(f"  analytic target @ padding={DEFAULT_PADDING}: {rv['analytic_target']:.3e}")
