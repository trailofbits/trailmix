use clap::Parser;
use sp1_sdk::{
    ProverClient,
    Prover,
    ProvingKey,
    Elf,
    SP1ProofWithPublicValues,
};
use std::fs;
use std::sync::Arc;

#[derive(Parser, Debug)]
struct CommandLineArgs {
    #[arg(long)] proof_path: String,
    #[arg(long)] example_zkp_fuzzer_machine_code_path: String,
    #[arg(long)] demanded_max_qubit_count: u32,
    #[arg(long)] demanded_max_non_clifford_count: u32,
    #[arg(long)] demanded_max_circuit_instructions: u32,
    #[arg(long)] demanded_num_samples: u32,
}

#[tokio::main]
async fn main() {
    let args = CommandLineArgs::parse();
    let proof = SP1ProofWithPublicValues::load(&args.proof_path).expect("Failed to verify: failed to load proof");

    // Check proven demands match or exceed the verification demands.
    let mut public_values = proof.public_values.clone();
    let circuit_hash: [u8; 32] = public_values.read::<[u8; 32]>();
    let circuit_hash_hex_string: String = circuit_hash
        .iter()
        .map(|b| format!("{:02x}", b))
        .collect();
    println!("proof.circuit_ops_sha_256 = {}", circuit_hash_hex_string);
    let proof_demanded_num_samples = public_values.read::<u32>();
    let proof_demanded_max_qubit_count = public_values.read::<u32>();
    let proof_demanded_max_non_clifford_count = public_values.read::<u32>();
    let proof_demanded_max_circuit_instructions = public_values.read::<u32>();
    println!("proof.demanded_num_samples = {}", proof_demanded_num_samples);
    println!("proof.demanded_max_qubit_count = {}", proof_demanded_max_qubit_count);
    println!("proof.demanded_max_non_clifford_count = {}", proof_demanded_max_non_clifford_count);
    println!("proof.demanded_max_circuit_instructions = {}", proof_demanded_max_circuit_instructions);
    assert!(proof_demanded_num_samples >= args.demanded_num_samples, "Failed to verify: demanded_num_samples not satisfied by proof");
    assert!(proof_demanded_max_qubit_count <= args.demanded_max_qubit_count, "Failed to verify: demanded_max_qubit_count not satisfied by proof");
    assert!(proof_demanded_max_non_clifford_count <= args.demanded_max_non_clifford_count, "Failed to verify: demanded_max_non_clifford_count not satisfied by proof");
    assert!(proof_demanded_max_circuit_instructions <= args.demanded_max_circuit_instructions, "Failed to verify: demanded_max_circuit_instructions not satisfied by proof");
    let proof_42 = public_values.read::<u8>();
    assert!(proof_42 == 42, "Failed to verify: fuzzer didn't end by unnecessarily committing a 42.");

    // Load the machine.
    let client = ProverClient::from_env().await;
    let machine_code_bytes = fs::read(args.example_zkp_fuzzer_machine_code_path).expect("Failed to verify: failed to read machine code file");
    let machine_code_elf = Elf::Dynamic(Arc::from(machine_code_bytes.into_boxed_slice()));
    let machine = client.setup(machine_code_elf).await.expect("Failed to verify: failed to setup client");

    // Verify the proof certifies the machine execution.
    client.verify(
        &proof,
        machine.verifying_key(),
        None,
    ).expect("Failed to verify: proof failed verification");

    println!("✅ Proof passed verification.")
}
