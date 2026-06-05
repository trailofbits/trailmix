#!/usr/bin/env python3
"""Reference model for the fused carry-save Wallace square-subtract:

    output := (output - lambda^2) mod q     (secp256k1, q = 2^256 - f)

Goals validated here, BEFORE writing any circuit:
  1. squaring identity: lam^2 = sum_i lam_i 2^{2i} + sum_{i<j} lam_i lam_j 2^{i+j+1}
     (diagonals free since lam_i in {0,1}; off-diagonals weight-2 = one left shift)
  2. column/carry-save accumulation of the partial-product bits is exact
  3. wrapped R-fold: accumulate into ~n+ bits, folding weight 2^256 -> R = f
     (2^256 == f mod q) INLINE so we never materialize the full 2n-bit product
  4. the # of partial-product ANDs and full-adder compressors (the Toffoli floor)

Run: python3 scripts/wallace_square_proto.py
"""

F = (1 << 32) + 977            # f, with q = 2^256 - f  (secp256k1 group field is 2^256-f)
N = 256
Q = (1 << N) - F
R = F                          # 2^256 == 2^256 - q == f  (mod q)


def square_identity(lam):
    """lam^2 via the squaring identity; returns the integer (un-reduced)."""
    bits = [(lam >> i) & 1 for i in range(N)]
    acc = 0
    ands = 0
    for i in range(N):
        acc += bits[i] << (2 * i)          # diagonal: lam_i (== lam_i^2), free
    for i in range(N):
        for j in range(i + 1, N):
            if bits[i] and bits[j]:
                acc += 1 << (i + j + 1)     # off-diagonal, weight 2
            ands += 1                        # one AND per (i<j) pair, regardless of value
    return acc, ands


def column_counts():
    """Per output-column partial-bit population -> # of full-adder compressors.

    Column k (0..2N-1) collects: 1 diagonal bit if k even & k/2<N; plus one
    off-diagonal bit for each (i<j) with i+j+1==k. #compressors ~ (bits - height)."""
    pop = [0] * (2 * N)
    for i in range(N):
        pop[2 * i] += 1
    for i in range(N):
        for j in range(i + 1, N):
            pop[i + j + 1] += 1
    total_bits = sum(pop)
    # carry-save reduces each column to 1 sum bit; every (bit beyond the first)
    # in a column costs ~1 full-adder => compressors ~ total_bits - nonempty_cols
    nonempty = sum(1 for p in pop if p > 0)
    compressors = total_bits - nonempty
    return total_bits, compressors, max(pop)


def wrapped_fold_square(lam):
    """Accumulate lam^2 with weight-2^256 folded to R inline; verify == lam^2 % q.

    Models the circuit's plan: keep an accumulator < ~2^(256+slack); whenever a
    partial contributes at bit position p>=256, instead add it at p-256 with an
    extra factor R (since 2^256 == R mod q). Iterate the fold until all weight is
    < 256 (R is 33-bit, so folds converge fast)."""
    bits = [(lam >> i) & 1 for i in range(N)]
    acc = 0
    # collect (weight_exponent) contributions, then fold
    contribs = []
    for i in range(N):
        if bits[i]:
            contribs.append(2 * i)         # diagonal lam_i (== lam_i^2), gated
    for i in range(N):
        for j in range(i + 1, N):
            if bits[i] and bits[j]:
                contribs.append(i + j + 1)
    for e in contribs:
        if e < N:
            acc += 1 << e
        else:
            acc += R << (e - N)            # fold one 2^256 == R
    # acc may still exceed q (and the folded terms can re-overflow 256); reduce
    while acc >= (1 << N):
        hi = acc >> N
        acc = (acc & ((1 << N) - 1)) + R * hi
    acc %= Q
    return acc


def shrinking_horner_square(lam):
    """lam^2 via the half-work squaring identity, FUSED Horner (no carry register):
       offdiag = sum_j lam_j 2^j (lam mod 2^j)   [Horner, ADD only the low-j slice]
       lam^2   = 2*offdiag + sum_j lam_j 2^{2j}  (diagonal)
    Returns (lam^2, sum_of_slice_widths). The slice at step j is j bits wide
    (vs full n in the current square) -> total adds = sum_j j = n(n-1)/2 = HALF."""
    bits = [(lam >> i) & 1 for i in range(N)]
    off = 0
    width_sum = 0
    for j in range(N - 1, -1, -1):     # Horner, high to low
        off = off * 2                  # the doubling (Horner shift)
        if bits[j]:
            off += lam & ((1 << j) - 1)  # ADD the low j bits of lam (the slice)
            width_sum += j
    diag = sum((1 << (2 * j)) for j in range(N) if bits[j])
    return 2 * off + diag, width_sum


