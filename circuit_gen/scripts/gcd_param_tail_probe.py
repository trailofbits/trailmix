#!/usr/bin/env python3
"""Empirical failure-rate probe for the Schrottenloher GCD parameters.

Mirrors the QUANTUM circuit exactly (gcd_pack.rs forward_gcd_pack):
 - register width per iter = current_n_at(i) (the shrinking schedule)
 - approximate comparator: b1 = (v_top < u_top) on the top
   cmp_eff = min(TRUNCATE + u_padding, current_n) bits of the
   current_n-wide view of u and v (NOT the exact u>v).
 - csub/cswap are EXACT on the current_n-wide view.

A run "fails" if after `iters` iterations (u,v) != (1,0), OR if at any
iter the live bit_length of u or v exceeds current_n (a real register
overflow -- the quantum circuit would silently drop the top bit).

We sweep TRUNCATE, ITERATIONS_VAR, U_PAD_VAR and report failure rate
over many random secp256k1 (q, x) inputs. This is the evidence for
whether the constants can be tightened.
"""
import random
from math import ceil, sqrt

F_SECP = 0x1000003D1  # 2^32 + 977 ... actually secp256k1: p = 2^256 - 2^32 - 977
# q in gcd_pack = 2^256 - F_SECP256K1 where F_SECP256K1 = 0x1000003D1
N = 256
Q = (1 << 256) - 0x1000003D1


def expected_iterations(n, iters_var):
    raw = 1.413 * n + iters_var * sqrt(n)
    return ceil(raw / 3.0) * 3


def u_padding(n, pad_var):
    return ceil(pad_var * sqrt(n))


def current_n_at(i, n, pad, step=1):
    raw = n - i * 0.5 * 1.415 + pad
    raw_int = max(ceil(raw), 0)
    stepped = ((raw_int + step - 1) // step) * step
    return min(stepped, n)


def run_one(q, x, n, iters_var, pad_var, truncate, step=1):
    """Return (converged, overflowed)."""
    pad = u_padding(n, pad_var)
    iters = expected_iterations(n, iters_var)
    trunc = truncate + pad
    u, v = q, x
    overflowed = False
    for i in range(iters):
        cn = current_n_at(i, n, pad, step)
        if cn < 1:
            cn = 1
        # overflow check: the quantum reg is cn wide. If u or v has a set
        # bit at index >= cn, the circuit silently drops it.
        if u >> cn != 0 or v >> cn != 0:
            overflowed = True
        # mask to the register width (model the silent drop)
        umask = u & ((1 << cn) - 1)
        vmask = v & ((1 << cn) - 1)
        b0 = vmask & 1
        # approximate comparator: top cmp_eff bits of the cn-wide view.
        cmp_eff = min(trunc, cn)
        shift = cn - cmp_eff
        v_top = vmask >> shift
        u_top = umask >> shift
        b1 = 1 if v_top < u_top else 0  # (v < u) == (u > v) on top bits
        b0andb1 = b0 & b1
        if b0andb1:
            umask, vmask = vmask, umask
        if b0:
            # v -= u  (exact on cn-wide view; v>=u guaranteed when b0 set)
            vmask = (vmask - umask) % (1 << cn)
        vmask >>= 1
        u, v = umask, vmask
    converged = (u == 1 and v == 0)
    return converged, overflowed


def sweep(truncate, iters_var, pad_var, n_trials=20000, step=1, seed=None):
    rng = random.Random(seed)
    fails = 0
    overflows = 0
    nonconv = 0
    for _ in range(n_trials):
        x = rng.randrange(1, Q)
        conv, ovf = run_one(Q, x, N, iters_var, pad_var, truncate, step)
        if not conv:
            fails += 1
            nonconv += 1
        if ovf:
            overflows += 1
    return fails, overflows, nonconv


if __name__ == "__main__":
    import sys
    NT = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    print(f"n_trials={NT}, q=secp256k1, x random in [1,q)")
    print(f"baseline: TRUNCATE=40 ITERS_VAR=2.4 PAD_VAR=2.3 "
          f"(iters={expected_iterations(N,2.4)}, pad={u_padding(N,2.3)})")
    print()
    print("=== Sweep TRUNCATE (ITERS_VAR=2.4, PAD_VAR=2.3) ===")
    for T in [40, 30, 24, 20, 16, 12, 8]:
        f, o, nc = sweep(T, 2.4, 2.3, NT)
        print(f"  TRUNCATE={T:2d}: fails={f:5d}/{NT} ({f/NT:.2e})  overflows={o}")
    print()
    print("=== Sweep ITERS_VAR (TRUNCATE=40, PAD_VAR=2.3) ===")
    for iv in [2.4, 2.0, 1.6, 1.2, 0.9, 0.6, 0.3]:
        f, o, nc = sweep(40, iv, 2.3, NT)
        print(f"  ITERS_VAR={iv:.1f} (iters={expected_iterations(N,iv)}): "
              f"fails={f:5d}/{NT} ({f/NT:.2e})  overflows={o}")
    print()
    print("=== Sweep PAD_VAR (TRUNCATE=40, ITERS_VAR=2.4) ===")
    for pv in [2.3, 2.0, 1.7, 1.4, 1.1, 0.8]:
        f, o, nc = sweep(40, 2.4, pv, NT)
        print(f"  PAD_VAR={pv:.1f} (pad={u_padding(N,pv)}): "
              f"fails={f:5d}/{NT} ({f/NT:.2e})  overflows={o}")
