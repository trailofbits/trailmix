#!/usr/bin/env python3
"""
shrunken_pz_phase_probe.py -- instrument pz_big_step_v3 (kaliski_test.py:487)
to understand its phase/gate structure for the reversible realization.

v3 is the FUSED, TAPELESS Euclidean-quotient EEA with a SINGLE q register:
  - DIVISION phase (A>=B): shift-subtract A by aligned B, SET one bit of q
    each step (q builds high->low to the full Euclidean quotient floor(A/B)).
  - MULTIPLY phase (A<B): drain q lowest-bit-first, MAC cb into ca.
  - mul->div boundary: when q==0 (drained) and A!=0, swap A<->B, ca<->cb,
    flip parity.

The reversible question: which per-step control flags clean by recompute,
and which leak (a flag computed from a register the gated op then moves
across its own threshold). We track:
  - g = (A>=B): the div/mul selector. Cleans iff (A>=B) is unchanged across
    the step's mutations (before the swap). LEAKS on the step where A
    crosses >=B -> <B (the last subtract of a division phase).
  - g_swap = (q==0 and A!=0): the swap trigger. The swap preserves q==0 and
    A!=0, so it should clean by recompute (migrate-style witness).
We count the actual leaks per inversion + the peak pack composition.
"""

import secrets

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F


def trailing_zeros(x):
    return (x & -x).bit_length() - 1


def run_v3_instrumented(x_orig, n_iters=520):
    sgn = x_orig > P // 2
    x = P - x_orig if sgn else x_orig
    A, B = P, x
    ca, cb = 0, 1
    q = 0
    parity = True

    n_div = n_mul = n_swap = n_idle = 0
    g_leaks = 0          # selector (A>=B) crossings that won't recompute-clean
    gswap_leaks = 0      # swap-trigger crossings that won't recompute-clean
    max_q_bitlen = 0
    max_AB_pack = 0      # max bitlen(A)+bitlen(B)
    max_cc_pack = 0      # max bitlen(ca)+bitlen(cb)
    max_total_pack = 0   # A+B+ca+cb+q bitlens, the live footprint proxy
    converge_iter = None

    for it in range(n_iters):
        active = not (A == 0 and B == 1 and q == 0)
        if not active:
            if converge_iter is None:
                converge_iter = it
            n_idle += 1
            continue

        g_pre = (A >= B)                    # the selector, A>=B at step start
        q_pre = q
        A_pre = A

        offset = False
        if A >= B:
            n_div += 1
            s = A.bit_length() - B.bit_length()
            B <<= s
            offset = (A < B)
            if offset:
                s -= 1
                if s >= 0:
                    B >>= 1
            if s >= 0:
                offset ^= (A.bit_length() != B.bit_length())
                A -= B
                B >>= s
                q ^= (1 << s)
                s -= trailing_zeros(q)
                assert offset == 0 and s == 0, f"{offset} {s}"
        else:
            n_mul += 1
            s2 = trailing_zeros(q)
            q ^= (1 << s2)
            cb <<= s2
            ca = ca + cb
            o = (ca.bit_length() != cb.bit_length())
            if o:
                cb <<= 1
                s2 += 1
            cb >>= s2

        # selector clean check: recompute (A>=B) on the post-mutation state
        # (BEFORE the swap, which is the standard uncompute point).
        g_post_preswap = (A >= B)
        if g_post_preswap != g_pre:
            g_leaks += 1

        # the swap (mul->div boundary)
        gswap_pre = (q == 0 and A != 0)
        if gswap_pre:
            A, B = B, A
            ca, cb = cb, ca
            parity = not parity
            n_swap += 1
        # swap-trigger clean check: recompute (q==0 and A!=0) post-swap
        gswap_post = (q == 0 and A != 0)
        if gswap_pre and (gswap_post != gswap_pre):
            gswap_leaks += 1

        max_q_bitlen = max(max_q_bitlen, q.bit_length())
        max_AB_pack = max(max_AB_pack, A.bit_length() + B.bit_length())
        max_cc_pack = max(max_cc_pack, ca.bit_length() + cb.bit_length())
        max_total_pack = max(
            max_total_pack,
            A.bit_length() + B.bit_length()
            + ca.bit_length() + cb.bit_length() + q.bit_length(),
        )

    assert A == 0 and B == 1 and ca == P, f"A {A} B {B} ca {ca} cb {cb}"
    cb_out = cb
    if not parity:
        cb_out = P - cb_out
    assert (cb_out * x) % P == 1
    if sgn:
        cb_out = P - cb_out
    return {
        "inv": cb_out,
        "n_div": n_div, "n_mul": n_mul, "n_swap": n_swap,
        "converge_iter": converge_iter if converge_iter is not None else n_iters,
        "g_leaks": g_leaks, "gswap_leaks": gswap_leaks,
        "max_q_bitlen": max_q_bitlen,
        "max_AB_pack": max_AB_pack, "max_cc_pack": max_cc_pack,
        "max_total_pack": max_total_pack,
    }


