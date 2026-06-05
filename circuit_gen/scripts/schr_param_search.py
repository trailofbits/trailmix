#!/usr/bin/env python3
"""Parameter search for the Schrottenloher 2026 secp256k1 EC point-add.

Sweeps (ITERATIONS_VAR, padding, TRUNCATE, vents) and, for each correctness
target, prints the CHEAPEST parameter set that meets it.

Targets (task spec; per-shot failure f_shot must satisfy (1-f_shot)^9000 >= P):
  aggressive   : P(run) >= 0.90  ->  f_shot <= 1.171e-5
  reckless     : beat BOTH 1175q AND 1.7M Toffoli, P(run) > 0.01  ->  f_shot <= 5.116e-4
  reckless>10% : same cost bound, P(run) > 0.10  ->  f_shot <= 2.558e-4

Cost / failure model lives in schr_param_model.py (cites Rust file:line for
every formula). The GCD-non-convergence rate is MEASURED empirically by
porting the classical GCD; the +f-window truncation rate is the analytic
2^-padding model, validated empirically (see schr_param_model.reduction_fail_rate).

Run from circuit_gen/:
    python3 scripts/schr_param_search.py            # fast (default trials)
    python3 scripts/schr_param_search.py --full     # high-trial GCD measurement
    python3 scripts/schr_param_search.py --trials 5000000

NEVER seeds the RNG (run-to-run wobble is signal).
"""

import argparse
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schr_param_model as M


# Run-success targets.
TARGETS = [
    ("aggressive",   0.90, None),                      # cost-free target
    ("reckless",     0.01, {"max_qubits": 1175, "max_toffoli": 1_700_000}),
    ("reckless>10%", 0.10, {"max_qubits": 1175, "max_toffoli": 1_700_000}),
]

# High-resolution GCD-non-convergence anchor: 2,000,000-trial empirical
# measurement (exact mode, ported gcd_pack.rs:102-152, u=q v=random-odd-x).
# Used as the authoritative gcd_fail when an iters value is present (the
# search's own --trials sweep VALIDATES these and resolves any not listed).
# Stored as (fails, trials) so the search can take the rate or a conservative
# 95%-CI upper bound (fails + 3)/trials when fails is tiny. Run-to-run wobble
# is expected (RNG never seeded); re-measure with --full to refresh.
HIGH_RES_GCD = {
    # iters: (fails, trials)   measured 2026-06-03, /tmp/gcd_agg.py 2M
    415: (0, 2_000_000),
    410: (2, 2_000_000),
    405: (4, 2_000_000),
    400: (52, 2_000_000),   # 2.6e-5 -- the convergence cliff: 405 -> 400 is ~13x
}


def iv_for_iters(target_iters):
    """ITERATIONS_VAR that yields expected_iterations == target_iters (mid-bin
    so it is robust to float rounding). raw = 1.413*256 + iv*16; pick raw =
    target-2.5 (middle of the (target-5, target] round-up bin)."""
    raw = target_iters - 2.5
    iv = (raw - 1.413 * M.N) / (M.DEFAULT_ITERATIONS_VAR * 0 + 16.0)
    assert M.expected_iterations(M.N, iv) == target_iters, (target_iters, iv)
    return iv


def measure_gcd_rates(iters_list, trials, modes=("exact",), truncate=40):
    """Empirically measure gcd_fail for each iters value (and mode). Returns
    {(iters, mode): (rate, fails, trials)}."""
    out = {}
    for it in iters_list:
        iv = iv_for_iters(it)
        for mode in modes:
            rate, fails, tr, ci = M.gcd_fail_rate(
                iv, truncate=truncate, trials=trials, mode=mode)
            out[(it, mode)] = (rate, fails, tr)
    return out


