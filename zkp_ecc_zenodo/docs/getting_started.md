# Getting Started

This document explains an example of using some of the tools in this repository to create
and verify a zero-knowledge-proof that a 64-bit 2s-complement quantum adder works
correctly, as well as some background knowledge needed to understand the proof
and the verification.

## Index

- [Gathering Dependencies](#gathering-dependencies)
- [Making and Sampling a Circuit](#making-and-sampling-a-circuit)
- [Fuzz Testing a Circuit](#fuzz-testing-a-circuit)
- [Using Fuzz Testing as a Proof Strategy](#using-fuzz-testing-as-a-proof-strategy)
- [Generating a Proof](#generating-a-proof)
- [Verifying a Proof](#verifying-a-proof)


## Gathering Dependencies

If you are on a linux system, you can follow with this document executing the given commands in the terminal.
Commands are written assuming your working directory is at the root of the repository.
(This file is `docs/getting_started.md` relative to that root.)

For the commands to work, you will need several dependencies:

- You need to [install the rust programming language](https://rust-lang.org/tools/install/) (to build the code).
    - We recommend using [`rustup`](https://rustup.rs/) (the rust installer tool) to get the correct version and toolchain:
        - `rustup target add x86_64-unknown-linux-gnu`
        - `rustup component add --toolchain 1.93.0-x86_64-unknown-linux-gnu cargo rustc`
- You need to [install the SP1 toolchain](https://docs.succinct.xyz/docs/sp1/getting-started/install#option-1-prebuilt-binaries-recommended) (to generate and verify proofs).
    - Note: SP1 needs [protobuf-compiler](https://protobuf.dev/installation/)
    - Note: SP1 needs [clang](https://clang.llvm.org/)
- You need to [install Docker CE](https://docs.docker.com/get-docker/) (for reproducible builds).

If rust and SP1 are installed, then you should be able to run this command:

```bash
rustup toolchain list | grep succinct
```

and get this output:

> ```
> succinct
> ```

If docker is installed, you should be able to run this command:

```bash
docker ps
```

and get the following output (instead of an error):

> ```
> CONTAINER ID   IMAGE     COMMAND   CREATED   STATUS    PORTS     NAMES
> ```

# Making and sampling a circuit

Let's start by making a simple circuit, and testing that it behaves correctly.

A "3-qubit incrementer" is a circuit that implements the following transitions:

- transform `|000⟩` into `|001⟩`
- transform `|001⟩` into `|010⟩`
- transform `|010⟩` into `|011⟩`
- transform `|011⟩` into `|100⟩`
- transform `|100⟩` into `|101⟩`
- transform `|101⟩` into `|110⟩`
- transform `|110⟩` into `|111⟩`
- transform `|111⟩` into `|000⟩`

Here is a text diagram of a [quantum logic circuit](https://en.wikipedia.org/wiki/Quantum_logic_gate) that implements this cycle:

```
q0: ─●─●─X─
     | |
q1: ─●─X───
     |
q2: ─X─────
```

When you increment a binary number, the increment carries until it hits a bit in the 0 state.
So, for a 3-bit incrementer, the most significant bit only flips if the other two bits are ON.
Correspondingly, the first gate in the circuit is a [controlled-controlled-NOT gate](https://en.wikipedia.org/wiki/Toffoli_gate)
that flips q2 if both q0 and q1 are ON.
Similarly, the second gate is a [controlled-NOT gate](https://en.wikipedia.org/wiki/Controlled_NOT_gate) that flips q1 if q0 is ON.
(It's important that this gate comes *after* the one flipping q2.)
Finally, an incrementer always flips the least significant bit and so the circuit ends by unconditionally applying a NOT gate to q0.

In the [kickmix circuit format](kickmix_file_format.md) defined and used by this repository, this circuit is written:

```
CCX q0 q1 q2
CX q0 q1
X q0
```

The above circuit is technically correct, but for tooling convenience you want a bit more.
`APPEND_TO_REGISTER` instructions are used to group the three qubits into a register, so they
can be referred to as a single quint (quantum integer) `r0` rather than as three separate qubits `q0 q1 q2`:

```
APPEND_TO_REGISTER q0 r0
APPEND_TO_REGISTER q1 r0
APPEND_TO_REGISTER q2 r0
CCX q0 q1 q2
CX q0 q1
X q0
```

The above text is the contents of the file [docs/example_data/inc3.kmx](example_data/inc3.kmx).
You can test that the circuit increments 3 into 4 using the `example_sample` tool (source code at [`docs/example_tools/example_sample/example_sample.rs`](example_tools/example_sample/example_sample.rs)):

```bash
cargo run -qp example_sample -- \
    docs/example_data/inc3.kmx 3
```

outputs:

> ```
> 4
> ```

What happened here is that the sample tool loaded the given circuit file ([docs/example_data/inc3.kmx](example_data/inc3.kmx)),
then initialized the qubits of the register `r0` to the 2s complement little endian
representation of the given command line argument (`3`),
then simulated applying the circuit's operations to the qubits,
then printed out the final value of the register `r0` (by interpreting its measured qubits as forming a 2s complement little endian integer).

There's various other circuits in the [docs/example_data/](example_data) directory.
For example, [docs/example_data/iadd64.kmx](example_data/iadd64.kmx) is an inplace 64 bit adder.
It implements r0 += r1 (mod 2⁶⁴).

Here is a zoomed-out circuit diagram of the adder (from [docs/example_data/iadd64.svg](example_data/iadd64.svg)):

![adder circuit diagram](example_data/iadd64.svg)

Running the following command confirms the adder correctly offsets 101 by 123 to get 224:

```bash
cargo run -qp example_sample -- \
    docs/example_data/iadd64.kmx 101 123
```

outputs:

> ```
> 224 123
> ```

For more information about the instructions that can appear in circuits,
see the instruction reference at [docs/kickmix_instruction_set.md](kickmix_instruction_set.md).

# Fuzz testing a circuit

The `example_sample` tool is simple to use, but it doesn't exhaustively check the correctness of the action of the circuit.
For that, there is the `example_fuzz` tool (source code at [docs/example_tools/example_fuzz](example_tools/example_fuzz)).
By feeding lines like `input -> output` into `cargo run -qp example_fuzz`, you can verify a circuit is behaving as it should.

For example, [docs/example_tools/print_iadd_cases.py](example_tools/print_iadd_cases.py) is a python script that generates lines like `1 10 -> 11 10`.
The two values to the left of `->` are the initial values for an adder circuit's registers and
the two values to the right are the expected final values of the registers.

By feeding the output of the python script into the `example_fuzz` tool, you can test the example 64 bit addition circuit on many thousands of random cases:

```bash
python docs/example_tools/print_iadd_cases.py 64 100_000 \
  | cargo run -qp example_fuzz -- docs/example_data/iadd64.kmx
```

outputs:

> ```
> pass (100000 shots)
> ```

There are a few different criteria a circuit must satisfy in order to pass fuzz testing.
The most obvious one is the circuit must end with the registers containing the expected values.
For simplicity, let's return to the three qubit increment and use [docs/example_data/inc3_test_cases.txt](example_data/inc3_test_cases.txt)
which exhaustively specifies all its expected register transitions:

```bash
cat docs/example_data/inc3_test_cases.txt
```

outputs:

> ```
> 0 -> 1
> 1 -> 2
> 2 -> 3
> 3 -> 4
> 4 -> 5
> 5 -> 6
> 6 -> 7
> 7 -> 0
> ```

[docs/example_data/inc3_wrong_order.kmx](example_data/inc3_wrong_order.kmx) is an intentionally broken 3-qubit incrementer.
It has the wrong gate order, so it will fail to map inputs to outputs in the correct way:

```bash
cat docs/example_data/inc3_wrong_order.kmx
```

outputs:

> ```
> # Incorrectly performs r0 += 1 (mod 8)
> APPEND_TO_REGISTER q0 r0
> APPEND_TO_REGISTER q1 r0
> APPEND_TO_REGISTER q2 r0
> CCX q0 q1 q2
> X q0
> CX q0 q1
> ```

Feeding [docs/example_data/inc3_test_cases.txt](example_data/inc3_test_cases.txt) and
[docs/example_data/inc3_wrong_order.kmx](example_data/inc3_wrong_order.kmx)
into the `example_fuzz` tool detects the problem:

```bash
cat docs/example_data/inc3_test_cases.txt \
    | cargo run -qp example_fuzz -- docs/example_data/inc3_wrong_order.kmx
```

outputs:

> ```
> Test failed: 0 -> 1
>     actual outputs: 3
> tests passed before failure: 0
> ```

Another way a circuit can be incorrect is if it leaves behind garbage
in ancillary qubits.
For example, [docs/example_data/inc3_wrong_garbage.kmx](example_data/inc3_wrong_garbage.kmx) performs an extraneous CX gate
that leaves garbage in the qubit `q3`:

```bash
cat docs/example_data/inc3_wrong_garbage.kmx
```

outputs:

> ```
> # Incorrectly performs r0 += 1 (mod 8)
> APPEND_TO_REGISTER q0 r0
> APPEND_TO_REGISTER q1 r0
> APPEND_TO_REGISTER q2 r0
> CX q0 q3
> CCX q0 q1 q2
> CX q0 q1
> X q0
> ```

`q3` is not part of a register, so it is considered ancillary.
It's okay to touch ancillary qubits during a circuit, but only if the qubit
is back in the 0 state by the end.

Uncleared garbage is a problem because it means the ancillary qubit could be
incorrectly entangled with the other qubits, breaking interference effects required
by the overlying quantum algorithm.
The `fuzz` tool catches this problem:

```bash
cat docs/example_data/inc3_test_cases.txt \
    | cargo run -qp example_fuzz -- docs/example_data/inc3_wrong_garbage.kmx
```

outputs:

> ```
> Test failed: 1 -> 2
>     some ancillary qubits weren't cleared to 0: q3
> tests passed before failure: 1
> ```

The last reason the circuit could be wrong is because of a phase flip.
Garbage is often cleared by [uncomputing](https://en.wikipedia.org/wiki/Uncomputation)
the garbage qubit back to the 0 state.
A specific way to do this is [measurement based uncomputation](https://algassert.com/post/1905).
In a kickmix circuit, a measurement based uncomputation is initiated using an `HMR` operation.
`HMR` performs an X-basis measurement followed by a Z-basis reset.
The simulator used in fuzz testing assigns the measurement a random result and, if that result is True, negates the amplitudes of states where
the target qubit was ON.
Essentially, the garbage qubit is turned into probabilistic phase garbage.
This phase garbage must be cleared to complete the uncomputation.

The circuit [docs/example_data/inc3_wrong_phase.kmx](example_data/inc3_wrong_phase.kmx) is a modification of [docs/example_data/inc3_wrong_garbage.kmx](example_data/inc3_wrong_garbage.kmx)
where an `HMR` operation is used to clear `q3`.
It does contain a phase correction... but the phase correction is wrong:

```bash
cat docs/example_data/inc3_wrong_phase.kmx
```

outputs:

> ```
> # Incorrectly performs r0 += 1 (mod 8)
> APPEND_TO_REGISTER q0 r0
> APPEND_TO_REGISTER q1 r0
> APPEND_TO_REGISTER q2 r0
> CX q0 q3
> CCX q0 q1 q2
> CX q0 q1
> X q0
> HMR q3 b0
> Z q0 if b0
> ```

The fuzz tool also catches this mistake:

```bash
cat docs/example_data/inc3_test_cases.txt \
    | cargo run -qp example_fuzz -- docs/example_data/inc3_wrong_phase.kmx
```

outputs:

> ```
> Test failed: 4 -> 5
>     actual outputs: 5
>     inverted phase
> tests passed before failure: 4
> ```

Beware that, because phase garbage is probabilistic, your output may differ from the one shown above.
In fact, because there's so few test cases being run, there's a decent chance of the `fuzz` tool missing the problem.
Run the test a few times and you should see a failure.

For reference, here's a version of the circuit without the mistake in the phase correction:

```
APPEND_TO_REGISTER q0 r0
APPEND_TO_REGISTER q1 r0
APPEND_TO_REGISTER q2 r0
CX q0 q3
CCX q0 q1 q2
CX q0 q1
X q0
HMR q3 b0
Z q0 if b0
NEG if b0
```

(The `NEG if b0` was missing.)


## Using Fuzz Testing as a Proof Strategy

Fuzz testing can't certify that a circuit is 100% perfectly correct.
However, crucially, *Shor's algorithm only requires approximate correctness*.
Roughly speaking: if X% of inputs are mapped to the wrong output, this will cause Shor's algorithm to fail X% of the time.

As an example, consider the [point doubling corner case](https://en.wikipedia.org/wiki/Elliptic_curve_point_multiplication#Point_doubling)
of [elliptic curve point addition](https://en.wikipedia.org/wiki/Elliptic_curve_point_multiplication#Point_operations).
When adding $P+Q$, special logic is needed when $P=Q$.
But, for a 256 bit curve, the chance of a randomly chosen input hitting this case is roughly 0.000000000000000000000000000000000000000000000000000000000000000000000000001%.
That's a negligible failure rate, and so it's common for elliptic curve quantum circuits to save operations by omitting the point doubling logic (e.g. [Proos+Zalka 2003](https://arxiv.org/abs/quant-ph/0301141)).
(Beware that there's *some* care required to ensure the rare cases are actually rate, such as initializing the accumulator to a random point.)

The approximations-are-okay property of Shor's algorithm (and in fact most quantum algorithms) is what allows us to certify circuits as good-enough using mere fuzz testing.

Now consider a situation with a prover Alice and a verifier Bob, and Alice is trying to convince Bob that she knows a good-enough circuit.
Using existing [zero-knowledge proof](https://en.wikipedia.org/wiki/Zero-knowledge_proof) (ZKP) tools such as
[SP1](https://docs.succinct.xyz/docs/sp1/introduction), Alice can convince Bob she has
a secret circuit $C$ that maps given inputs $P, Q$ to the correct output $P+Q$ (without revealing $C$).
However, clearly Bob doesn't want Alice to be choosing $P$ and $Q$; she could just be avoiding inputs that don't work!
In an interactive setting, this would be solved trivially by *Bob* picking $P$ and $Q$.
In a non-interactive setting, we can instead lean on [the Fiat-Shamir heuristic](https://en.wikipedia.org/wiki/Fiat%E2%80%93Shamir_heuristic).
The idea is to derive $P$ and $Q$ as one-way functions of $C$, for example by seeding a
[cryptographically secure pseudo random number generator](https://en.wikipedia.org/wiki/Cryptographically_secure_pseudorandom_number_generator)
using a [cryptographic hash](https://en.wikipedia.org/wiki/Cryptographic_hash_function) of $C$.
Although this makes the tested points a deterministic function of $C$,
it should still be intractable for an attacker to find a flawed $C$
whose bad points are avoided (if bad points are common).
With more and more succeeding fuzz tests, Bob can become and more and more confident that higher and higher
proportions of inputs are being handled correctly.

## Generating a Proof

**Step 1: create a circuit that performs a desired operation**

For this example, we will use [docs/example_data/iadd64.kmx](example_data/iadd64.kmx).
It is a 64 bit variant of the [Cuccaro adder](https://arxiv.org/abs/quant-ph/0410184).
It is supposed to perform 64-bit 2s-complement addition.
To be precise: this circuit should transform the pair (x, y) into the pair ((x + y) mod 2⁶⁴, y).

**Step 2: write a fuzz testing program**

For this example, the fuzz testing program is at
[docs/example_tools/example_zkp_fuzzer/example_zkp_fuzzer.rs](example_tools/example_zkp_fuzzer/example_zkp_fuzzer.rs).
In an ideal world, this program would be as short and simple as possible.
The more complex it is, the harder it is for the verifier to understand and check its behavior.
In this case the fuzzer and the utilities it uses from this repository constitute
around 1000 lines of Rust code.

A truly paranoid verifier would not just verify the assets in this
repository, but also the dependencies it relies upon. For example,
the example fuzzer has dependencies such as `sp1-zkvm = "6.0.2"` for reading private inputs and committing public outputs.
Those in turn have their own dependencies, which have their own dependencies, and so forth.
As of this writing, according to `cargo generate-lockfile`, the example fuzzer program depends on *205* (!!!) packages.
Clearly many of these packages aren't crucial (e.g. the dependency `svgbobdoc == "0.3.0"` is a tool for making svg diagrams),
and we haven't done an audit, but unfortunately this could easily constitute tens of millions of lines of potentially-relevant
code for the truly paranoid verifier to review.
Even including *only* the crucial `sp1-zkvm` dependency ultimately pulls in a total of 143 transitive dependencies;
we hope future versions of SP1 will make it feasible to bring the number of potentially-relevant lines down.
(For scale, the compiled fuzz testing binary is ultimately around 200 kilobytes of machine code.)

Anyways, here are the important things that the fuzz testing program does:

- Read private inputs, such as the circuit, using `sp1_zkvm::io::read`.
- Write public outputs, such as the circuit hash, using `sp1_zkvm::io::commit`.
- Check claimed bounds on certain properties, such as the number of non-Clifford instructions executed.
- Oh and, of course, do the actual fuzz testing.

**Step 3: compile the fuzz testing program into reproducible RISC-V machine code**

SP1 provides a `prove build` tool for producing machine code
targeting the correct architecture:

```bash
# Note: expected runtime: ~5 minutes (first time compilation)
cargo prove build \
    --packages example_zkp_fuzzer \
    --docker
```

This command will end by printing a line containing the filepath of the output.
For example, it might be `target/elf-compilation/docker/riscv64im-succinct-zkvm-elf/release/example_zkp_fuzzer`.
The eventual ZKP will be about the execution of *that file's machine code*, so this path is needed for later steps.
For reference, we've included a copy of the expected machine code file at `docs/example_data/iadd64_fuzzer.elf`.
That example path is the one this document will use in later commands.

Note that the build command can still succeed if you omit `--docker`, but the exact machine code produced
may not be reproducible by others. This would break their ability to verify that the machine code
actually comes from the specified rust code.

**Step 4: write a proof generating program**

For this example, the proof generating program is at
[docs/example_tools/example_zkp_prove/example_zkp_prove.rs](example_tools/example_zkp_prove/example_zkp_prove.rs).

This program is sort of a manager around the fuzzing program.
It will be given the RISC-V machine code of the fuzz testing program
as an input.
It uses SP1 to feed values into that program and to
produce a proof of how the program executed and what it output.

**Step 5: run the proof generating program**

The input into the proof generating program are the compiled machine code of the fuzz tester,
the secret circuit to fuzz test, and various demanded properties of the circuit.
The output is a proof file and optionally a vkey file (that can be used to avoid including the machine code as part of the proof).

A 64 qubit adder can be performed with no workspace, so we will
demand that the number of qubits is at most 128 (64 for the target, 64 for the offset).
It can be performed using less than 128 Toffoli gates, so we will demand
the toffoli count is at most 128.
As a sanity check we will demand that the circuit has at most
1000 instructions (this includes *everything*, including metadata instructions defining the registers).
We want this example to be fast to run, so we will only demand that the
fuzz testing performing 128 samples.
The proof generating program takes these options via flags like `--demanded-max-qubit-count`:


```bash
MACHINE_CODE_PATH=docs/example_data/iadd64_fuzzer.elf

# Note: expected runtime: ~10 minutes (including compilation)
# Note: expected runtime ~3 minutes (ignoring compilation)
cargo run --release -p example_zkp_prove -- \
    --example-zkp-fuzzer-machine-code-path ${MACHINE_CODE_PATH} \
    --circuit-path docs/example_data/iadd64.kmx \
    --demanded-max-qubit-count 128 \
    --demanded-max-non-clifford-count 128 \
    --demanded-max-circuit-instructions 1000 \
    --demanded-num-samples 128 \
    --proof-out-path docs/example_data/iadd64_proof.bin \
    --vkey-out-path docs/example_data/iadd64_vkey.bin
```

which should output:

> ```
> stdout: circuit.sha256 = eb06cd07ae320b214792e702c3dafcf4a046c516b4632a294a98c875173a5c4f
> stdout: circuit.num_qubits = 128
> stdout: circuit.num_bits = 0
> stdout: circuit.num_registers = 2
> stdout: circuit.operations.len = 757
> stdout: circuit.average_cliffords_performed = 502
> stdout: circuit.average_non_cliffords_performed = 125
> stdout: The circuit passed fuzz testing.
> Wrote proof to docs/example_data/iadd64_proof.bin
> Wrote vkey to docs/example_data/iadd64_vkey.bin
> ```

Note that the `--vkey-out-path` is optional.
It produces a small file that can be shared instead of the machine code (which is much larger).
Verifiers can confirm the rust code corresponds to the vkey by doing a reproducible
build and rederiving the vkey from its output.
In this document we will do the simple inefficient thing, and verify using the machine code.

## Verifying a Proof

The `example_zkp_verify` tool, whose source code is at
[docs/example_tools/example_zkp_verify/example_zkp_verify.rs](example_tools/example_zkp_verify/example_zkp_verify.rs),
checks that a given proof corresponds to the execution of a given machine.
It is extremely important for a human verifier to actually read this source code, and confirm
it is doing the expected verification (as opposed to just unconditionally printing
"passed verification!" or something more subtle).
Correspondingly, here's an inlined copy of the source code:

```bash
cat docs/example_tools/example_zkp_verify/example_zkp_verify.rs
```

outputs:

> ```rust
> use clap::Parser;
> use sp1_sdk::{
>     ProverClient,
>     Prover,
>     ProvingKey,
>     Elf,
>     SP1ProofWithPublicValues,
> };
> use std::fs;
> use std::sync::Arc;
> 
> #[derive(Parser, Debug)]
> struct CommandLineArgs {
>     #[arg(long)] proof_path: String,
>     #[arg(long)] example_zkp_fuzzer_machine_code_path: String,
>     #[arg(long)] demanded_max_qubit_count: u32,
>     #[arg(long)] demanded_max_non_clifford_count: u32,
>     #[arg(long)] demanded_max_circuit_instructions: u32,
>     #[arg(long)] demanded_num_samples: u32,
> }
> 
> #[tokio::main]
> async fn main() {
>     let args = CommandLineArgs::parse();
>     let proof = SP1ProofWithPublicValues::load(&args.proof_path).expect("Failed to verify: failed to load proof");
> 
>     // Check proven demands match or exceed the verification demands.
>     let mut public_values = proof.public_values.clone();
>     let circuit_hash: [u8; 32] = public_values.read::<[u8; 32]>();
>     let circuit_hash_hex_string: String = circuit_hash
>         .iter()
>         .map(|b| format!("{:02x}", b))
>         .collect();
>     println!("proof.circuit_ops_sha_256 = {}", circuit_hash_hex_string);
>     let proof_demanded_num_samples = public_values.read::<u32>();
>     let proof_demanded_max_qubit_count = public_values.read::<u32>();
>     let proof_demanded_max_non_clifford_count = public_values.read::<u32>();
>     let proof_demanded_max_circuit_instructions = public_values.read::<u32>();
>     println!("proof.demanded_num_samples = {}", proof_demanded_num_samples);
>     println!("proof.demanded_max_qubit_count = {}", proof_demanded_max_qubit_count);
>     println!("proof.demanded_max_non_clifford_count = {}", proof_demanded_max_non_clifford_count);
>     println!("proof.demanded_max_circuit_instructions = {}", proof_demanded_max_circuit_instructions);
>     assert!(proof_demanded_num_samples >= args.demanded_num_samples, "Failed to verify: demanded_num_samples not satisfied by proof");
>     assert!(proof_demanded_max_qubit_count <= args.demanded_max_qubit_count, "Failed to verify: demanded_max_qubit_count not satisfied by proof");
>     assert!(proof_demanded_max_non_clifford_count <= args.demanded_max_non_clifford_count, "Failed to verify: demanded_max_non_clifford_count not satisfied by proof");
>     assert!(proof_demanded_max_circuit_instructions <= args.demanded_max_circuit_instructions, "Failed to verify: demanded_max_circuit_instructions not satisfied by proof");
>     let proof_42 = public_values.read::<u8>();
>     assert!(proof_42 == 42, "Failed to verify: fuzzer didn't end by unnecessarily committing a 42.");
> 
>     // Load the machine.
>     let client = ProverClient::from_env().await;
>     let machine_code_bytes = fs::read(args.example_zkp_fuzzer_machine_code_path).expect("Failed to verify: failed to read machine code file");
>     let machine_code_elf = Elf::Dynamic(Arc::from(machine_code_bytes.into_boxed_slice()));
>     let machine = client.setup(machine_code_elf).await.expect("Failed to verify: failed to setup client");
> 
>     // Verify the proof certifies the machine execution.
>     client.verify(
>         &proof,
>         machine.verifying_key(),
>         None,
>     ).expect("Failed to verify: proof failed verification");
> 
>     println!("✅ Proof passed verification.")
> }
> ```

As you can see from the source code, this verifier is specialized to verifying fuzz testing of
quantum circuits. It doesn't just ask SP1 to verify that correspondence between the machine code
and the proof, it also verifies constraints like the maximum number of qubits used by the circuit.
(You need to read the fuzzer source code to ensure it is writing the constraint values in the same
order they are being read here.)

Here is how you call the `example_zkp_verify` tool to perform the verification:

```bash
MACHINE_CODE_PATH=docs/example_data/iadd64_fuzzer.elf

# Note: expected runtime ~10 minutes (including first time compilation)
# Note: expected runtime ~1 minute (ignoring compilation)
cargo run --release -p example_zkp_verify -- \
    --demanded-max-qubit-count 128 \
    --demanded-max-non-clifford-count 128 \
    --demanded-max-circuit-instructions 1000 \
    --demanded-num-samples 128 \
    --proof-path docs/example_data/iadd64_proof.bin \
    --example-zkp-fuzzer-machine-code-path ${MACHINE_CODE_PATH}
```

> ```
> proof.circuit_ops_sha_256 = eb06cd07ae320b214792e702c3dafcf4a046c516b4632a294a98c875173a5c4f
> proof.demanded_num_samples = 128
> proof.demanded_max_qubit_count = 128
> proof.demanded_max_non_clifford_count = 128
> proof.demanded_max_circuit_instructions = 1000
> ✅ Proof passed verification.
> ```

Using command line tools, you can easily verify that the sha256 hash matches the circuit that was used:

```bash
sha256sum docs/example_data/iadd64.kmx
```

> ```
> eb06cd07ae320b214792e702c3dafcf4a046c516b4632a294a98c875173a5c4f  docs/example_data/iadd64.kmx
> ```

And that the non-Clifford count was in fact at most 128:

```bash
cat docs/example_data/iadd64.kmx | grep "CC[XZ]" | wc -l 
```

> ```
> 125
> ```

This completes the parts of proof verification that can be considered "automatic".
To truly verify a proof you must manually verify more things:

1. Verify that the machine code used in the proof corresponds to the rust code of the fuzzer (by doing a reproducible build as described above).
2. Verify that [docs/example_tools/zkp_fuzzer/zkp_fuzzer.rs](example_tools/example_zkp_fuzzer/example_zkp_fuzzer.rs) actually does fuzz testing (and verifies the properties it claims to verify).
3. Verify that fuzz testing with the Fiat-Shamir heuristic is actually a valid way to confirm a circuit is suitable for use in Shor's algorithm.

Here is an example of how (3) could have failed.
Sophie Schmieg pointed out to us that it was potentially crucial that the circuit format we use isn't Turing complete.
A Turing complete circuit could be written as a [quine](https://en.wikipedia.org/wiki/Quine_(computing)), capable of computing its own hash.
Because the CSPRNG is seeded with a hash of the circuit, a quine could conceivably foretell the outcomes of its own random measurement results.
This could then be used for nefarious purposes such as bypassing probabilistic phase corrections during measurement based uncomputations.
The kickmix circuit format has no conditional branches, so it isn't Turing complete, so it's not possible to make a quine, so this isn't a problem.
But it does speak to the potential of there being subtle issues that we haven't foreseen.

Here is an embarrassing example of how (2) *did* fail.
Keegan Ryan noticed that, in the first version of this repository that was published, there was no code validating that circuit operations were well formed.
For example, the instruction `CX q0 q0` would be accepted instead of rejected (allowing qubits to be cleared at no cost).
By exploiting the lack of sanity checking, they managed to produce a circuit with no non-Clifford gates that spoofed the fuzz testing.

There are many dumb ways and subtle ways to get these things wrong!
We hope the cryptographic community tries their hardest to find flaws in the proofs and in the proof strategy.
