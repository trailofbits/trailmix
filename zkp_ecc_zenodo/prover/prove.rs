use clap::Parser;
use sp1_sdk::{
    ProverClient, Prover, ProveRequest, ProvingKey,
    include_elf, Elf, SP1Stdin,
};

use std::io::Write;
use std::time::{Duration, Instant};
use std::fs::OpenOptions;

/// The ELF (executable and linkable format) file for the Succinct RISC-V zkVM.
const ZKP_ECC_ELF: Elf = include_elf!("zkp_ecc-program");

/// Helper function to format Duration into a human-readable HH:MM:SS.ms string
fn format_duration(duration: Duration) -> String {
    let secs = duration.as_secs();
    let ms = duration.subsec_millis();
    let hours = secs / 3600;
    let mins = (secs % 3600) / 60;
    let secs = secs % 60;

    if hours > 0 {
        format!("{:02}h {:02}m {:02}s {}ms", hours, mins, secs, ms)
    } else if mins > 0 {
        format!("{:02}m {:02}s {}ms", mins, secs, ms)
    } else {
        format!("{}.{:03}s", secs, ms)
    }
}

/// Helper function to format u64 with commas
fn format_u64(n: u64) -> String {
    let s = n.to_string();
    let mut result = String::new();
    for (i, c) in s.chars().rev().enumerate() {
        if i > 0 && i % 3 == 0 {
            result.insert(0, ',');
        }
        result.insert(0, c);
    }
    result
}

/// The arguments for the command.
#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    #[arg(long)]
    execute: bool,

    #[arg(long)]
    prove: bool,

    #[arg(long)]
    kmx: String,

    #[arg(long)]
    qubit_counts: u32,

    #[arg(long)]
    toffoli_counts: u32,

    #[arg(long)]
    total_ops: u32,

    #[arg(long, default_value = "64")]
    num_tests: u32,
}