def measure_truncated_grid(iters_list, truncate_list, trials):
    """DIRECTLY measure GCD-non-convergence in TRUNCATED mode for each
    (iters, TRUNCATE) pair (gcd_pack.rs:320-339 comparator). This is the
    faithful model of the comparator's effect on convergence: narrowing
    TRUNCATE sharply raises non-convergence (measured: at iters=405,
    T=40->0, T=30->9e-5, T=24->1.6e-3, T=20->1e-2, T=16->5e-2). Returns
    {(iters, T): (rate, fails, trials)}."""
    out = {}
    for it in iters_list:
        iv = iv_for_iters(it)
        for T in truncate_list:
            rate, fails, tr, ci = M.gcd_fail_rate(
                iv, truncate=T, trials=trials, mode="truncated")
            out[(it, T)] = (rate, fails, tr)
    return out


def evaluate(iters, padding, truncate, vents, dialog_m, gcd_fail):
    """Return a record dict for one parameter point."""
    iters_var = iv_for_iters(iters)
    params = {
        "iterations_var": iters_var,
        "padding": padding,
        "truncate": truncate,
        "vents": vents,
        "dialog_m": dialog_m,
    }
    p, f, bd = M.p_shot(params, gcd_fail=gcd_fail)
    q = M.qubits(params)
    tof = M.toffoli(params)
    prun = M.p_run(f)
    return {
        "iters": iters,
        "iters_var": iters_var,
        "padding": padding,
        "truncate": truncate,
        "vents": vents,
        "dialog_m": dialog_m,
        "tape": M.dialog_tape(iters, dialog_m),
        "qubits": q,
        "toffoli": tof,
        "f_shot": f,
        "p_run": prun,
        "gcd_fail": gcd_fail,
        "f_reduction": bd["f_reduction"],
    }


def fmt_row(r):
    return (f"  iv={r['iters_var']:+.4f}  pad={r['padding']:>2d}  trunc={r['truncate']:>2d}  "
            f"vents={r['vents']:>3d}  M={r['dialog_m']}  iters={r['iters']:>3d}  "
            f"tape={r['tape']:>3d}  q={r['qubits']:>4d}  tof={r['toffoli']:>9,d}  "
            f"f_shot={r['f_shot']:.3e}  P9000={r['p_run']:.4f}")


