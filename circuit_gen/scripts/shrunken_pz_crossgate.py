#!/usr/bin/env python3
"""
shrunken_pz_crossgate.py -- verify the CROSS-GATED reversible realization of
pz_big_step_v3 is fully clean (zero leaked flags).

Key (user's Zalka invariant): division touches only (A,B,q); multiply
touches only (ca,cb,q). Phase: division <=> ca<cb, multiply <=> A<B.

So gate each substep on the comparison of the pair it does NOT modify:
  - division gated on g_div = (ca < cb)   [division leaves ca,cb fixed
                                           => g_div recomputes identical
                                           => CLEAN uncompute, incl. dk]
  - multiply gated on g_mul = (A < B)     [multiply leaves A,B fixed
                                           => CLEAN uncompute]
  - swap gated on g_swap = (q==0 & A!=0)  [swap preserves it => CLEAN]

Ordering MULTIPLY-FIRST then DIVISION then SWAP, each gate computed right
before its substep and uncomputed right after, reading the pair the
substep left stationary.

We simulate the exact reversible step and CHECK, per step, that recomputing
each gate after its substep equals the value used (clean uncompute => 0
residual). Plus end-to-end inverse correctness.
"""

import secrets

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F


def trailing_zeros(x):
    return (x & -x).bit_length() - 1


def run(x_orig, n_iters=520):
    sgn = x_orig > P // 2
    x = P - x_orig if sgn else x_orig
    A, B = P, x
    ca, cb = 0, 1
    q = 0
    parity = True

    leak_gdiv = 0
    leak_gmul = 0
    leak_gswap = 0
    double_fire = 0   # steps where BOTH multiply and division fired (must be 0)
    no_fire_active = 0  # active steps where NEITHER fired (must be 0)

    for _ in range(n_iters):
        active = not (A == 0 and B == 1 and q == 0)
        if not active:
            break

        fired_mul = False
        fired_div = False

        # ---- MULTIPLY substep, gated on g_mul=(A<B). Touches ca,cb,q only. ----
        g_mul = 1 if (A < B) else 0
        A0, B0 = A, B           # snapshot the pair multiply must leave fixed
        if g_mul:
            fired_mul = True
            s2 = trailing_zeros(q)
            q ^= (1 << s2)
            cb <<= s2
            ca = ca + cb
            o = (ca.bit_length() != cb.bit_length())
            if o:
                cb <<= 1
                s2 += 1
            cb >>= s2
        # clean-uncompute check: g_mul recomputed on (A,B) -- unchanged by mul
        if (1 if (A < B) else 0) != g_mul:
            leak_gmul += 1
        assert (A, B) == (A0, B0), "multiply touched A or B!"

        # ---- DIVISION substep, gated on g_div=(ca<cb). Touches A,B,q only. ----
        g_div = 1 if (ca < cb) else 0
        ca0, cb0 = ca, cb       # snapshot the pair division must leave fixed
        if g_div:
            fired_div = True
            s = A.bit_length() - B.bit_length()
            B <<= s
            offset = (A < B)
            if offset:
                s -= 1
                if s >= 0:
                    B >>= 1
            if s >= 0:
                A -= B
                B >>= s
                q ^= (1 << s)
                s -= trailing_zeros(q)
        # clean-uncompute check: g_div recomputed on (ca,cb) -- unchanged by div
        if (1 if (ca < cb) else 0) != g_div:
            leak_gdiv += 1
        assert (ca, cb) == (ca0, cb0), "division touched ca or cb!"

        # ---- SWAP, gated on g_swap=(q==0 & A!=0). ----
        g_swap = 1 if (q == 0 and A != 0) else 0
        if g_swap:
            A, B = B, A
            ca, cb = cb, ca
            parity = not parity
        if (1 if (q == 0 and A != 0) else 0) != g_swap:
            leak_gswap += 1

        if fired_mul and fired_div:
            double_fire += 1
        if active and not fired_mul and not fired_div:
            no_fire_active += 1

    # correctness
    ok = (A == 0 and B == 1 and ca == P)
    cb_out = cb
    if not parity:
        cb_out = P - cb_out
    inv_ok = ok and ((cb_out * x) % P == 1)
    if sgn:
        cb_out = P - cb_out
    final_inv = cb_out
    return {
        "leak_gdiv": leak_gdiv, "leak_gmul": leak_gmul,
        "leak_gswap": leak_gswap, "double_fire": double_fire,
        "no_fire_active": no_fire_active,
        "inv_ok": inv_ok, "inv": final_inv,
    }


def main():
    TRIALS = 4000
    tot = {k: 0 for k in ["leak_gdiv", "leak_gmul", "leak_gswap",
                          "double_fire", "no_fire_active"]}
    correct = 0
    for _ in range(TRIALS):
        x = secrets.randbelow(P - 1) + 1
        r = run(x)
        for k in tot:
            tot[k] += r[k]
        if r["inv_ok"] and r["inv"] == pow(x, P - 2, P):
            correct += 1

    print("=" * 72)
    print(f"CROSS-GATED v3 reversible realization, {TRIALS} random secp x")
    print("=" * 72)
    print(f"  inverse correct:                 {correct}/{TRIALS}")
    print()
    print("  Total leaked-flag events across ALL inversions (want 0):")
    print(f"    g_div=(ca<cb) leaks:           {tot['leak_gdiv']}")
    print(f"    g_mul=(A<B)   leaks:           {tot['leak_gmul']}")
    print(f"    g_swap        leaks:           {tot['leak_gswap']}")
    print()
    print("  Substep-exclusion sanity:")
    print(f"    double-fire (mul & div) steps: {tot['double_fire']}  (want 0)")
    print(f"    active-but-no-fire steps:      {tot['no_fire_active']}  (want 0)")
    print()
    clean = (tot['leak_gdiv'] == tot['leak_gmul'] == tot['leak_gswap']
             == tot['double_fire'] == tot['no_fire_active'] == 0)
    print("  ==> FULLY CLEAN (zero garbage)" if clean and correct == TRIALS
          else "  ==> NOT clean / incorrect")


if __name__ == "__main__":
    main()
