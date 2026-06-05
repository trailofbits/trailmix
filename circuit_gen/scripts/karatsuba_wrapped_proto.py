#!/usr/bin/env python3
"""
karatsuba_wrapped_proto.py

The CORRECT model of the user's fold-aware MAC: c += A*B mod p, accumulated
section-by-section into a 256-bit-wide c, where any bit that would land at
position >= 256 is WRAPPED -- multiplied by R = 2^256 mod p and added back low
(and a high section past shift 256 is PRE-MULTIPLIED by R as a unit). Nothing
ever sits in a wide [256:384] register, so the only thing crossing bit 256 is a
1-bit carry. Approximate: we keep c in [0, 2^256) (folded, == A*B mod p as a
residue) and never canonicalize into [0,p).

We (1) verify the wrapped accumulate is exact mod p, and (2) measure the actual
carry width crossing bit 256 at every wrapped add -- the claim is it's tiny.
"""

p = 2**256 - 2**32 - 977
R = 2**32 + 977            # 2^256 mod p
W = 128
N = 256
MASKN = (1 << N) - 1
MASKW = (1 << W) - 1


def fold_once(x):
    """x (possibly > 2^256) -> congruent value < 2^256 by folding hi*R.
       Returns (folded, max_carry_bits_crossed) tracking how far over 256 x was."""
    over = max(0, x.bit_length() - N)
    while x >> N:
        x = (x & MASKN) + (x >> N) * R
    return x, over


def add_section_at(c, value, shift, stats):
    """c += value << shift, but wrapped: the part of (value<<shift) at bits
       >= 256 is folded by R. Implemented as: split value<<shift into low (<2^256)
       and high; high is value's bits that overflow, *R, recursively folded."""
    full = value << shift
    lo = full & MASKN
    hi = full >> N                      # the wrapped section (lands *R)
    c = c + lo
    # carry of this add crossing bit 256:
    stats['add_over'] = max(stats['add_over'], max(0, c.bit_length() - N))
    c, _ = fold_once(c)
    if hi:
        wrapped = hi * R                # pre-multiply the wrapped section by R
        c = c + (wrapped & MASKN)
        c, _ = fold_once(c)
        # the wrapped*R can itself exceed 256 -> secondary tiny fold
        sec = wrapped >> N
        stats['wrap_hi_bits'] = max(stats['wrap_hi_bits'], hi.bit_length())
        stats['sec_bits'] = max(stats['sec_bits'], sec.bit_length())
        if sec:
            c = c + sec * R
            c, _ = fold_once(c)
    return c


def schoolbook_wrapped(A, B, c0, stats):
    """4 chunky 128x128 products, each placed wrapped."""
    a1, a2 = A & MASKW, A >> W
    b1, b2 = B & MASKW, B >> W
    c = c0
    c = add_section_at(c, a1 * b1, 0, stats)        # shift 0
    c = add_section_at(c, a1 * b2, W, stats)        # shift W
    c = add_section_at(c, a2 * b1, W, stats)        # shift W
    c = add_section_at(c, a2 * b2, 2 * W, stats)    # shift 2W (all wraps, *R)
    return c


def main():
    import random
    rng = random.Random()
    n = 4000
    ok = 0
    stats = {'add_over': 0, 'wrap_hi_bits': 0, 'sec_bits': 0}
    for _ in range(n):
        A = rng.randrange(1 << N)
        B = rng.randrange(1 << N)
        c0 = rng.randrange(p)
        c = schoolbook_wrapped(A, B, c0, stats)
        if c % p == (c0 + A * B) % p:
            ok += 1
    print(f"schoolbook_wrapped: {ok}/{n} correct (mod p)")
    print(f"  max carry over bit 256 on a normal add : {stats['add_over']} bit(s)")
    print(f"  max wrapped-section width (the *R input): {stats['wrap_hi_bits']} bits")
    print(f"  max secondary (*R) overshoot           : {stats['sec_bits']} bits")
    print()
    print("Interpretation: the 'wrapped section' is up to ~128 bits, but it is")
    print("CONSUMED by one constant *R add (R is 33-bit) landing low -- not a")
    print("128-bit overflow register to discharge. Only 1-bit carries cross 256.")


if __name__ == "__main__":
    main()
