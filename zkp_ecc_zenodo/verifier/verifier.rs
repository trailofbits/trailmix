use clap::Parser;
use sp1_sdk::{Elf, HashableKey, Prover, ProverClient, ProvingKey, SP1ProofWithPublicValues};
use sp1_build::{build_program_with_args, BuildArgs};
use std::sync::Arc;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    #[arg(long)]
    proof: String,

    #[arg(long)]
    vkey: Option<String>,

    #[arg(long)]
    elf: Option<String>,
}

#[tokio::main]
async fn main() {
    let args = Args::parse();
    let client = ProverClient::from_env().await;

    // Read or generate the verification key.
    let vk = if let Some(vkey_path) = args.vkey {
        let vk_bytes = std::fs::read(&vkey_path).expect("failed to read vkey file");
        bincode::deserialize(&vk_bytes).expect("failed to deserialize vkey")
    } else if let Some(elf_path) = args.elf {
        let bytes = std::fs::read(&elf_path).expect("failed to read elf file");
        let elf_data = Elf::Dynamic(Arc::from(bytes.into_boxed_slice()));
        let pk = client.setup(elf_data).await.expect("failed to setup");
        pk.verifying_key().clone()
    } else {
        println!("Neither --vkey nor --elf provided. Building program using Docker...");
        let manifest_dir = env!("CARGO_MANIFEST_DIR");
        let workspace_root = std::path::Path::new(manifest_dir).parent().unwrap();
        let program_dir = workspace_root.join("program");

        let build_args = BuildArgs {
            docker: true,
            ..Default::default()
        };
        build_program_with_args(program_dir.to_str().unwrap(), build_args);
        
        let elf_path = workspace_root.join("target/elf-compilation/docker/riscv64im-succinct-zkvm-elf/release/zkp_ecc-program");
        let bytes = std::fs::read(&elf_path).unwrap_or_else(|e| {
            panic!("failed to read generated elf file from {}: {}", elf_path.display(), e)
        });
        let elf_data = Elf::Dynamic(Arc::from(bytes.into_boxed_slice()));
        let pk = client.setup(elf_data).await.expect("failed to setup");
        pk.verifying_key().clone()
    };

    println!("Verifying Key (Hex): {}", vk.bytes32());

    // Load the proof and print it in hex format.
    let mut proof = SP1ProofWithPublicValues::load(&args.proof).expect("failed to load proof");
    if matches!(&proof.proof, sp1_sdk::SP1Proof::Plonk(_) | sp1_sdk::SP1Proof::Groth16(_)) {
        // For Groth16 and Plonk, `proof.bytes()` gives the `[vkey_hash || encoded_proof]` format.
        println!("Proof (Hex): 0x{}", hex::encode(proof.bytes()));
    }

    // Verify the proof.
    client.verify(&proof, &vk, None).expect("failed to verify proof");

    let proof_type = match &proof.proof {
        sp1_sdk::SP1Proof::Core(_) => "Core STARK",
        sp1_sdk::SP1Proof::Compressed(_) => "Compressed STARK",
        sp1_sdk::SP1Proof::Plonk(_) => "Plonk SNARK",
        sp1_sdk::SP1Proof::Groth16(_) => "Groth16 SNARK",
    };
    println!("Successfully verified {} proof.", proof_type);
    
    // Read and print public values in human-readable format
    let output_hash = proof.public_values.read::<[u8; 32]>();
    println!("Circuit hash commitment: 0x{}", hex::encode(output_hash));
    
    let num_tests = proof.public_values.read::<u32>();
    println!("Demanded Number of tests: {}", num_tests);

    let demanded_qubit_count = proof.public_values.read::<u32>();
    println!("Demanded Qubit count: {}", demanded_qubit_count);

    let demanded_average_non_clifford_count = proof.public_values.read::<u32>();
    println!("Demanded Average non-Clifford count: {}", demanded_average_non_clifford_count);

    let demanded_total_ops = proof.public_values.read::<u32>();
    println!("Demanded Total ops: {}", demanded_total_ops);


}