def meets(r, target_f, cost=None):
    if r["f_shot"] > target_f:
        return False
    if cost is not None:
        if r["qubits"] > cost["max_qubits"]:
            return False
        if r["toffoli"] > cost["max_toffoli"]:
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=500_000,
                    help="GCD empirical trials per iters/mode (default 500k; "
                         "use --full for 3M).")
    ap.add_argument("--full", action="store_true",
                    help="High-trial GCD measurement (3,000,000 trials).")
    args = ap.parse_args()
    trials = 3_000_000 if args.full else args.trials

    # Sweep ranges.
    iters_grid = [415, 410, 405, 400, 395, 390, 385]
    padding_grid = list(range(10, 41))         # padding (pm_prims default 30)
    truncate_grid = [40, 30, 24, 20, 16]       # GCD comparator width (default 40)
    vents_grid = [0, 60, 90, 120, 180, 255]    # measurement-vent ancillae
    dialog_grid = [5, 1]                       # packed (low-q) vs raw (low-tof)

    print("=" * 100)
    print("Schrottenloher secp256k1 EC point-add parameter search")
    print(f"GCD empirical trials per (iters,mode): {trials:,}  (RNG never seeded)")
    print("=" * 100)

    # --- Measure GCD-non-convergence empirically across the iters grid. ---
    print("\n[1] Empirical GCD-non-convergence rate (ported classical GCD, "
          "u=q, v=x odd; gcd_pack.rs:102-152):")
    gcd_rates = measure_gcd_rates(iters_grid, trials)
    print(f"{'iters':>6} | {'exact fail (sweep)':>20} | {'HIGH-RES 2M':>14} | "
          f"{'tape_M5':>7} {'tape_M1':>7}")
    print("-" * 80)
    for it in iters_grid:
        re_, rf_, rt_ = gcd_rates[(it, "exact")]
        hr = (f"{HIGH_RES_GCD[it][0]/HIGH_RES_GCD[it][1]:.2e}"
              if it in HIGH_RES_GCD else "  (sweep)")
        print(f"{it:>6} | {re_:>14.3e}({rf_:>4d}) | {hr:>14} | "
              f"{M.dialog_tape(it,5):>7} {M.dialog_tape(it,1):>7}")

    # --- DIRECT truncated-mode (iters, TRUNCATE) convergence grid. ---
    # TRUNCATE narrowing breaks GCD convergence; this is the faithful measure
    # (gcd_pack.rs:320-339), not an extrapolation. Use the high-res anchor for
    # iters=405 (trunc_check 100k) plus a per-run sweep for the rest.
    print("\n[1b] GCD-non-convergence vs TRUNCATE (DIRECT truncated comparator, "
          "gcd_pack.rs:320-339):")
    # The aggressive/reckless decisions only need iters in {405, 400, 395}.
    trunc_iters = [it for it in iters_grid if it in (415, 410, 405, 400, 395)]
    # Cap the truncated-grid trials so this stays fast (the rates are large for
    # narrow T, so modest trials resolve them; T=40/30 use the HIGH_RES anchor).
    trunc_trials = min(trials, 200_000)
    trunc_rates = measure_truncated_grid(trunc_iters, truncate_grid, trunc_trials)
    # Splice in the high-resolution trunc_check anchors (trunc_check 2026-06-03,
    # 100k each). (iters, T): (fails, trials). Shows TRUNCATE narrowing breaks
    # convergence at BOTH iters; T<=24 is the cliff.
    HIGH_RES_TRUNC = {
        (405, 40): (0, 100_000), (405, 30): (9, 100_000),
        (405, 24): (156, 100_000), (405, 20): (1006, 100_000),
        (405, 16): (5121, 100_000),
        (395, 40): (19, 100_000), (395, 30): (25, 100_000),
        (395, 24): (203, 100_000), (395, 20): (1085, 100_000),
        (395, 16): (5230, 100_000),
    }
    for k, v in HIGH_RES_TRUNC.items():
        if k[1] in truncate_grid and k[0] in trunc_iters:
            trunc_rates[k] = (v[0] / v[1], v[0], v[1])
    hdr = "iters |" + "".join(f"  T={T:>2d}" for T in truncate_grid)
    print("  " + hdr)
    for it in trunc_iters:
        row = f"  {it:>4d} |"
        for T in truncate_grid:
            r = trunc_rates[(it, T)][0]
            row += f" {r:>6.1e}"
        print(row)
    print("  => TRUNCATE <= 24 breaks reckless (>5e-4); <= 20 is catastrophic. "
          "Only T in {40, 30} are viable.")
    print("\n  Resolution note: aggressive (f<=1.17e-5) needs the HIGH_RES 2M "
          "anchor (UB ~1.5e-6/2M);")
    print("  the per-run sweep (--trials) resolves the lower-iters / narrow-T "
          "points (rates >= 1e-4).")

    # --- Validate the +f-window analytic model empirically (anchor). ---
    print("\n[2] +f-window truncation model validation (pm_prims.rs:114-128):")
    rv = M.reduction_fail_rate(M.DEFAULT_PADDING, trials=2_000_000)
    print(f"  empirical @ padding={rv['emp_padding_used']}: {rv['emp_rate']:.3e} "
          f"({rv['emp_fails']}/{rv['emp_trials']})  vs analytic {rv['analytic_at_val']:.3e}  "
          f"(ratio {rv['model_ratio']:.3f})")
    iters_default = M.expected_iterations(M.N, M.DEFAULT_ITERATIONS_VAR)
    nfw, nms = M.reduction_event_counts(iters_default)
    print(f"  reduction-event counts per EC-add @ iters={iters_default}: "
          f"+f windows = {nfw}, msbs comparators = {nms} "
          "(pointadd.rs:81-102 + bezout_unpack.rs + pm_prims.rs)")

    # --- Build the full candidate set. ---
    # For GCD fail we use the EXACT-mode measurement (the to_bitvector_classical
    # ground truth, gcd_pack.rs:104); the truncated-mode column above shows
    # TRUNCATE has a separate, smaller effect we fold in via the truncate_grid
    # comparator-cost scaling (toffoli()) and a TRUNCATE-convergence guard.
    # The GCD-non-convergence rate at a (iters, TRUNCATE) pair is the DIRECT
    # truncated-mode measurement (trunc_rates / HIGH_RES_TRUNC), which captures
    # both the iteration-budget floor (raise TRUNCATE -> floor at the iters
    # value) AND the comparator-narrowing penalty in ONE number. We take a
    # conservative 95%-CI upper bound (fails+3)/trials when fails is tiny so we
    # never claim a rate the data can't support.
    def _rate_ub(r, f_, t_):
        """rate, or conservative 95% upper bound (f+3)/t when fails tiny."""
        return r if f_ > 0 else 3.0 / t_

    def exact_floor(it):
        """Best-resolved exact-mode GCD floor at this iters (HIGH_RES 2M anchor
        preferred). This is the convergence floor at WIDE TRUNCATE (T>=40, where
        the truncated comparator ~ the exact compare)."""
        if it in HIGH_RES_GCD:
            f_, t_ = HIGH_RES_GCD[it]
            return _rate_ub(f_ / t_, f_, t_)
        r, f_, t_ = gcd_rates[(it, "exact")]
        return _rate_ub(r, f_, t_)

    def gcd_fail_for(it, tr):
        floor = exact_floor(it)
        # The DIRECT truncated measurement at (it, tr) captures the
        # comparator-narrowing penalty. But the truncated anchor uses fewer
        # trials (100k-200k) than the exact 2M floor, so at WIDE TRUNCATE its
        # 0/T upper bound (~3e-5) is LOOSER than the true rate (~2e-6). We must
        # not let that loose bound reject the default config. Rule:
        #   - if the truncated run shows a CLEAR excess over the floor (observed
        #     fails imply a rate well above `floor`), the comparator narrowing is
        #     real -> use the truncated rate (it dominates).
        #   - otherwise (truncated ~ floor within resolution) -> use the
        #     better-resolved exact floor.
        if (it, tr) in trunc_rates:
            r, f_, t_ = trunc_rates[(it, tr)]
            tr_rate = _rate_ub(r, f_, t_)
            # "Clear excess": the truncated point-estimate exceeds 3x the floor
            # AND is backed by >= 5 observed fails (statistically real, not a
            # resolution artifact).
            if f_ >= 5 and r > 3.0 * floor:
                return tr_rate
            return floor
        # iters outside the truncated grid (385, 390): already non-convergent on
        # the budget; TRUNCATE narrowing is moot. Use the exact floor.
        return floor

    candidates = []
    for it in iters_grid:
        for tr in truncate_grid:
            gcd_fail = gcd_fail_for(it, tr)
            for pad in padding_grid:
                for dm in dialog_grid:
                    for v in vents_grid:
                        r = evaluate(it, pad, tr, v, dm, gcd_fail)
                        candidates.append(r)

    # --- For each target, find the cheapest meeting set. ---
    print("\n" + "=" * 100)
    print("[3] Cheapest parameter set per target")
    print("=" * 100)

    for name, p_run_target, cost in TARGETS:
        target_f = M.f_shot_target(p_run_target)
        ok = [r for r in candidates if meets(r, target_f, cost)]
        print(f"\n--- {name}: P(run) >= {p_run_target:.2f}  =>  f_shot <= {target_f:.3e}"
              + (f"  AND qubits <= {cost['max_qubits']} AND toffoli <= {cost['max_toffoli']:,}"
                 if cost else "  (no cost bound)") + " ---")
        if not ok:
            print("  NO parameter set in the grid meets this target.")
            # Absolute Toffoli floor in the grid (ignoring all bounds): tells us
            # whether the cost bound is even physically reachable.
            floor = min(candidates, key=lambda r: r["toffoli"])
            print(f"  Absolute Toffoli floor in grid (any q, any f): "
                  f"tof={floor['toffoli']:,} at q={floor['qubits']}  "
                  + (f"=> 1.7M bound UNREACHABLE (floor {floor['toffoli']:,} > 1,700,000)"
                     if cost and floor["toffoli"] > cost["max_toffoli"]
                     else ""))
            # Show the closest miss by toffoli among f-meeting sets.
            f_ok = [r for r in candidates if r["f_shot"] <= target_f]
            if f_ok and cost:
                best_q = min(f_ok, key=lambda r: r["qubits"])
                best_t = min(f_ok, key=lambda r: r["toffoli"])
                # Best dual-objective point (closest to satisfying both): rank by
                # max over-budget fraction on the two axes.
                def overshoot(r):
                    return max(r["qubits"] / cost["max_qubits"],
                               r["toffoli"] / cost["max_toffoli"])
                best_dual = min(f_ok, key=overshoot)
                print("  Closest f-meeting points (violate cost bound):")
                print("   min-qubits :" + fmt_row(best_q))
                print("   min-toffoli:" + fmt_row(best_t))
                print("   best-dual  :" + fmt_row(best_dual))
                # Also: cheapest q-only and tof-only sets meeting f (the two
                # realizable single-axis configs the user can actually build).
                qonly = [r for r in f_ok if r["qubits"] <= cost["max_qubits"]]
                tonly = [r for r in f_ok if r["toffoli"] <= cost["max_toffoli"]]
                if qonly:
                    bq = min(qonly, key=lambda r: r["toffoli"])
                    print("   q<=1175 only (min tof):" + fmt_row(bq))
                if tonly:
                    bt = min(tonly, key=lambda r: r["qubits"])
                    print("   tof<=1.7M only (min q):" + fmt_row(bt))
            continue
        if name == "aggressive":
            # Aggressive: no cost bound -> minimize qubits then toffoli.
            key = lambda r: (r["qubits"], r["toffoli"])
            label = "min (qubits, then toffoli)"
        else:
            # Reckless: cost-bounded -> minimize toffoli then qubits (toffoli is
            # the harder of the two bounds).
            key = lambda r: (r["toffoli"], r["qubits"])
            label = "min (toffoli, then qubits)"
        ok.sort(key=key)
        print(f"  cheapest [{label}]:")
        print("   *" + fmt_row(ok[0]))
        # Also print a small Pareto-ish table of the top alternatives.
        print("  top alternatives:")
        seen = set()
        shown = 0
        for r in ok:
            sig = (r["qubits"], r["toffoli"])
            if sig in seen:
                continue
            seen.add(sig)
            print("    " + fmt_row(r))
            shown += 1
            if shown >= 6:
                break

    # --- Headline reference rows (the documented configs). ---
    print("\n" + "=" * 100)
    print("[4] Documented config cross-check (pointadd.rs:62-63, :341-365)")
    print("=" * 100)
    it405 = 405
    if it405 in HIGH_RES_GCD:
        f405, t405 = HIGH_RES_GCD[it405]
        gcd405_use = f405 / t405 if f405 > 0 else 3.0 / t405
    else:
        gcd405 = gcd_rates[(it405, "exact")]
        gcd405_use = gcd405[0] if gcd405[1] > 0 else 3.0 / gcd405[2]
    for (dm, v, lbl, meas_q, meas_t) in [
        (5, 0, "M=5 vents=0 (SP1 headline)", 1173, 2_477_000),
        (1, 0, "M=1 raw vents=0",            1329, 2_272_000),
        (1, 90, "M=1 raw vents=90",          1451, 2_126_000),
    ]:
        r = evaluate(405, 30, 40, v, dm, gcd405_use)
        print(f"  {lbl:30s} model: q={r['qubits']:>4d} tof={r['toffoli']:>9,d}   "
              f"measured: q={meas_q} tof={meas_t:,}")


if __name__ == "__main__":
    main()
