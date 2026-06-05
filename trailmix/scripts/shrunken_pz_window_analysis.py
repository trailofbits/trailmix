#!/usr/bin/env python3
"""
shrunken_pz_window_analysis.py -- measure how narrow the per-step bitlen WINDOWS are
for the cross-gated v3 inversion, to size narrowed prefix-AND comparators, a
bounded clz-diff, and a smaller rotator.

For each step i and register R in {A,B,ca,cb,q}, we record across many shots:
  minbl_R[i], maxbl_R[i]  (the bitlen range R occupies at step i)
The clz/bitlen of R only needs to scan the window [minbl, maxbl] (the MSB is
in there). A comparator A vs B is decided in [min over pair, max over pair].
The division shift s = bitlen(A)-bitlen(B) and multiply shift s2 = ctz(q) are
also bounded per step -> bounds the rotator distance.

Reports: typical window widths (max-min) and the max shift per step, vs the
full scheduled register width -- i.e. how much the narrowing can save.
"""

import secrets

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F


def trailing_zeros(x):
    return (x & -x).bit_length() - 1


def bl(x):
    return x.bit_length()


def run(x_orig, n):
    sgn = x_orig > P // 2
    x = P - x_orig if sgn else x_orig
    A, B = P, x
    ca, cb = 0, 1
    q = 0
    rows = []  # per step: (blA,blB,blca,blcb,blq, s_div, s2_mul)
    for _ in range(n):
        if A == 0 and B == 1 and q == 0:
            rows.append((0, 1, bl(ca), 0, 0, -1, -1))
            continue
        s_div = -1
        s2_mul = -1
        rec = (bl(A), bl(B), bl(ca), bl(cb), bl(q))
        if A < B:
            s2_mul = trailing_zeros(q)
            q ^= 1 << s2_mul
            ca = ca + (cb << s2_mul)
        if ca < cb:
            s = bl(A) - bl(B)
            offset = False
            if s >= 0:
                offset = A < (B << s)
            if offset:
                s -= 1
            if s >= 0:
                s_div = s
                bsh = B << s
                if A >= bsh:
                    A -= bsh
                    q ^= 1 << s
        if q == 0 and A != 0:
            A, B = B, A
            ca, cb = cb, ca
        rows.append(rec + (s_div, s2_mul))
    return rows


def main():
    TRIALS = 4000
    N = 502
    # per step: for each reg, min and max bitlen; max s_div, max s2_mul
    minbl = [[10**9] * 5 for _ in range(N)]
    maxbl = [[0] * 5 for _ in range(N)]
    maxsdiv = [0] * N
    maxs2 = [0] * N
    for _ in range(TRIALS):
        x = secrets.randbelow(P - 1) + 1
        rows = run(x, N)
        for i, r in enumerate(rows):
            for k in range(5):
                if r[k] < minbl[i][k]:
                    minbl[i][k] = r[k]
                if r[k] > maxbl[i][k]:
                    maxbl[i][k] = r[k]
            if r[5] > maxsdiv[i]:
                maxsdiv[i] = r[5]
            if r[6] > maxs2[i]:
                maxs2[i] = r[6]

    # windows
    names = ["A", "B", "ca", "cb", "q"]
    print("=" * 74)
    print(f"v3 per-step bitlen WINDOWS (max-min), {TRIALS} shots")
    print("=" * 74)
    # aggregate window stats per register over the run
    for k in range(5):
        wins = [maxbl[i][k] - minbl[i][k] for i in range(N) if maxbl[i][k] > 0]
        wins.sort()
        mean = sum(wins) / len(wins)
        print(f"  {names[k]:3s} window (max-min bitlen): "
              f"mean={mean:5.1f} p50={wins[len(wins)//2]:3d} "
              f"max={wins[-1]:3d}  (full reg width ~ maxbl)")
    print()
    sd = sorted(s for s in maxsdiv if s >= 0)
    s2 = sorted(s for s in maxs2 if s >= 0)
    print(f"  division shift s : mean-max-per-step={sum(sd)/len(sd):.1f} "
          f"overall max={sd[-1]}  -> rotator distance bound")
    print(f"  multiply shift s2: mean-max-per-step={sum(s2)/len(s2):.1f} "
          f"overall max={s2[-1]}")
    print()
    # sample a few steps
    print("  step :  A[min-max]  B[min-max]  ca[min-max]  cb[min-max]  s_div s2")
    for i in [0, 1, 50, 125, 250, 375, 450, 495]:
        a = f"{minbl[i][0]}-{maxbl[i][0]}"
        b = f"{minbl[i][1]}-{maxbl[i][1]}"
        c = f"{minbl[i][2]}-{maxbl[i][2]}"
        d = f"{minbl[i][3]}-{maxbl[i][3]}"
        print(f"  {i:4d} : {a:>10} {b:>10} {c:>11} {d:>11}   {maxsdiv[i]:4d} {maxs2[i]:3d}")
    print()
    print("  Interpretation: if windows are small, clz/bitlen + comparators only")
    print("  need to scan ~window bits (prefix-AND over [min,max]), and the")
    print("  rotator only needs to cover the max shift, not the full register.")


if __name__ == "__main__":
    main()