#[tokio::main]
async fn main() {
    // Setup the logger.
    sp1_sdk::utils::setup_logger();

    let args = Args::parse();

    if args.execute == args.prove {
        eprintln!("Error: You must specify either --execute or --prove");
        std::process::exit(1);
    }

    // Read the circuit file as raw bytes.
    let circuit_bytes = std::fs::read(&args.kmx)
        .unwrap_or_else(|_| panic!("Failed to read circuit from {}", args.kmx));

    let kmx_path = std::path::Path::new(&args.kmx);
    let fname = kmx_path
        .file_stem()
        .expect("Invalid kmx file path")
        .to_str()
        .unwrap();

    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    let workspace_root = std::path::Path::new(manifest_dir).parent().unwrap();
    let proof_dir = workspace_root.join("proofs").join(fname);
    std::fs::create_dir_all(&proof_dir).expect("failed to create proofs directory");
    let perf_log_path = proof_dir.join("performance.log");


    let client = ProverClient::from_env().await;
    
    let mut stdin = SP1Stdin::new();
    stdin.write(&args.qubit_counts);
    stdin.write(&args.toffoli_counts);
    stdin.write(&args.total_ops);
    stdin.write(&args.num_tests);
    stdin.write_vec(circuit_bytes);

    let start_time = Instant::now();

    if args.execute {
        println!("Execution mode enabled: simulating ZK Proof");



        let (mut output, report) = client.execute(ZKP_ECC_ELF, stdin).await.expect("failed to execute");
        let cycles = report.total_instruction_count();
        let elapsed = start_time.elapsed();
        println!("Number of cycles: {}", format_u64(cycles));
        let syscalls = report.total_syscall_count();
        println!("Number of syscalls: {}", format_u64(syscalls));

        // Standard output logic only for full run
        println!("Execution simulated successfully!");
        let output_hash = output.read::<[u8; 32]>();
        println!("Circuit hash commitment: {:?}", hex::encode(output_hash));
        
        let reported_num_tests = output.read::<u32>();
        assert_eq!(reported_num_tests, args.num_tests, "Mismatch in num_tests");

        let demanded_qubit_count = output.read::<u32>();
        let demanded_average_non_clifford_count = output.read::<u32>();
        let demanded_total_ops = output.read::<u32>();
        
        println!("Demanded Qubit count: {}", demanded_qubit_count);
        println!("Demanded Average non-Clifford count: {}", demanded_average_non_clifford_count);
        println!("Demanded Total ops: {}", demanded_total_ops);
    
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&perf_log_path)
            .expect("Failed to open performance log");
        writeln!(file, "[{}] EXECUTE TESTS {}: {:>12} cycles, {:>12} syscalls in {}", chrono::Local::now().to_rfc3339(), args.num_tests, cycles, syscalls, format_duration(elapsed)).unwrap();
        println!("Performance metrics logged to: {}", perf_log_path.display());
    } else {


        let prove_start_time = Instant::now();
        let use_cluster = std::env::var("USE_CLUSTER").unwrap_or_default() == "true";
        
        let pk = client.setup(ZKP_ECC_ELF).await.expect("failed to setup");
        let proof = if use_cluster {
            println!(
                "Proving mode enabled: Submitting STARK Proof to remote SP1 Cluster..."
            );
            
            use sp1_cluster_utils::{request_proof_from_env, ClusterElf};
            use sp1_sdk::network::proto::types::ProofMode;
            
            let cluster_elf = ClusterElf::NewElf(ZKP_ECC_ELF.to_vec());
            let timeout_hours: u64 = std::env::var("SP1_PROVE_TIMEOUT_HOURS")
                .unwrap_or_else(|_| "4".to_string())
                .parse()
                .expect("SP1_PROVE_TIMEOUT_HOURS must be a valid integer");
            println!("PARSED TIMEOUT HOURS: {}", timeout_hours);
            
            let results = request_proof_from_env(
                ProofMode::Groth16,
                timeout_hours,
                cluster_elf,
                stdin.clone(),
            ).await.expect("Failed to get proof from cluster");
            
            println!("Successfully received proof from cluster! Proof ID: {}", results.proof_id);
            let p: sp1_sdk::SP1ProofWithPublicValues = results.proof.into();
            p
        } else {

            println!(
                "Proving mode enabled: Generating cryptographic STARK Proof locally (this may take a while...)"
            );
            let p = client
                .prove(&pk, stdin)
                .groth16()
                .await
                .expect("failed to generate proof");
            p
        };
        
        let prove_elapsed = prove_start_time.elapsed();
        
        println!("Successfully generated proof in {}", format_duration(prove_elapsed));

        let proof_path = proof_dir.join(format!("proof_{}.bin", args.num_tests));
        proof.save(&proof_path).expect("failed to save proof");
        println!("Proof saved to: {}", proof_path.display());

        // Save Verifying Key (.vkey)
        let vk = pk.verifying_key();
        let vkey_path = proof_dir.join("vkey.bin");
        let vk_bytes = bincode::serialize(vk).expect("failed to serialize verifying key");
        let mut file = std::fs::File::create(&vkey_path).expect("failed to create vkey file");
        file.write_all(&vk_bytes).expect("failed to write vkey to file");
        println!("Verifying key saved to: {}", vkey_path.display());

        let verify_start = Instant::now();
        client
            .verify(&proof, pk.verifying_key(), None)
            .expect("failed to verify proof");
        let verify_elapsed = verify_start.elapsed();
        println!("Successfully verified STARK proof in {}", format_duration(verify_elapsed));
        let verify_elapsed_str = format_duration(verify_elapsed);
        
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&perf_log_path)
            .expect("Failed to open performance log");
        let total_elapsed = start_time.elapsed();
        writeln!(file, "[{}] PROVE TESTS {}: Generated in {}, Verified in {}, Total session time: {}", 
                 chrono::Local::now().to_rfc3339(), args.num_tests, format_duration(prove_elapsed), verify_elapsed_str, format_duration(total_elapsed)).unwrap();
        println!("Performance metrics logged to: {}", perf_log_path.display());
    }
}
