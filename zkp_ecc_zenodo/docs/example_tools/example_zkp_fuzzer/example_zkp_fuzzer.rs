#![no_main]
sp1_zkvm::entrypoint!(zkp_main);

use zkp_ecc_lib::{
    circuit::{Op, analyze_ops, QubitOrBit},
    Simulator,
};
use std::num::Wrapping;
use ruint::aliases::U256;
use sha2::Sha256;
use sha3::{Shake256, digest::{Update, FixedOutput, ExtendableOutput, XofReader}};

pub fn zkp_main() {
    // Read private inputs (the demands and the circuit that should meet them).
    let demanded_qubit_count = sp1_zkvm::io::read::<u32>();
    let demanded_average_non_clifford_count = sp1_zkvm::io::read::<u32>();
    let demanded_total_ops = sp1_zkvm::io::read::<u32>();
    let demanded_num_tests = sp1_zkvm::io::read::<u32>();
    let private_circuit_kmx_bytes = sp1_zkvm::io::read_vec();

    // Commit a SHA256 hash of the circuit's raw text bytes.
    let mut hasher = Sha256::default();
    hasher.update(&private_circuit_kmx_bytes);
    let circuit_hash: [u8; 32] = hasher.finalize_fixed().into();
    sp1_zkvm::io::commit(&circuit_hash);
    let mut hasher = Shake256::default();
    hasher.update(&private_circuit_kmx_bytes);
    let mut xof = hasher.finalize_xof();

    // Parse the circuit text.
    let circuit_text = String::from_utf8(private_circuit_kmx_bytes).expect("Invalid UTF-8");
    let mut ops = Vec::new();
    for line in circuit_text.lines() {
        if let Some(op) = Op::from_text(line) {
            ops.push(op);
        }
    }

    // Compute circuit stats.
    let total_ops = ops.len() as u32;
    let (total_qubits, num_bits, num_regs, registers) = analyze_ops(ops.iter());
    let circuit_hash_hex_string: String = circuit_hash
        .iter()
        .map(|b| format!("{:02x}", b))
        .collect();
    println!("circuit.sha256 = {}", circuit_hash_hex_string);
    println!("circuit.num_qubits = {}", total_qubits);
    println!("circuit.num_bits = {}", num_bits);
    println!("circuit.num_registers = {}", num_regs);
    println!("circuit.operations.len = {}", total_ops);

    // Verify the circuit's registers have the expected form for performing quantum-classical integer addition (`target += offset`).
    // For reference, the form should be:
    //     register 0: 64-qubit register for the 'target' integer
    //     register 1: 64-bit register for the 'offset' integer
    assert!(registers.len() == 2, "Circuit should have exactly 4 registers: target_x, target_y, offset_x, offset_y");
    assert!(registers[0].len() == 64, "register 0 should be composed of 64 qubits");
    for q in &registers[0] {
        assert!(matches!(q, QubitOrBit::Qubit(_)), "register 0 should be composed of 64 qubits");
    }
    assert!(registers[1].len() == 64, "register 1 should be composed of 64 qubits");
    for q in &registers[1] {
        assert!(matches!(q, QubitOrBit::Qubit(_)), "register 1 should be composed of 64 qubits");
    }

    // Assert circuit stats are within demanded bounds.
    // (The average non-Clifford count can only be tested later because gates can happen probabilistically.)
    assert!(total_qubits <= demanded_qubit_count, "Qubit count {} exceeds maximum constraint {}", total_qubits, demanded_qubit_count);
    assert!(total_ops <= demanded_total_ops, "Total ops {} exceeds maximum constraint {}", total_ops, demanded_total_ops);

    // Commit demanded values.
    sp1_zkvm::io::commit(&demanded_num_tests);
    sp1_zkvm::io::commit(&demanded_qubit_count);
    sp1_zkvm::io::commit(&demanded_average_non_clifford_count);
    sp1_zkvm::io::commit(&demanded_total_ops);

    // Generate test inputs and expected outputs.
    // Make the inputs unpredictable to the circuit by using Fiat-Shamir
    // (i.e. by instantiating a CSPRNG seeded using the contents of the circuit)
    let mut all_target: Vec<U256> = Vec::with_capacity(demanded_num_tests as usize);
    let mut all_offset: Vec<U256> = Vec::with_capacity(demanded_num_tests as usize);
    let mut all_expected: Vec<U256> = Vec::with_capacity(demanded_num_tests as usize);
    for _ in 0..demanded_num_tests {
        let mut r_bytes = [[0u8; 8]; 2];
        xof.read(&mut r_bytes[0]);
        xof.read(&mut r_bytes[1]);

        let target: u64 = u64::from_le_bytes(r_bytes[0]);
        let offset: u64 = u64::from_le_bytes(r_bytes[0]);
        let expected_output = (Wrapping(target) + Wrapping(offset)).0;

        all_target.push(U256::from(target));
        all_offset.push(U256::from(offset));
        all_expected.push(U256::from(expected_output));
    }

    // Initialize the Simulator
    let mut sim = Simulator::new(
        total_qubits as usize,
        num_bits as usize,
        &mut xof,
    );

    // Perform the shots while testing for correctness.
    // (Note: the simulator works in batches of 64 shots due to bit-stripping state across `u64`s.)
    const BATCH_SIZE: usize = 64;
    let num_batches = (demanded_num_tests as usize + BATCH_SIZE - 1) / BATCH_SIZE;
    for batch in 0..num_batches {

        let current_batch_size = std::cmp::min(BATCH_SIZE, (demanded_num_tests as usize) - batch * BATCH_SIZE);

        // Load the test case into the input qubits and input bits.
        sim.clear_for_shot();
        for shot in 0..current_batch_size {
            let i = batch * BATCH_SIZE + shot;
            let target = all_target[i];
            let offset = all_offset[i];

            sim.set_register(&registers[0], target, shot);
            sim.set_register(&registers[1], offset, shot);
        }

        // Update the simulator's state by applying the operations from the circuit.
        sim.apply_iter(ops.iter());

        // Check that the expected output was produced.
        for shot in 0..current_batch_size {
            let i = batch * BATCH_SIZE + shot;
            let output = sim.get_register(&registers[0], shot);
            let expected = all_expected[i];
            assert!(output == expected, "Circuit produced the wrong output");
        }

        // Check for phase garbage (e.g. incorrectly fixed phase kickback from an HMR instruction).
        let phase = sim.phase;
        for shot in 0..current_batch_size {
            let phase_bit = (phase >> shot) & 1;
            assert!(phase_bit == 0, "Circuit produced phase garbage");
        }

        // Check for any ancillary garbage (by zeroing non-ancillary qubits then looking for unzero'd qubits).
        for register in &registers {
            for qb in register {
                if let zkp_ecc_lib::QubitOrBit::Qubit(q) = *qb {
                    *sim.qubit_mut(q) = 0;
                }
            }
        }
        for q in 0..sim.num_qubits {
            let v = sim.qubit(zkp_ecc_lib::QubitId(q.try_into().unwrap()));
            assert!(v == 0, "Circuit left garbage behind ({} was not cleared to 0)", q);
        }
    }

    // Verify the sampled operation counts meet the demands.
    let avg_clifford = sim.stats.clifford_gates / demanded_num_tests as u64;
    let avg_non_clifford = sim.stats.toffoli_gates / demanded_num_tests as u64;
    assert!(avg_non_clifford <= demanded_average_non_clifford_count as u64, "Average non-clifford count {} exceeds maximum {}", avg_non_clifford, demanded_average_non_clifford_count);
    println!("circuit.average_cliffords_performed = {}", avg_clifford);
    println!("circuit.average_non_cliffords_performed = {}", avg_non_clifford);
    println!("The circuit passed fuzz testing.");

    // Unnecessarily write the byte '42' to indicate success.
    let success: u8 = 42;
    sp1_zkvm::io::commit(&success);
}
