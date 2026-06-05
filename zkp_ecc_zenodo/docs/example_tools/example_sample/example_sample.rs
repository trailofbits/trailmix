use std::env;
use zkp_ecc_lib::Circuit;
use zkp_ecc_lib::Simulator;
use ruint::aliases::U256;
use sha3::{Shake256, digest::{Update, ExtendableOutput}};
use rand::Rng;

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() < 2 {
        eprintln!("Usage: sample <circuit_path> <register0_initial_value> ...");
        return;
    }

    // Randomly seed the CSPRNG.
    let mut hasher = Shake256::default();
    let seed: [u8; 32] = rand::thread_rng().gen();
    hasher.update(&seed);
    let mut xof = hasher.finalize_xof();

    let circuit = Circuit::from_kmx(&args[1]).unwrap();

    let mut sim = Simulator::new(
        circuit.num_qubits as usize,
        circuit.num_bits as usize,
        &mut xof,
    );

    if args.len() != circuit.registers.len() + 2 {
        eprintln!("The given circuit declares {} registers, but you passed {} initial value arguments.\nUsage: <circuit_path> <register0_initial_value> ...", circuit.registers.len(), args.len() - 2);
        return;
    }
    for k in 0..circuit.registers.len() {
        let v = args[k + 2].parse::<U256>().expect("Argument is not an integer");
        sim.set_register(&circuit.registers[k], v, 0);
    }

    sim.apply_iter(circuit.operations.iter());

    for k in 0..circuit.registers.len() {
        if k > 0 {
            print!(" ");
        }
        print!("{}", sim.get_register(&circuit.registers[k], 0));
    }
    print!("\n");
}
