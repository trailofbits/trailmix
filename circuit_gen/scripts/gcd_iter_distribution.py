#!/usr/bin/env python3
"""Measure the GCD convergence-STEP distribution for the circuit's GCD.

Answers: is iters=402 higher/lower than needed? For each random secp256k1 x,
run the gate-faithful binary GCD (shrinking current_n, exact-enough top-40
comparator) and record the step at which (u,v) first reaches (1,0) -- that's
the number of iterations the circuit actually needs. The tail P(step > iters)
is the non-convergence failure at a given iteration budget.

Reports mean/std/max, the empirical tail at the current 402, an analytic
normal-tail extrapolation, and the iters needed to hit a per-pass failure
target (e.g. 99% over 9000 points => per-point 1.1e-6 => per-pass ~2.8e-7
across 4 GCD passes).
"""
import random, sys
from math import ceil, sqrt, erfc

Q = (1 << 256) - 0x1000003D1   # secp256k1 field prime p
N = 256

def u_padding(n, pv=2.3): return ceil(pv * sqrt(n))
def expected_iterations(n, iv=2.4): return ceil((1.413 * n + iv * sqrt(n)) / 3.0) * 3
def current_n_at(i, n, pad, step=1):
    raw = n - i * 0.5 * 1.415 + pad
    return min(((max(ceil(raw), 0) + step - 1) // step) * step, n)

def conv_step(x, n=N, max_iters=520, truncate=40, pad_var=2.3):
    """Steps until the cn-masked (u,v) == (1,0); None if not within max_iters.
       Also flags an overflow (set bit at index >= cn -> circuit drops it)."""
    pad = u_padding(n, pad_var)
    trunc = truncate + pad
    u, v = Q, x
    overflowed = False
    for i in range(max_iters):
        cn = max(current_n_at(i, n, pad), 1)
        if (u >> cn) != 0 or (v >> cn) != 0:
            overflowed = True
        umask = u & ((1 << cn) - 1)
        vmask = v & ((1 << cn) - 1)
        if umask == 1 and vmask == 0:
            return i, overflowed
        b0 = vmask & 1
        cmp_eff = min(trunc, cn); shift = cn - cmp_eff
        b1 = 1 if (vmask >> shift) < (umask >> shift) else 0
        if b0 & b1:
            umask, vmask = vmask, umask
        if b0:
            vmask = (vmask - umask) % (1 << cn)
        vmask >>= 1
        u, v = umask, vmask
    return None, overflowed

def normal_tail(thresh, mean, std):
    # P(X > thresh) for X ~ Normal(mean, std), via complementary error fn.
    z = (thresh - mean) / std
    return 0.5 * erfc(z / sqrt(2.0))

if __name__ == "__main__":
    NT = int(sys.argv[1]) if len(sys.argv) > 1 else 100000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else None
    rng = random.Random(seed)
    iters = expected_iterations(N, 2.4)   # 402
    steps = []
    nonconv = 0
    overflows = 0
    over402 = 0
    for _ in range(NT):
        x = rng.randrange(1, Q)
        s, ovf = conv_step(x)
        if ovf:
            overflows += 1
        if s is None:
            nonconv += 1
        else:
            steps.append(s)
            if s > iters:
                over402 += 1
    steps.sort()
    m = sum(steps) / len(steps)
    var = sum((s - m) ** 2 for s in steps) / len(steps)
    sd = sqrt(var)
    mx = steps[-1]
    p999 = steps[int(0.999 * len(steps))]
    print(f"n_trials={NT}  current iters budget={iters}  (1.413n={1.413*N:.1f}, +2.4*sqrt(n)={2.4*sqrt(N):.1f})")
    print(f"convergence step: mean={m:.2f}  std={sd:.2f}  max={mx}  p99.9={p999}")
    print(f"  margin: iters - mean = {iters - m:.1f} = {(iters-m)/sd:.2f} std ; iters - max = {iters - mx}")
    print(f"empirical: steps>402 = {over402}/{NT}   nonconv(>520) = {nonconv}   overflows = {overflows}")
    print(f"analytic normal tail P(step>402) = {normal_tail(iters, m, sd):.3e}")
    # iters needed for a per-pass target
    for tgt, label in [(2.8e-7, "99%/9000 (per-pass)"), (1.1e-6, "per-point"), (1e-9, "ultra")]:
        # find k with normal_tail(mean + k*std) <= tgt
        k = 1.0
        while normal_tail(m + k * sd, m, sd) > tgt and k < 12:
            k += 0.05
        need = m + k * sd
        need_iters = ceil(need / 3.0) * 3
        print(f"  for per-pass {tgt:.1e} ({label}): need ~{need:.0f} steps = {k:.2f} std -> iters {need_iters}")
