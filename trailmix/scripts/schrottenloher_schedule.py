#!/usr/bin/env python3
"""Schrottenloher EC-add register-shrinking schedule for secp256k1.

Computes the per-iter active width of u, v and the garbage tape growth
according to the paper's formulas (gcd.py:223-229), and reports the
peak qubit budget under different register-allocation strategies.
"""
from math import ceil, sqrt

N = 256
ITERATIONS_VAR = 2.4
U_PAD_VAR = 2.3

iters = ceil((1.413 * N + ITERATIONS_VAR * sqrt(N)) / 3) * 3
u_padding = ceil(U_PAD_VAR * sqrt(N))
expected_garbage = ceil(iters / 3) * 5

def current_n_at(i):
    raw = N - i * 0.5 * 1.415 + u_padding
    raw_clamped = max(0, ceil(raw))
    return min(raw_clamped, N)

def garbage_filled_at(i):
    # Garbage grows 5 bits every 3 iters.
    return ((i + 2) // 3) * 5  # ceil((i+1)/3) * 5

print(f"# Schrottenloher secp256k1 schedule (N={N}, iters={iters}, u_padding={u_padding}, garbage={expected_garbage})")
print()
print(f"{'iter':>5} {'curr_n':>7} {'gb_filled':>10} {'gb_unfilled':>12} {'shareable':>10}")
for i in [0, 10, 30, 50, 80, 100, 150, 200, 250, 300, 350, 380, 400, iters-1]:
    cn = current_n_at(i)
    gf = garbage_filled_at(i)
    gu = expected_garbage - gf
    # Bits available for sharing: per u + per v, freed bits above current_n.
    free_in_u = N + u_padding - cn
    shareable = 2 * free_in_u
    print(f"{i:>5} {cn:>7} {gf:>10} {gu:>12} {shareable:>10}")

print()
print(f"Active u+v: drops from {2*N+2*u_padding} (iter 0) to {2*1} (last).")
print(f"Garbage filled: 0 → {expected_garbage} over the run.")
print()
print(f"--- Allocation strategies ---")
n_extras = 0
strat1 = 2*(N+u_padding) + expected_garbage + 257*2 + n_extras  # our current
print(f"1. naive (caller x_full {N+u_padding} + y_full {N+1} + tmp_full {N+1} + garbage {expected_garbage} + u_full {N+u_padding}): {strat1}q")

# Strategy 2: drop the unused u_padding from caller side (clamp to N).
strat2 = N + (N+1) + (N+1) + expected_garbage + N + n_extras
print(f"2. drop unused pad from caller x_full and internal u_full: {strat2}q (save {strat1-strat2})")

# Strategy 3: share garbage with u_full/v_full bit positions (paper Sec 3.1).
strat3 = 2*(N+u_padding) + (N+1) + (N+1) + n_extras
print(f"3. share garbage with u/v storage: {strat3}q (save {strat1-strat3})")

# Strategy 4: combine 2 and 3 — drop the 'unused' pad too.
# But we DO need pad for register-sharing! The pad gives room for garbage tape.
# Actually expected_garbage = 670, and we have 2*u_padding = 74 free bits per iter 0.
# That's MUCH less than 670. So we'd need pad ≈ 335 per register to hold garbage.
#
# Reconciliation: the paper uses the bit-reversed interleave where as u and v
# SHRINK over iters, the FREED bits become garbage storage. So the TOTAL
# storage = 2*(N+u_padding) and the "extra" 2*u_padding gives the buffer for
# garbage to grow into.
#
# Required pad: garbage fills at iter i with current_n=cn(i). Need pad such
# that 2*(N+u_padding) >= 2*cn(i) + garbage_filled(i) for all i.
# Equivalently: u_padding >= (garbage_filled(i) - 2*(N - cn(i))) / 2.
#
# Max over i of [garbage_filled(i) - 2*(N - cn(i))] / 2 gives required pad.
max_required_pad = 0
for i in range(iters+1):
    cn = current_n_at(i)
    gf = garbage_filled_at(i)
    needed = (gf - 2*(N - cn)) / 2.0
    if needed > max_required_pad:
        max_required_pad = needed
print(f"Required u_padding for register-sharing: {ceil(max_required_pad)} (Qarton's U_PAD_VAR=2.3*sqrt(N) = {u_padding} — close).")

# Strategy 5: optimal — share garbage, drop unused pad after iter ends.
strat5 = 2*(N+u_padding) + (N+1) + (N+1)
print(f"5. paper Sec 3.1 (u_full+v_full share garbage storage): {strat5}q")
print()
print(f"--- Schrottenloher targets ---")
print(f"  Space-opt: 1192 qubits, 2^21.19 ≈ 2.34M Toffoli")
print(f"  Gate-opt:  1446 qubits, 2^20.83 ≈ 1.83M Toffoli")
print(f"  Current ours: 1773 qubits, 8.04M Toffoli")
print()
print(f"Path to 1192q: implement strategy 5 (paper register sharing).")
print(f"  2*(256+37) + 2*257 = 586 + 514 = 1100. Add ~90 for small ancs and internals = ~1190.")
