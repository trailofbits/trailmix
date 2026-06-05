### Trustless Verification and Docker Builds
The verification key (`vkey.bin` file) serves as the public cryptographic anchor for our Zero-Knowledge Proofs. It represents the compiled RISC-V ELF binary of our program logic.

Enforcing `SP1_DOCKER=true` during proof generation ensures that the SP1 SDK compiles the Rust program inside a standardized, isolated Docker environment. This guarantees **deterministic, machine-agnostic builds**.

Because the compilation environment is reproducible, anyone can clone this repository, build it inside the exact same Docker container, and derive the exact same verification key independently.

The `Cargo.lock` file pins the exact version of the `sp1-build` library used in this release. When `SP1_DOCKER=true` is invoked, the build script fetches the Docker image with the tag matching that pinned crate version (e.g., `ghcr.io/succinctlabs/sp1:v6.0.0-beta.1`). This guarantees that regardless of future framework updates, anyone checking out this repository will automatically download the exact same immutable Docker artifact, ensuring long-term reproducibility of the verification key file.

You can use the following command to verify the generated proof against the locally derived vkey:

```bash
cargo run --release -p zkp_ecc-verifier -- \
    --proof proofs/iadd_elliptic/proof_chacha20_64.bin \
    --vkey proofs/iadd_elliptic/vkey_chacha20_64.bin
```