#!/bin/bash

# Usage example:
# ./run_proofs.sh \
#   --num-tests "64 128 256" \
#   --kmx "./testdata/your_circuit.kmx" \
#   --qubit-counts 1420 \
#   --toffoli-counts 3600000 \
#   --total-ops 20000000 \
#   --proving-mode "multi-gpu"

# All arguments are required.

# Initialize variables
PROVING_MODE=""
KMX=""
QUBIT_COUNTS=""
TOFFOLI_COUNTS=""
TOTAL_OPS=""
NUM_TESTS=()

# Parse command line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --proving-mode) PROVING_MODE="$2"; shift ;;
        --kmx) KMX="$2"; shift ;;
        --qubit-counts) QUBIT_COUNTS="$2"; shift ;;
        --toffoli-counts) TOFFOLI_COUNTS="$2"; shift ;;
        --total-ops) TOTAL_OPS="$2"; shift ;;
        --num-tests) 
            NUM_TESTS+=("$2")
            shift 
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --num-tests <int/string> Number of tests. Can be space-separated string or specified multiple times. (Required)"
            echo "  --kmx <path>             Path to .kmx file (Required)"
            echo "  --qubit-counts <int>     Qubit counts (Required)"
            echo "  --toffoli-counts <int>   Toffoli counts (Required)"
            echo "  --total-ops <int>        Total ops (Required)"
            echo "  --proving-mode <mode>    'multi-gpu' or 'single-gpu' (Required)"
            exit 0
            ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# Check if required arguments are provided
if [ -z "$PROVING_MODE" ] || [ -z "$KMX" ] || [ -z "$QUBIT_COUNTS" ] || [ -z "$TOFFOLI_COUNTS" ] || [ -z "$TOTAL_OPS" ] || [ ${#NUM_TESTS[@]} -eq 0 ]; then
    echo "Error: Missing required arguments."
    echo "Run '$0 --help' for usage info."
    exit 1
fi

echo "Starting STARK proof generation loop in ${PROVING_MODE} mode..."

for tests_arg in "${NUM_TESTS[@]}"; do
    for TEST_COUNT in $tests_arg; do
        echo "=========================================================================="
        echo "Running STARK Proof for $TEST_COUNT tests..."
        echo "=========================================================================="

        if [ "$PROVING_MODE" = "multi-gpu" ]; then
            SP1_DOCKER=true \
            SP1_PROVE_TIMEOUT_HOURS=240 \
            USE_CLUSTER=true \
            CLI_CLUSTER_RPC=http://127.0.0.1:50051 \
            CLI_REDIS_NODES=redis://:redispassword@127.0.0.1:6379/0 \
            RUST_LOG=info \
            cargo run --release --bin prove --manifest-path prover/Cargo.toml -- \
                --prove \
                --num-tests "$TEST_COUNT" \
                --qubit-counts "$QUBIT_COUNTS" \
                --toffoli-counts "$TOFFOLI_COUNTS" \
                --total-ops "$TOTAL_OPS" \
                --kmx "$KMX"
        elif [ "$PROVING_MODE" = "single-gpu" ]; then
            SP1_DOCKER=true \
            SP1_PROVE_TIMEOUT_HOURS=240 \
            SP1_PROVER=cuda \
            RUST_LOG=info \
            cargo run --release --bin prove --manifest-path prover/Cargo.toml -- \
                --prove \
                --num-tests "$TEST_COUNT" \
                --qubit-counts "$QUBIT_COUNTS" \
                --toffoli-counts "$TOFFOLI_COUNTS" \
                --kmx "$KMX"
        else
            echo "Error: Unknown PROVING_MODE '${PROVING_MODE}'. Use 'multi-gpu' or 'single-gpu'."
            exit 1
        fi

        echo "Verification Stage for $TEST_COUNT tests..."
        KMX_BASENAME=$(basename -- "$KMX")
        FNAME="${KMX_BASENAME%.*}"
        
        PROOF_PATH="proofs/${FNAME}/proof_${TEST_COUNT}.bin"
        VKEY_PATH="proofs/vkey.bin"
        ELF_PATH="proofs/zkp_ecc-program"
        
        RUST_LOG=info cargo run --release -p verifier -- \
            --proof "$PROOF_PATH" \
            --vkey "$VKEY_PATH"

        RUST_LOG=info cargo run --release -p verifier -- \
            --proof "$PROOF_PATH" \
            --elf "$ELF_PATH"

        RUST_LOG=info cargo run --release -p verifier -- \
            --proof "$PROOF_PATH" \

    done
done

echo "Completed all specified tests."
