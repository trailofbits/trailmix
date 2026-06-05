#!/usr/bin/env python3
"""
shrunken_pz_delta_s_probe.py -- measure whether the division B<<s rotate can use a
NARROW (2-bit) shifter by tracking a DELTA shift instead of the absolute s.

Current impl: each division rotates B up by s = bitlen(A)-bitlen(B) (~20, so a
5-6 bit barrel shifter, 5-6 layers x ~n cswaps -> 28% of all Toffolis), then
back down by s_eff. The absolute s is large.

Idea: keep B in a running-shifted FRAME (B_framed = B << shift). Then
  - the subtraction A -= B_framed needs NO shift (B already aligned),
  - the per-step REALIGNMENT shift = shift - new_shift = bitlen(B_framed) -
    bitlen(A_new)  (how many leading bits A dropped) -- should be SMALL.

But multiply/swap between divisions RESET the frame (B changes / A,B swap), so
the delta only helps for division steps that CONTINUE a phase (B unchanged since
the last division). This probe measures, over random secp x:
  1. distribution of the absolute up-shift s (confirms ~20 / 5-6 bit shifter),
  2. distribution of the realignment delta within a phase (B unchanged),
  3. fraction of division steps that are phase-continuations vs frame-resets,
  4. the shifter width a delta scheme would need (max delta, tail past 2/3 bits).

We run the EXACT cross-gated v3 algorithm (shrunken_pz_crossgate.py) and instrument
the division substep.  NO RNG SEEDING (per repo rule).
"""

import secrets
from collections import Counter

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F


def trailing_zeros(x):
    return (x & -x).bit_length() - 1


def run_instrumented(x_orig, n_iters=520):
    """Run cross-gated v3; return (div_records, mul_s2_list).
    div_records: per-division (s_up_eff, B_before, bl_a_pre, bl_a_post).
    mul_s2_list: per-multiply the cb<<s2 shift amount."""
    sgn = x_orig > P // 2
    x = P - x_orig if sgn else x_orig
    A, B = P, x
    ca, cb = 0, 1
    q = 0
    div_records = []
    mul_s2 = []

    for _ in range(n_iters):
        if A == 0 and B == 1 and q == 0:
            break

        # ---- MULTIPLY (A<B): touches ca,cb,q. cb<<s2 rotate. ----
        if A < B:
            s2 = trailing_zeros(q)
            mul_s2.append(s2)
            q ^= (1 << s2)
            cb <<= s2
            ca = ca + cb
            o = (ca.bit_length() != cb.bit_length())
            if o:
                cb <<= 1
                s2 += 1
            cb >>= s2

        # ---- DIVISION (ca<cb): touches A,B,q. B<<s rotate. ----
        if ca < cb:
            B_before = B
            bl_a_pre = A.bit_length()
            s = A.bit_length() - B.bit_length()
            B <<= s
            offset = (A < B)
            if offset:
                s -= 1
                if s >= 0:
                    B >>= 1
            s_eff = s if s >= 0 else 0
            if s >= 0:
                A -= B
                B >>= s
                q ^= (1 << s)
                s -= trailing_zeros(q)
            bl_a_post = A.bit_length()
            div_records.append((s_eff, B_before, bl_a_pre, bl_a_post))

        # ---- SWAP (q==0 & A!=0). ----
        if q == 0 and A != 0:
            A, B = B, A
            ca, cb = cb, ca

    return div_records, mul_s2


def hist_report(name, hist, note=""):
    print(f"{name} {note}")
    tot = sum(hist.values())
    cum = 0
    for k in sorted(hist):
        cum += hist[k]
        if k <= 8 or k % 4 == 0 or k >= 28:
            print(f"  {k:2d}: {100*hist[k]/tot:5.2f}%  (cum {100*cum/tot:6.2f}%)")
    maxk = max(hist)
    mean = sum(k * v for k, v in hist.items()) / tot
    print(f"  mean={mean:.2f}  max={maxk}  -> width {max(1, maxk.bit_length())} bits")
    print()


def main():
    N = 4000
    s_up_hist = Counter()      # division up-shift s_eff
    s2_hist = Counter()        # multiply cb<<s2 shift
    delta_hist = Counter()     # within-phase realignment delta (A-drop of prev div)
    n_div = 0
    n_mul = 0
    n_continuation = 0
    n_reset = 0
    delta_over3 = 0
    delta_over7 = 0
    cont_delta_total = 0

    for _ in range(N):
        x = secrets.randbelow(P - 1) + 1
        recs, mul_s2 = run_instrumented(x)
        for s2 in mul_s2:
            n_mul += 1
            s2_hist[min(s2, 40)] += 1
        prev_B = None
        prev_drop = None  # how much A dropped in the previous division
        for (s_eff, B_before, bl_pre, bl_post) in recs:
            n_div += 1
            s_up_hist[min(s_eff, 40)] += 1
            drop = bl_pre - bl_post  # A's bitlen drop this division
            if prev_B is not None and B_before == prev_B:
                # phase continuation: B is still framed at the PREVIOUS division's
                # alignment. To re-align for THIS division, shift B down by how
                # much A dropped in the previous division (= prev_drop).
                n_continuation += 1
                delta_hist[min(prev_drop, 40)] += 1
                cont_delta_total += prev_drop
                if prev_drop > 3:
                    delta_over3 += 1
                if prev_drop > 7:
                    delta_over7 += 1
            else:
                n_reset += 1
            prev_B = B_before
            prev_drop = drop

    print(f"=== pz_v3 delta_s probe (N={N} random secp x) ===")
    print(f"division steps: {n_div} ({n_div/N:.1f}/inv)   "
          f"multiply steps: {n_mul} ({n_mul/N:.1f}/inv)")
    print(f"  phase-continuations (B unchanged from prev div): "
          f"{n_continuation} ({100*n_continuation/n_div:.1f}%)")
    print(f"  frame-resets       (B changed / first div):     "
          f"{n_reset} ({100*n_reset/n_div:.1f}%)")
    print()
    hist_report("DIVISION up-shift s_eff:", s_up_hist,
                "(current B<<s rotate; CCX on s[i]=0 are free in tof)")
    hist_report("MULTIPLY shift s2 = ctz(q):", s2_hist, "(cb<<s2 rotate)")
    if n_continuation:
        hist_report("WITHIN-PHASE realignment delta (framed-B down-shift):",
                    delta_hist, "(only the 33% continuations could use this)")
        print(f"  continuations needing > 2-bit (delta>3): "
              f"{100*delta_over3/n_continuation:.2f}%")
        print(f"  continuations needing > 3-bit (delta>7): "
              f"{100*delta_over7/n_continuation:.2f}%")


if __name__ == "__main__":
    main()
