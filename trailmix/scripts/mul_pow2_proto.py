#!/usr/bin/env python3
"""Reference for fast multiply-by-2^k mod q (secp256k1), via the user's
`tmp = carries*f; out += tmp; clear tmp` reduction.

  q = 2^256 - f,  f = 2^32 + 977.
  2^k * x  =  low + carries*2^256  ==  low + carries*f   (mod q)
where low = (x<<k) mod 2^256, carries = (x<<k) >> 256 = x >> (256-k)  (k bits).

Reduction (windowed, like mod_double_pm -- carry beyond lsbs dropped, the
pseudo-Mersenne approximation):
  tmp = carries * f            (a k x 33-bit multiply, into scratch, ~33+k bits)
  a[0..lsbs] += tmp            (carry beyond lsbs dropped)
  clear carries via cx(a[i], carries[i])  for i<k   -- valid iff f mod 2^k == 1
  clear tmp

Validated here: (1) value == (2^k*x) mod q at the same approximation rate as
mod_double, (2) f mod 2^k == 1 for k<=4 (so the cx-clean works), (3) the
carries-clean identity a[0..k] == carries holds after the windowed add.

Run: python3 scripts/mul_pow2_proto.py
"""

F = (1 << 32) + 977
N = 256
Q = (1 << N) - F


def mul_pow2_windowed(x, k, lsbs):
    """2^k*x mod q via low + carries*f, windowed add (carry beyond lsbs dropped)."""
    shifted = x << k
    low = shifted & ((1 << N) - 1)
    carries = shifted >> N                 # = x >> (256-k), a k-bit value
    tmp = carries * F                      # k x 33-bit product, < 2^(33+k)
    a_lo = low & ((1 << lsbs) - 1)
    a_hi = low >> lsbs
    s = a_lo + tmp
    s_lo = s & ((1 << lsbs) - 1)           # DROP carry beyond lsbs (the approx)
    result = (a_hi << lsbs) | s_lo
    # carries-clean check: after shift, low's bottom k bits are 0, so
    # a[0..k] == tmp[0..k] == (carries*f) mod 2^k == carries*(f mod 2^k) mod 2^k.
    clean_ok = (result & ((1 << k) - 1)) == ((carries * (F % (1 << k))) % (1 << k))
    return result, carries, clean_ok


def main():
    import random
    rng = random.Random()

    # (1) f mod 2^k == 1 for which k? (decides cx-clean validity)
    print("f mod 2^k (==1 means cx-clean works):")
    for k in range(1, 9):
        print(f"  k={k}: f mod 2^{k} = {F % (1 << k)}  -> cx-clean {'OK' if F % (1<<k) == 1 else 'NEEDS inverse-mult'}")
    print()

    # (2) value correctness + approximation error rate, per k and padding.
    for k in [1, 2, 3, 4]:
        for padding in [30]:
            lsbs = 33 + k + padding
            bad = 0
            clean_fail = 0
            trials = 200000
            for _ in range(trials):
                x = rng.randrange(Q)
                got, carries, clean_ok = mul_pow2_windowed(x, k, lsbs)
                want = (pow(2, k, Q) * x) % Q
                if got % Q != want:
                    bad += 1
                if not clean_ok:
                    clean_fail += 1
            print(f"k={k} lsbs={lsbs}: approx errors {bad}/{trials} (~2^{-padding} expected), "
                  f"carries-clean fails {clean_fail}/{trials}")
    print()

    # (3) Toffoli estimate: tmp=carries*f build + out+=tmp + clear, vs k folds.
    fbits = [j for j in range(40) if (F >> j) & 1]
    print(f"f set bits: {fbits} ({len(fbits)} of them)")
    for k in [1, 2, 4, 8]:
        # build tmp: first f-bit is a copy (cx), rest are k-bit adds into tmp (~k ccx each).
        build = (len(fbits) - 1) * k
        outadd = 33 + k          # add tmp (~33+k bits) into out
        clear = (len(fbits) - 1) * k
        total = build + outadd + clear
        folds = k * 62           # k separate doublings, ~62 ccx fold each
        print(f"  k={k}: x2^k via tmp ~ {total} ccx   vs  {k} folds ~ {folds} ccx   "
              f"(save ~{folds - total})")


if __name__ == "__main__":
    main()
