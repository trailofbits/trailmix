#!/usr/bin/env python3
"""Nail the radix-2^4 reverse-Horner structure for output -= lam^2 mod q.

Models exact mod-q arithmetic (halve = *inv2, double = *2 mod q) to confirm:
  1. the per-bit reverse-Horner computes output - lam^2,
  2. a radix-2^4 version (one /2^4 per window + 4 subtracts at scales 2^0..2^3,
     one x2^4 per window in the closing batch) computes the SAME thing.
Once equal, the Rust uses mod_mul_pow2_reverse for /2^4, x2^4 batch via mod_mul_pow2,
and the 4 subtracts as mod_sub of (lam<<b)  (or lam at scale 2^b).

Run: python3 scripts/radix4_square_proto.py
"""

import random

N = 256
F = (1 << 32) + 977
Q = (1 << N) - F
INV2 = pow(2, -1, Q)


def halve(a):
    return (a * INV2) % Q


def double(a):
    return (2 * a) % Q


def bit(x, i):
    return (x >> i) & 1


def per_bit_sub(output, lam):
    """The current structure: reverse-Horner, output -= lam^2."""
    a = output % Q
    for i in reversed(range(N)):          # i = 255..0
        if i < N - 1:
            a = halve(a)
        a = (a - bit(lam, N - 1 - i) * lam) % Q
    for _ in range(N - 1):
        a = double(a)
    return a


def radix4_sub(output, lam):
    """Radix-2^4 reverse-Horner. Window w (bits 4w..4w+3), MSB window first.
    Per window: /2^4 (except the very first subtract group), then subtract the
    4 bits at scales 2^3..2^0 (so within a window we still 'halve then subtract'
    4 times, i.e. 4 halves + 4 subtracts -- the radix just batches the FOLDS of
    those halves into one /2^4, but the SCALES are identical to per-bit)."""
    a = output % Q
    nbits = N
    first = True
    # process bits MSB->LSB exactly like per-bit, but we'll group folds by 4.
    # Here (value model) /2^4 == four halves, so structurally identical; the win
    # is purely in the quantum fold-count. Model: same as per-bit but grouped.
    for w in reversed(range(nbits // 4)):       # 63..0
        for bb in reversed(range(4)):           # within window, MSB first
            i = 4 * w + bb                       # this is n-1-i' ... map carefully
            # per-bit uses index j = N-1-i over j=0..255 as bits processed.
            # To match, process the same j-sequence. j goes 0..255 as i goes 255..0.
            pass
    # The above grouping is fiddly to index; instead verify the SIMPLE claim that
    # /2^4 == halve^4 and x2^4 == double^4, so ANY regrouping of the per-bit loop
    # that preserves the halve/subtract ORDER is identical. Demonstrate by running
    # per-bit but asserting halve^4 == /2^4 at the grouping boundaries.
    return per_bit_sub(output, lam)


def halve4(a):
    return (a * pow(INV2, 4, Q)) % Q


def double4(a):
    return (a * pow(2, 4, Q)) % Q


def radix4_offset_sub(output, lam):
    """Fused reverse-Horner, radix-2^4 with OFFSET subtracts (the rfold-rep plan):
    per window w (MSB first): /2^4 (except first), then subtract lam*2^b gated on
    bit 4w+b for b=0..3 (the 4 window bits at window-local scales 2^0..2^3). Then a
    closing x2^4 batch. Must equal output - lam^2 mod q."""
    a = output % Q
    nwin = N // 4
    for w in reversed(range(nwin)):          # 63..0
        if w < nwin - 1:
            a = halve4(a)
        for b in range(4):                   # window-local scale 2^b
            if bit(lam, 4 * w + b):
                a = (a - lam * (1 << b)) % Q
    for _ in range(nwin - 1):                # x2^4 batch (63 of them)
        a = double4(a)
    return a


def main():
    rng = random.Random()
    # (0) per-bit computes output - lam^2 ?
    bad0 = 0
    for _ in range(3000):
        o = rng.randrange(Q)
        l = rng.randrange(Q)
        if per_bit_sub(o, l) != (o - l * l) % Q:
            bad0 += 1
    print(f"per-bit reverse-Horner == output-lam^2 : mismatches {bad0}/3000")

    # (1) the grouping identity: halve^4 == multiply by inv2^4 == '/2^4', and the
    #     subtract scales within a window. Confirm halve^4 and the x2^4 batch.
    x = rng.randrange(Q)
    h4 = x
    for _ in range(4):
        h4 = halve(h4)
    assert h4 == (x * pow(INV2, 4, Q)) % Q
    d4 = x
    for _ in range(4):
        d4 = double(d4)
    assert d4 == (x * pow(2, 4, Q)) % Q
    print("halve^4 == *inv2^4 (=/2^4)  and  double^4 == *2^4  : OK")
    print("=> ANY regrouping of the per-bit halve/subtract loop into 4-bit windows")
    print("   that keeps the halve/subtract ORDER is bit-identical. The radix-2^4")
    print("   win is the quantum FOLD count (one /2^4 fold per window vs 4), NOT a")
    print("   math change. So: 4 right-shifts (free) + 4 mod-subs + ONE window fold.")
    print()
    print("KEY for Rust: within a window do 4x[ right_shift(out, no fold); out -= bit*lam ],")
    print("then ONE reduction fold of the 4-bit shift-drift (mod_mul_pow2_reverse's fold).")
    print("The mod-subs reduce normally (clean); the deferred part is ONLY the /2 folds.")
    print(f"radix4 (grouped per-bit) == output-lam^2 : reuses per-bit, mismatches {bad0}/3000")

    # (2) brute-force the exact radix-4 offset-sub structure.
    def radix_try(output, lam, rev, scale, ndbl, skip_first_div):
        a = output % Q
        wins = range(63, -1, -1) if rev else range(64)
        first = True
        for w in wins:
            if not (first and skip_first_div):
                a = halve4(a)
            first = False
            for b in range(4):
                if bit(lam, 4 * w + b):
                    e = b if scale == "up" else 3 - b
                    a = (a - lam * (1 << e)) % Q
        for _ in range(ndbl):
            a = double4(a)
        return a

    found = None
    for rev in [True, False]:
        for scale in ["up", "down"]:
            for ndbl in [63, 64]:
                for skip in [True, False]:
                    bad = 0
                    for _ in range(400):
                        o = rng.randrange(Q)
                        l = rng.randrange(Q)
                        if radix_try(o, l, rev, scale, ndbl, skip) != (o - l * l) % Q:
                            bad += 1
                            break
                    if bad == 0:
                        found = (rev, scale, ndbl, skip)
                        print(f"MATCH: rev={rev} scale=2^{scale} ndouble4={ndbl} skip_first_div={skip}")
    if found is None:
        print("no simple match -- structure needs a per-window fold/offset rethink")
    else:
        rev, scale, ndbl, skip = found
        bad = sum(
            radix_try(o, l, rev, scale, ndbl, skip) != (o - l * l) % Q
            for o, l in [(rng.randrange(Q), rng.randrange(Q)) for _ in range(5000)]
        )
        print(f"confirmed match: mismatches {bad}/5000")


if __name__ == "__main__":
    main()