def end_fold_reduce(prod512):
    """User's 2-pass pseudo-Mersenne reduction of a 512-bit square:
       hi = prod>>256, lo = prod & (2^256-1);  t = lo + hi*f   (<= ~290 bits)
       then fold t's bits above 256 once more: r = (t & mask) + (t>>256)*f  (< 256-ish)
    Returns reduced value mod q. f = R = 2^32+977 (33 bits), so hi*f <= ~289 bits."""
    lo = prod512 & ((1 << N) - 1)
    hi = prod512 >> N
    t = lo + hi * F                      # <= 2^256 + 2^256*2^33 ~ 2^289  (+34 bits)
    t2 = (t & ((1 << N) - 1)) + (t >> N) * F  # second fold; (t>>256) ~ 34 bits
    # t2 can still be slightly >= q (one conditional subtract), like every pm reduce
    return t2 % Q


def main():
    import random
    rng = random.Random()      # do NOT seed (per project rule)
    bad = 0
    max_height = 0
    for _ in range(4000):
        lam = rng.getrandbits(256) % Q
        out = rng.getrandbits(256) % Q

        ident, ands = square_identity(lam)
        assert ident == lam * lam, "squaring identity wrong"

        sh, _ = shrinking_horner_square(lam)
        if sh != lam * lam:
            bad += 1

        folded = wrapped_fold_square(lam)
        if folded != (lam * lam) % Q:
            bad += 1

        want = (out - lam * lam) % Q
        got = (out - folded) % Q
        if got != want:
            bad += 1

        # user's 2-pass end-fold reduction of the full 512-bit square
        if end_fold_reduce(lam * lam) != (lam * lam) % Q:
            bad += 1

    # --- end-fold reduction width (the user's +290 budget) ---
    maxt = 0
    for _ in range(4000):
        lam = rng.getrandbits(256) % Q
        prod = lam * lam
        hi = prod >> N
        t = (prod & ((1 << N) - 1)) + hi * F
        maxt = max(maxt, t.bit_length())
    print("--- end-fold reduction (square into 512, lo += hi*f, fold again) ---")
    print(f"t = lo + hi*f max width over 4000 shots: {maxt} bits  (+{maxt - N} over 256)")
    print(f"so extra ancillae ~= 256 (high half) + {maxt - N} (fold margin) = ~{256 + maxt - N}")
    print(f"  fits lowqubit headroom 361: {256 + maxt - N <= 361}")
    print()

    total_bits, compressors, height = column_counts()
    _, ands = square_identity(0)

    # --- shrinking-Horner (fused, no carry register, fits 1169) ---
    _, wsum = shrinking_horner_square((1 << 256) - 1)  # all bits set = max slices
    print("--- shrinking-Horner square (fused, half-work) ---")
    print(f"slice-bit adds (all bits set): {wsum}  (= n(n-1)/2 = {N*(N-1)//2}, HALF of full-Horner {N*N})")
    print(f"current full-Horner square-subtract: 227078 tof (256 full-lambda mod-subs)")
    print(f"shrinking est: ~half the mod-sub width => ~113-120k tof, SAME qubits (fused, fits 1169)")
    print()

    # --- fold-strategy cost + qubit analysis ---
    # high partials (output bit p >= 256) that must fold by R.
    high = 0
    for i in range(N):
        for j in range(i + 1, N):
            if (i + j + 1) >= N:
                high += 1
    for i in range(N):
        if 2 * i >= N:
            high += 1
    Rbits = bin(R).count("1")  # nonzero bits of R = 2^32+977
    print("--- fold strategies ---")
    print(f"high partials (p>=256, need fold): {high}")
    print(f"R = 2^32+977 has {Rbits} set bits")
    print(f"(A) END-fold: accumulate full 512-bit product, fold H*R once.")
    print(f"    extra ~= R-mult of 256-bit H ~ {Rbits}*256 = {Rbits*256} compressors")
    print(f"    tof ~ {ands+compressors+Rbits*256}  but needs +512 working (busts 361, fits lowtof ~604)")
    print(f"(B) INLINE bit-fold: each high partial bit -> ~{Rbits} low bits")
    print(f"    extra ~= {high}*({Rbits}-1) = {high*(Rbits-1)} compressors")
    print(f"    tof ~ {ands+compressors+high*(Rbits-1)}  but fits 361 (acc stays 257 + carry 257 = +258)")
    print(f"squaring identity: exact (lam^2 = diag + 2*offdiag)")
    print(f"off-diagonal ANDs (Toffoli, compute): {ands}  (= n(n-1)/2 = {N*(N-1)//2})")
    print(f"partial bits total: {total_bits}   max column height: {height}")
    print(f"carry-save compressors (Toffoli): ~{compressors}")
    print(f"Toffoli floor (ANDs + compressors, MBU-free uncompute): ~{ands + compressors}")
    print(f"  vs Horner square-subtract: 227078 tof")
    print(f"wrapped-fold + subtract mismatches over 4000 random shots: {bad}")
    assert bad == 0, "wrapped fold or subtract mismatch"
    print("OK")


if __name__ == "__main__":
    main()
