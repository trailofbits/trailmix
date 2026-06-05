#!/usr/bin/env bash
# Generate the EC-add kmx configs into a gitignored dir and validate each through
# the NATIVE zkp_ecc simulator (the same Simulator that gets compiled into the SP1
# guest -- see zenodo docs/example_tools/native_fuzz, modeled on
# program/src/main.rs) over the full 9000 Fiat-Shamir shots.
#
#   low-qubit : Schrottenloher dialog_m=5 base-3 pack, no venting -> ~1173q / ~2.48M Toffoli
#   low-tof   : Schrottenloher dialog_m=3 SAT pack + coupled venting -> ~1416q / ~2.03M Toffoli
#   jump-lowqubit : Schrottenloher jump-GCD (jump=2, packed) -> ~1169q / ~2.08M Toffoli
#   jump-lowtof   : jump-GCD (jump=2, packed) + coupled venting -> ~1412q / ~1.90M Toffoli
#   shrunken  : shrunken-PZ reversible inversion EC-add -> ~1050q / ~32.9M Toffoli
#
# Run from the repo root:  ./gen_and_validate_kmx.sh
set -euo pipefail

CG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/trailmix" && pwd)"
ZENODO_DIR="$(cd "$CG_DIR/../zkp_ecc_zenodo" && pwd)"
OUT_DIR="$CG_DIR/kmx_out"          # gitignored (see trailmix/.gitignore)
NUM_TESTS="${NUM_TESTS:-9000}"
mkdir -p "$OUT_DIR"

LOWQUBIT_KMX="$OUT_DIR/ec_lowqubit.kmx"
LOWTOF_KMX="$OUT_DIR/ec_lowtof.kmx"
SHRUNKEN_KMX="$OUT_DIR/ec_shrunken_pz.kmx"
JUMP_KMX="$OUT_DIR/ec_jump.kmx"
JUMP_LOWTOF_KMX="$OUT_DIR/ec_jump_lowtof.kmx"

echo "=== [1/6] emit low-qubit kmx (dialog_m=5, vents=0) -> $LOWQUBIT_KMX ==="
( cd "$CG_DIR" && N_CASES=1 CASES_OUT="$OUT_DIR/.lowqubit_cases.txt" \
    ./scripts/run_8g_scope.sh cargo run --release --bin emit_test_ec_add_schrottenloher \
    2>/dev/null > "$LOWQUBIT_KMX" )

echo "=== [2/6] emit low-tof kmx (dialog_m=3 SAT pack + coupled venting) -> $LOWTOF_KMX ==="
( cd "$CG_DIR" && N_CASES=1 CASES_OUT="$OUT_DIR/.lowtof_cases.txt" \
    ./scripts/run_8g_scope.sh cargo run --release --bin emit_test_ec_add_schrottenloher_lowtof \
    2>/dev/null > "$LOWTOF_KMX" )

echo "=== [3/6] emit jump-lowqubit kmx (jump-GCD packed) -> $JUMP_KMX ==="
( cd "$CG_DIR" && N_CASES=1 CASES_OUT="$OUT_DIR/.jump_cases.txt" \
    ./scripts/run_8g_scope.sh cargo run --release --bin emit_test_ec_add_schrottenloher_jump \
    2>/dev/null > "$JUMP_KMX" )

echo "=== [4/6] emit jump-lowtof kmx (jump-GCD packed + coupled venting) -> $JUMP_LOWTOF_KMX ==="
( cd "$CG_DIR" && N_CASES=1 CASES_OUT="$OUT_DIR/.jump_lowtof_cases.txt" \
    ./scripts/run_8g_scope.sh cargo run --release --bin emit_test_ec_add_schrottenloher_jump_lowtof \
    2>/dev/null > "$JUMP_LOWTOF_KMX" )

echo "=== [5/6] emit shrunken-PZ kmx -> $SHRUNKEN_KMX ==="
# The shrunken-PZ circuit is ~103M ops (~1.4 GB kmx), so the op-buffer cap must be
# raised above the 100M default for to_kmx to stream every op.
( cd "$CG_DIR" && CIRC_OPS_CAP=150000000 N_CASES=1 CASES_OUT="$OUT_DIR/.shrunken_cases.txt" \
    ./scripts/run_8g_scope.sh cargo run --release --bin emit_test_ec_add_shrunken_pz \
    2>/dev/null > "$SHRUNKEN_KMX" )

echo "=== [6/6] build + run native simulator on all five ($NUM_TESTS shots each) ==="
( cd "$ZENODO_DIR" && cargo build --release -p native_fuzz >/dev/null 2>&1 )
NF="$ZENODO_DIR/target/release/native_fuzz"

run_native () {  # <kmx> <qubit_cap> <toffoli_cap> <total_ops_cap>
  systemd-run --user --scope --same-dir -p MemoryMax=20G -p MemorySwapMax=0 \
    "$NF" "$1" "$2" "$3" "$4" "$NUM_TESTS"
}

echo "--- low-qubit (caps: 1175 qubits / 2,700,000 Toffoli / 15M ops) ---"
run_native "$LOWQUBIT_KMX" 1175 2700000 15000000
echo "--- low-tof (caps: 1420 qubits / 2,100,000 Toffoli / 15M ops) ---"
run_native "$LOWTOF_KMX" 1420 2100000 15000000
echo "--- jump-lowqubit (caps: 1175 qubits / 2,100,000 Toffoli / 13M ops) ---"
run_native "$JUMP_KMX" 1175 2100000 13000000
echo "--- jump-lowtof (caps: 1420 qubits / 1,950,000 Toffoli / 14M ops) ---"
run_native "$JUMP_LOWTOF_KMX" 1420 1950000 14000000
echo "--- shrunken-PZ (caps: 1060 qubits / 50,000,000 Toffoli / 140M ops) ---"
run_native "$SHRUNKEN_KMX" 1060 50000000 140000000

echo "=== DONE: all five configs validated at $NUM_TESTS shots ==="