def main():
    TRIALS = 4000
    n_iters = 520
    ok = 0
    fail = 0
    agg = {k: [] for k in
           ["n_div", "n_mul", "n_swap", "converge_iter", "g_leaks",
            "gswap_leaks", "max_q_bitlen", "max_AB_pack", "max_cc_pack",
            "max_total_pack"]}
    for _ in range(TRIALS):
        x = secrets.randbelow(P - 1) + 1
        try:
            r = run_v3_instrumented(x, n_iters)
        except AssertionError:
            fail += 1
            continue
        if r["inv"] == pow(x, P - 2, P):
            ok += 1
        else:
            fail += 1
        for k in agg:
            agg[k].append(r[k])

    def stats(label, arr, unit=""):
        arr = sorted(arr)
        n = len(arr)
        mean = sum(arr) / n
        p50 = arr[n // 2]
        p99 = arr[min(n - 1, int(0.99 * n))]
        p999 = arr[min(n - 1, int(0.999 * n))]
        mx = arr[-1]
        print(f"  {label:26s} mean={mean:9.1f} p50={p50:>7} p99={p99:>7} "
              f"p99.9={p999:>7} max={mx:>7} {unit}")

    print("=" * 78)
    print(f"pz_big_step_v3 instrumented, {TRIALS} random secp x, n_iters={n_iters}")
    print("=" * 78)
    print(f"  correct: {ok}/{TRIALS}   (budget/assert fails: {fail})")
    print()
    stats("div steps", agg["n_div"])
    stats("mul steps", agg["n_mul"])
    stats("swaps (= #quotients)", agg["n_swap"])
    stats("converge iter", agg["converge_iter"])
    print()
    print("  --- GATE CLEANING (per inversion) ---")
    stats("g=(A>=B) leaks", agg["g_leaks"])
    stats("g_swap=(q==0&A!=0) leaks", agg["gswap_leaks"])
    print()
    print("  --- REGISTER SIZING / PEAK proxy (bit-lengths) ---")
    stats("max q bitlen", agg["max_q_bitlen"], "bits (size the q reg)")
    stats("max A+B pack", agg["max_AB_pack"], "bits")
    stats("max ca+cb pack", agg["max_cc_pack"], "bits")
    stats("max total live pack", agg["max_total_pack"], "bits")
    print()
    print("  Interpretation:")
    print("   - g_swap leaks == 0 confirms the swap-trigger cleans by recompute")
    print("     (swap preserves q==0 & A!=0): the mul->div boundary is FREE.")
    print("   - g leaks == #quotients would mean only the div-phase-END marker")
    print("     leaks: a minimal ~150-bit garbage tape, far under binary 670 /")
    print("     gamma 543. q reg is tiny (no materialized tape).")


if __name__ == "__main__":
    main()
