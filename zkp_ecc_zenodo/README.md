# ZKP_ECC: Zero-Knowledge Proofs of Quantum Elliptic Curve Cryptography Circuits

## Overview

This repository contains Zero-Knowledge Proofs (ZKPs) generated as part of writing the paper
["Securing Elliptic Curve Cryptocurrencies against Quantum Vulnerabilities: Resource Estimates and Mitigations"](https://quantumai.google/static/site-assets/downloads/cryptocurrency-whitepaper.pdf).
The ZKPs prove that we know quantum circuits for attacking elliptic curve cryptography with 10x lower spacetime cost compared to prior art.
The ZKPs do this without revealing the contents of the circuits.
The repository also contains supporting infrastructure for generating and verifying proofs of this nature.

If you're unfamiliar with zero knowledge proofs or quantum circuits, we recommend reading [docs/getting_started.md](docs/getting_started.md).
It contains a guided walkthrough of proving and verifying the function of a simple quantum circuit (a 64 qubit adder).
It also lists crucial dependencies used by the code in this repository.

We use the [SP1 zkVM](https://github.com/succinctlabs/sp1) to generate a [Groth16](https://eprint.iacr.org/2016/260.pdf) Succinct Non-Interactive Argument of Knowledge (SNARK).
The SNARK attests to the correctness and efficiency of [elliptic curve point addition](https://en.wikipedia.org/wiki/Elliptic_curve_point_multiplication#Point_addition) circuits.
Specifically, the circuits are verified as approximately correct elliptic curve point additions using fuzz testing with cases chosen by the [Fiat-Shamir heuristic](https://en.wikipedia.org/wiki/Fiat%E2%80%93Shamir_heuristic).
(Note that Shor's algorithm uses many elliptic curve point additions, not just one.)
The circuits are specified in a custom format (see [docs/kickmix_file_format.md](docs/kickmix_file_format.md) and [docs/kickmix_instruction_set.md](docs/kickmix_instruction_set.md)), which has no support for subroutines or loops or other concepts that could make analysis non-trivial.


## Proofs

### 1. Low-Qubit Variant

The file [proofs/low_qubits/proof_9024.bin](proofs/low_qubits/proof_9024.bin) is a ZKP that we possess a kickmix circuit with the following properties:

- When run, it executes at most **2,700,000** non-Clifford gates (CCX+CCZ)
- It uses at most **1175** logical qubits
- It contains at most **17,000,000** kickmix circuit instructions
- It performs elliptic curve point addition (it passes 9024 test cases chosen randomly by the [Fiat-Shamir heuristic](https://en.wikipedia.org/wiki/Fiat%E2%80%93Shamir_heuristic)).
- It has a SHA256 hash `5373e67ca5e900819747f8c37a4a7fa9a3ea28986835436eaa9825b12a082ff2`.

The verification key for the RISC-V Elf binary of the fuzz testing program is:

> 001b118b4d719b0c43518ff8c046555b79e49a4259684242bf0214060e3d01e4

The compiled RISC-V ELF binary is provided at [proofs/zkp_ecc-program](proofs/zkp_ecc-program) and the verification key is provided at [proofs/vkey.bin](proofs/vkey.bin).
The rust code used to produce the binary is in the [lib/](lib/) and [program/](program/) directories.


### 2. Low-Gate Variant

The file [proofs/low_toffoli/proof_9024.bin](proofs/low_toffoli/proof_9024.bin) is a ZKP that we possess a kickmix circuit with the following properties:

- When run, it executes at most **2,100,000** non-Clifford gates (CCX+CCZ)
- It uses at most **1425** logical qubits
- It contains at most **17,000,000** kickmix circuit instructions
- It performs elliptic curve point addition (it passes 9024 test cases chosen randomly by the [Fiat-Shamir heuristic](https://en.wikipedia.org/wiki/Fiat%E2%80%93Shamir_heuristic)).
- It has a SHA256 hash `04f17175a034cade07b0350481aab02ec4ad08254aa5d4dfd53ba217afca4f0c`.

The verification key for the RISC-V Elf binary of the fuzz testing program is:

> 001b118b4d719b0c43518ff8c046555b79e49a4259684242bf0214060e3d01e4

This is the same binary as the low-qubit variant (they are simply given different inputs), and so the other details are also identical.
The compiled RISC-V ELF binary is provided at [proofs/zkp_ecc-program](proofs/zkp_ecc-program) and the verification key is provided at [proofs/vkey.bin](proofs/vkey.bin).
The rust code used to produce the binary is in the [lib/](lib/) and [program/](program/) directories.


## How We Generate the Proof

We use sp1's multi-gpu proving mode to generate proofs.
See [docs/sp1_cluster_deployment_guide.md](docs/sp1_cluster_deployment_guide.md) for more details on how to setup the sp1 cluster.
The `./run_proofs.sh` script is invoked as follows to start proof generation:

```bash
LOW_GATE_CIRCUIT_PATH=...  # you'll have to provide your own for this to work

./run_proofs.sh \
  --num-tests "9024" \
  --kmx "${LOW_GATE_CIRCUIT_PATH}" \
  --qubit-counts 1425 \
  --toffoli-counts 2100000 \
  --total-ops 17000000 \
  --proving-mode "multi-gpu"
```

and for the low-qubit variant:

```bash
LOW_QUBIT_CIRCUIT_PATH=...  # you'll have to provide your own for this to work

./run_proofs.sh \
  --num-tests "9024" \
  --kmx "${LOW_QUBIT_CIRCUIT_PATH}" \
  --qubit-counts 1175 \
  --toffoli-counts 2700000 \
  --total-ops 17000000 \
  --proving-mode "multi-gpu"
```

1. **Compilation**: The script invokes `prover/prove.rs`. Using `sp1-build`, this compiles `program/` into an ELF native to the RISC-V zkVM architecture.
2. **Private Input Injection**: The `.kmx` operations are read from disk by the host and passed as an array of private inputs into the zkVM `stdin`.
3. **Execution**: The SP1 prover natively executes the ELF, which simulates the quantum circuit. It tracks memory access, assertions, bounded limits, and computes the test evaluations.
4. **STARK Proof Generation**: The host generates a Groth16 proof and saves it to disk inside the `proofs/` directory (e.g. `proofs/low_toffoli/proof_64.bin`). The host also saves the verification key (eg: `proofs/vkey.bin`) that represents a cryptographic commitment of the exact RISC-V program that was executed in order to generate the proof.


## How to Verify a Proof

### The automatic part

After a proof is successfully created, it can be verified by a third-party observer using the standalone `verifier` binary. 

The verifier can use an explicitly provided verification key (eg: `proofs/vkey.bin`) via the `--vkey` flag, or deterministically derive the verification key from the proving ELF (eg: `proofs/zkp_ecc-program`) passed via the `--elf` flag, or the verifier can omit both flags and deterministically rebuild the ELF via Docker and derive the verification key from that.

```bash
# Verify using an explicitly exported vkey file
cargo run --release -p verifier -- \
    --proof proofs/low_toffoli/proof_9024.bin \
    --vkey proofs/vkey.bin
```

Alternatively, you can generate the verification key deterministically on-the-fly if you provide the ELF binary that was used to create the proof:

```bash
# Verify by hashing the given ELF binary
cargo run --release -p verifier -- \
    --proof proofs/low_toffoli/proof_9024.bin \
    --elf proofs/zkp_ecc-program
```

Finally, you can simply point the verifier at a proof and it will automatically construct an isolated Docker environment to deterministically rebuild the proving ELF and derive the verification key:

```bash
# Verify by using Docker to rebuild the original program
cargo run --release -p verifier -- \
    --proof proofs/low_toffoli/proof_9024.bin
```

Upon a successful invocation, the verifier prints useful information like:
1. The verification key corresponding to the ELF binary. 
2. For Groth16 or Plonk proofs, the verifier also prints bytes of the proof itself.
3. The SHA256 hash of the secret quantum circuit that was executed.
4. The demanded resource counts that the secret quantum circuit satisfies.
5. The number of test cases executed for verifying the correctness of the circuit.
6. Whether the proof is valid

### The manual part

The automatic verification checks that a given program (in this case, a quantum circuit simulator) was faithfully executed
on a set of private (known only to the prover, in this case the secret quantum circuit) and public inputs (known to both
prover and verifier, in this case the SHA256 hash of the secret quantum circuit, 9024 pseudo-random test cases and claimed resource costs).
It does not verify that the program is actually testing the correctness of quantum circuits.
It proves *that* the program output certain values, but not *why* it output those values. 
To verify the *why*, you must carefully read the source code in this repository and confirm that the program is performing
fuzz testing with inputs chosen by the [Fiat-Shamir heuristic](https://en.wikipedia.org/wiki/Fiat%E2%80%93Shamir_heuristic).
You must further verify that the implemented kickmix simulator is correct and that this is actually a valid way to certify the quantum circuits.
For example, fuzz testing can only prove *approximate* correctness and so it's crucial that Shor's algorithm tolerates approximately correct circuits.
A circuit that maps 1% of inputs to the wrong output will cause Shor's algorithm to fail around 1% of the time.
