#!/usr/bin/env python3
"""
shrunken_pz_flag_clear.py -- test candidate reversible clearing rules for the
v3 div/mul selector flag. The flag `cmp = (A<B)` (1=multiply, 0=divide)
is computed at step start to gate the substep. Question: which clear rule
returns cmp to 0 at EVERY step (=> no garbage), vs leaks (cmp stuck).

We test, per step, several end-of-step clear XOR conditions and count how
many steps leave cmp != 0 after the clear. We also test cmp as a PERSISTENT
phase bit (never recomputed; only updated by the rule) and check it tracks
(A<B) and returns to a clean value.

User's proposal under test: clear via ((A_end<B) OR g_swap).
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

    # garbage counters for several candidate clear rules (fresh-ancilla model:
    # cmp set = (A<B) at start, cleared by rule at end; count residual !=0)
    leak_recompute = 0          # clear ^= (A_end < B_end)   [pre-swap]
    leak_user = 0               # clear ^= ((A_end<B) OR g_swap)   [pre-swap test]
    leak_user_postswap = 0      # clear ^= ((A_end<B) OR g_swap) [post-swap]
    leak_xor_swap = 0           # clear ^= ((A_end<B) XOR g_swap)

    # persistent phase bit p (1=multiply): updated, never recomputed.
    # forward rule candidate: p ^= ((A_end<B) != p_before_used_as_(A_start<B))
    # i.e. p := (A_end<B) ... test if a single bit stays consistent.
    p = 0   # start in division (A=P >= B=x)
    p_track_mismatch = 0        # times p != (A<B) at step START
    p_final = None

    for _ in range(n_iters):
        active = not (A == 0 and B == 1 and q == 0)
        if not active:
            break

        cmp_start = 1 if (A < B) else 0     # the selector value used this step

        # persistent p: check it matches the true phase at step start
        if p != cmp_start:
            p_track_mismatch += 1

        # ---- the v3 substep ----
        if A >= B:
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
        else:
            s2 = trailing_zeros(q)
            q ^= (1 << s2)
            cb <<= s2
            ca = ca + cb
            o = (ca.bit_length() != cb.bit_length())
            if o:
                cb <<= 1
                s2 += 1
            cb >>= s2

        a_lt_b_preswap = 1 if (A < B) else 0
        g_swap = 1 if (q == 0 and A != 0) else 0

        # ---- clear-rule evaluation (fresh-ancilla model, BEFORE swap) ----
        # recompute rule:
        if (cmp_start ^ a_lt_b_preswap) != 0:
            leak_recompute += 1
        # user's (A<B OR g_swap), pre-swap:
        clr_user = a_lt_b_preswap | g_swap
        if (cmp_start ^ clr_user) != 0:
            leak_user += 1
        # (A<B) XOR g_swap:
        clr_xor = a_lt_b_preswap ^ g_swap
        if (cmp_start ^ clr_xor) != 0:
            leak_xor_swap += 1

        # ---- the swap ----
        if g_swap:
            A, B = B, A
            ca, cb = cb, ca
            parity = not parity

        a_lt_b_postswap = 1 if (A < B) else 0
        # user's (A<B OR g_swap), post-swap:
        clr_user_post = a_lt_b_postswap | g_swap
        if (cmp_start ^ clr_user_post) != 0:
            leak_user_postswap += 1

        # ---- persistent p update: p should track (A<B) at NEXT step start ----
        # candidate clean rule: p ^= (A_lt_b at this step's start) XOR
        #   (A_lt_b at next step's start). We approximate "next start" by the
        #   post-swap A<B (the state entering next step).
        p = a_lt_b_postswap   # set p to the true next-phase (functional, redundant)

    p_final = p
    return {
        "leak_recompute": leak_recompute,
        "leak_user": leak_user,
        "leak_user_postswap": leak_user_postswap,
        "leak_xor_swap": leak_xor_swap,
        "p_track_mismatch": p_track_mismatch,
        "p_final": p_final,
    }


def main():
    TRIALS = 3000
    keys = ["leak_recompute", "leak_user", "leak_user_postswap",
            "leak_xor_swap", "p_track_mismatch"]
    agg = {k: [] for k in keys}
    pfin = {}
    for _ in range(TRIALS):
        x = secrets.randbelow(P - 1) + 1
        r = run(x)
        for k in keys:
            agg[k].append(r[k])
        pfin[r["p_final"]] = pfin.get(r["p_final"], 0) + 1

    print("=" * 72)
    print(f"v3 selector clear-rule test, {TRIALS} random secp x")
    print("  (residual garbage per inversion: # steps cmp != 0 after clear)")
    print("=" * 72)

    def stat(label, arr):
        arr = sorted(arr)
        print(f"  {label:34s} mean={sum(arr)/len(arr):8.2f} "
              f"p50={arr[len(arr)//2]:>5} max={arr[-1]:>5}")

    stat("recompute (A_end>=B) [baseline]", agg["leak_recompute"])
    stat("USER (A<B OR g_swap) pre-swap", agg["leak_user"])
    stat("USER (A<B OR g_swap) post-swap", agg["leak_user_postswap"])
    stat("(A<B) XOR g_swap", agg["leak_xor_swap"])
    print()
    stat("persistent p mismatch vs (A<B)", agg["p_track_mismatch"])
    print(f"  persistent p final values: {pfin}")
    print()
    print("  A rule with 0 residual garbage on ALL trials = a clean clear.")


if __name__ == "__main__":
    main()
