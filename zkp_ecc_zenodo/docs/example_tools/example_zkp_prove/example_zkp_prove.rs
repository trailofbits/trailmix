use clap::Parser;
use sp1_sdk::{
    ProverClient,
    Prover,
    ProveRequest,
    ProvingKey,
    SP1Stdin,
    Elf,
};
use std::io::Write;
use std::fs;
use std::sync::Arc;


#[derive(Parser, Debug)]
struct CommandLineArgs {
    #[arg(long)] circuit_path: String,
    #[arg(long)] example_zkp_fuzzer_machine_code_path: String,
    #[arg(long)] proof_out_path: String,
    #[arg(long)] vkey_out_path: Option<String>,
    #[arg(long)] demanded_max_qubit_count: u32,
    #[arg(long)] demanded_max_non_clifford_count: u32,
    #[arg(long)] demanded_max_circuit_instructions: u32,
    #[arg(long)] demanded_num_samples: u32,
}

#[tokio::main]
async fn main() {
    let args = CommandLineArgs::parse();

    // Serialize values to be read by the ZKP machine.
    let mut stdin = SP1Stdin::new();
    stdin.write(&args.demanded_max_qubit_count);
    stdin.write(&args.demanded_max_non_clifford_count);
    stdin.write(&args.demanded_max_circuit_instructions);
    stdin.write(&args.demanded_num_samples);
    let circuit_bytes = std::fs::read(&args.circuit_path)
        .unwrap_or_else(|_| panic!("Failed to read circuit from {}", args.circuit_path));
    stdin.write_vec(circuit_bytes);

    // Read the elf file defining the ZKP machine.
    let client = ProverClient::from_env().await;
    let machine_code = fs::read(args.example_zkp_fuzzer_machine_code_path).expect("Failed to read machine code input.");
    let machine_elf: Elf = Elf::Dynamic(Arc::from(machine_code.into_boxed_slice()));
    let machine = client.setup(machine_elf).await.expect("failed to setup");

    // Compute the proof.
    let proof = client
            .prove(&machine, stdin)
            .compressed()
            .await
            .expect("failed to generate proof");

    // Save the proof.
    proof.save(&args.proof_out_path).expect("failed to save proof");
    println!("Wrote proof to {}", &args.proof_out_path);

    // Optionally save the verifying key for the machine.
    if let Some(path) = args.vkey_out_path {
        let vk = machine.verifying_key();
        let vk_bytes = bincode::serialize(vk).expect("failed to serialize verifying key");
        let mut file = std::fs::File::create(&path).expect("failed to create vkey file");
        file.write_all(&vk_bytes).expect("failed to write vkey to file");
        println!("Wrote vkey to {}", &path);
    }
}
