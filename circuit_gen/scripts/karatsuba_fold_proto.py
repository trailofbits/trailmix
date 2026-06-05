#!/usr/bin/env python3
"""
karatsuba_fold_proto.py

Verify the fold-aware, direct-accumulate 1-level Karatsuba modular MAC:
    c += A*B mod p
where the three sub-products are accumulated straight into c (no 512-bit
product temp, hence no reversible-uncompute tax) and the high operand is
pre-scaled by 2^(2W) == R so the high/middle products land already reduced
(reduction is free).

We test the USER'S LITERAL steps and several closing variants, on random
secp256k1-sized inputs, and report which schemes satisfy c == (c0 + A*B) % p.
"""

p = 2**256 - 2**32 - 977
R = 2**32 + 977                  # 2^256 mod p
W = 128
M = (1 << W) - 1
TWO_2W = pow(2, 2 * W, p)        # 2^256 mod p == R
INV_2W = pow(2, -2 * W, p)       # 2^-256 mod p


def split(X):
    return X & M, X >> W          # (x1 low, x2 high)


def target(A, B, c0):
    return (c0 + A * B) % p


def scheme_literal(A, B, c0):
    """The user's literal steps."""
    a1, a2 = split(A)
    b1, b2 = split(B)
    c = c0
    c = c + a1 * b1                       # 1
    b2 = (b2 * TWO_2W) % p                # 2: b2 *= 2^2W (== *R)
    c = c + a2 * b2                       # 3: high term, auto-folded
    b2 = (b2 * INV_2W) % p                # 4: undo
    b2 = b2 - a1                          # 5
    a2 = a2 - b1                          # 6
    c = c - a2 * b2 * (1 << W)            # 7
    return c % p


def scheme_sub_correct(A, B, c0):
    """Textbook subtractive Karatsuba, direct-accumulate, fold-aware.
       middle = P0 + P2 - (a1-a2)(b1-b2);  A*B = P0 + middle*2^W + P2*2^2W.
       => c += P0*(1+2^W) + P2*(2^W+2^2W) - (a1-a2)(b1-b2)*2^W   (all mod p)."""
    a1, a2 = split(A)
    b1, b2 = split(B)
    P0 = a1 * b1
    P2 = a2 * b2
    Pm = (a1 - a2) * (b1 - b2)
    c = c0
    c += P0 * (1 + (1 << W))
    c += P2 * ((1 << W) + (1 << (2 * W)))
    c -= Pm * (1 << W)
    return c % p


def scheme_add_correct(A, B, c0):
    """Additive Karatsuba: middle = (a1+a2)(b1+b2) - P0 - P2."""
    a1, a2 = split(A)
    b1, b2 = split(B)
    P0 = a1 * b1
    P2 = a2 * b2
    Ps = (a1 + a2) * (b1 + b2)
    c = c0
    c += P0
    c += (Ps - P0 - P2) * (1 << W)
    c += P2 * (1 << (2 * W))
    return c % p


def scheme_literal_with_diag(A, B, c0):
    """Literal scheme, but report the residual = target - got (mod p) and
       whether it has a clean closed form, to reverse-engineer the intent."""
    got = scheme_literal(A, B, c0)
    tgt = target(A, B, c0)
    return (tgt - got) % p


SCHEMES = [
    ("literal (user's exact steps)", scheme_literal),
    ("subtractive (a1-a2)(b1-b2)", scheme_sub_correct),
    ("additive  (a1+a2)(b1+b2)", scheme_add_correct),
]


def overflow_profile():
    """For the subtractive fold-aware scheme realized as direct accumulates
    into a narrow c (reduced after each term), report the bit-width of the
    pre-fold overshoot at each accumulate -- i.e. how many bits must be
    discharged (the cleanup burden that blocked mod_mul_lazy). c stays < p
    between terms via folding; the question is how big the transient is.

    Terms (subtractive):  c += P0 ; c += P0<<W ; c += P2<<W ; c += P2<<2W ; c -= Pm<<W
    where each accumulate is (c_reduced + term), and we fold the bits >=256.
    """
    import random
    rng = random.Random()
    print("\nOverflow (bits above 256) per accumulate, worst of 2000 trials:")
    labels = ["P0<<0", "P0<<W", "P2<<W", "P2<<2W (pre-folded =*R)", "Pm<<W"]
    worst = [0] * 5
    for _ in range(2000):
        a1 = rng.randrange(1 << W); a2 = rng.randrange(1 << W)
        b1 = rng.randrange(1 << W); b2 = rng.randrange(1 << W)
        P0 = a1 * b1
        P2 = a2 * b2
        Pm = (a1 - a2) * (b1 - b2)
        c = rng.randrange(p)            # already-reduced accumulator
        terms = [P0, P0 << W, P2 << W, (P2 % p) * R % p, (-Pm) % p << W]
        # model: each step c = (c + term); overshoot = bits of (c+term) above 256
        for i, t in enumerate(terms):
            s = c + t
            ov = max(0, s.bit_length() - 256)
            worst[i] = max(worst[i], ov)
            c = s % p                   # fold back to reduced for next step
    for lbl, w in zip(labels, worst):
        print(f"  {lbl:<26} overshoot up to {w:>4} bits")


def main():
    import random
    rng = random.Random()  # unseeded per project rule
    n = 4000
    print(f"p = secp256k1, W={W}, {n} random trials\n")
    for name, fn in SCHEMES:
        ok = 0
        for _ in range(n):
            A = rng.randrange(0, 1 << 256)
            B = rng.randrange(0, 1 << 256)
            c0 = rng.randrange(0, p)
            if fn(A, B, c0) == target(A, B, c0):
                ok += 1
        print(f"  {name:<34} {ok}/{n} correct")

    # Characterize the literal scheme's residual structure.
    print("\nResidual structure of the literal scheme (target - got mod p):")
    a1 = rng.randrange(0, 1 << W); a2 = rng.randrange(0, 1 << W)
    b1 = rng.randrange(0, 1 << W); b2 = rng.randrange(0, 1 << W)
    A = a2 * (1 << W) + a1; B = b2 * (1 << W) + b1
    res = scheme_literal_with_diag(A, B, 0)
    # Candidate closed form: missing middle = (a1 b2 + a2 b1)*2^W plus what literal added.
    cand = ((a1 * b2 + a2 * b1) * (1 << W) + (a2 - b1) * (b2 - a1) * (1 << W)) % p
    print(f"  residual == [(a1 b2 + a2 b1) + (a2-b1)(b2-a1)]*2^W (mod p)? {res == cand}")


if __name__ == "__main__":
    main()
