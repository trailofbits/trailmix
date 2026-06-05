#![no_main]
sp1_zkvm::entrypoint!(main);

use zkp_ecc_lib::{
    circuit::{QubitOrBit, Circuit},
    Simulator,
    WeierstrassEllipticCurve,
};
use sha2::Sha256;
use sha3::{Shake256, digest::{Update, FixedOutput, ExtendableOutput, XofReader}};
use ruint::aliases::U256;

pub fn main() {
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

    // Parse the circuit text.
    let circuit_text = String::from_utf8(private_circuit_kmx_bytes).expect("Invalid UTF-8");
    let circuit = Circuit::from_text(&circuit_text);

    println!("Circuit Stats: {} qubits, {} bits, {} registers, {} operations", circuit.num_qubits, circuit.num_bits, circuit.num_registers, circuit.operations.len());
    
    // Verify the circuit's registers have the expected form for performing elliptic curve point addition (`target += offset`).
    // For reference, the form should be:
    //     register 0: 256-qubit register for X coordinate of the 'target' elliptic curve point
    //     register 1: 256-qubit register for Y coordinate of the 'target' elliptic curve point
    //     register 2: 256-bit register for X coordinate of the 'offset' elliptic curve point
    //     register 3: 256-bit register for Y coordinate of the 'offset' elliptic curve point
    assert!(circuit.registers.len() == 4, "Circuit should have exactly 4 registers: target_x, target_y, offset_x, offset_y");
    assert!(circuit.registers[0].len() == 256, "register 0 should be composed of 256 qubits");
    for q in &circuit.registers[0] {
        assert!(matches!(q, QubitOrBit::Qubit(_)), "register 0 should be composed of 256 qubits");
    }
    assert!(circuit.registers[1].len() == 256, "register 1 should be composed of 256 qubits");
    for q in &circuit.registers[1] {
        assert!(matches!(q, QubitOrBit::Qubit(_)), "register 1 should be composed of 256 qubits");
    }
    assert!(circuit.registers[2].len() == 256, "register 2 should be composed of 256 classical qubits");
    for q in &circuit.registers[2] {
        assert!(matches!(q, QubitOrBit::Bit(_)), "register 2 should be composed of 256 qubits");
    }
    assert!(circuit.registers[3].len() == 256, "register 3 should be composed of 256 classical bits");
    for q in &circuit.registers[3] {
        assert!(matches!(q, QubitOrBit::Bit(_)), "register 3 should be composed of 256 qubits");
    }

    // Assert circuit stats are within demanded bounds.
    // (The average non-Clifford count can only be tested later because gates can happen probabilistically.)
    assert!(circuit.num_qubits <= demanded_qubit_count, "Qubit count {} exceeds maximum constraint {}", circuit.num_qubits, demanded_qubit_count);
    assert!(circuit.operations.len() as u32 <= demanded_total_ops, "Total ops {} exceeds maximum constraint {}", circuit.operations.len(), demanded_total_ops);
    


    // Commit demanded values.
    sp1_zkvm::io::commit(&demanded_num_tests);
    sp1_zkvm::io::commit(&demanded_qubit_count);
    sp1_zkvm::io::commit(&demanded_average_non_clifford_count);
    sp1_zkvm::io::commit(&demanded_total_ops);

    // The tests will use the secp256k1 curve.
    let curve = WeierstrassEllipticCurve {
        modulus: U256::from_str_radix("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F", 16).unwrap(),
        a: U256::from(0),
        b: U256::from(7),
        gx: U256::from_str_radix("79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798", 16).unwrap(),
        gy: U256::from_str_radix("483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8", 16).unwrap(),
        order: U256::from_str_radix("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16).unwrap(),
    };

    // Generate test inputs and expected outputs.
    // Make the inputs unpredictable to the circuit by using Fiat-Shamir
    // (i.e. by instantiating a CSPRNG seeded using the contents of the circuit)
    let mut hasher = Shake256::default();
    hasher.update(circuit_text.as_bytes());
    let mut xof = hasher.finalize_xof();
    let mut all_target_x = Vec::with_capacity(demanded_num_tests as usize);
    let mut all_target_y = Vec::with_capacity(demanded_num_tests as usize);
    let mut all_offset_x = Vec::with_capacity(demanded_num_tests as usize);
    let mut all_offset_y = Vec::with_capacity(demanded_num_tests as usize);
    let mut all_expected_x = Vec::with_capacity(demanded_num_tests as usize);
    let mut all_expected_y = Vec::with_capacity(demanded_num_tests as usize);
    for _ in 0..demanded_num_tests {
        let mut r_bytes = [[0u8; 32]; 2];
        xof.read(&mut r_bytes[0]);
        xof.read(&mut r_bytes[1]);

        let (target_x, target_y) = curve.mul(curve.gx, curve.gy, U256::from_le_bytes(r_bytes[0]));
        let (offset_x, offset_y) = curve.mul(curve.gx, curve.gy, U256::from_le_bytes(r_bytes[1]));
        let expected_output = curve.add(target_x, target_y, offset_x, offset_y);
        assert!(curve.is_on_curve(target_x, target_y), "target not on curve");
        assert!(curve.is_on_curve(offset_x, offset_y), "offset not on curve");

        all_target_x.push(target_x);
        all_target_y.push(target_y);
        all_offset_x.push(offset_x);
        all_offset_y.push(offset_y);
        all_expected_x.push(expected_output.0);
        all_expected_y.push(expected_output.1);
    }


    // Initialize the Simulator
    let mut sim = Simulator::new(
        circuit.num_qubits as usize,
        circuit.num_bits as usize,
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
            let target_x = all_target_x[i];
            let target_y = all_target_y[i];
            let offset_x = all_offset_x[i];
            let offset_y = all_offset_y[i];

            // These two registers are quantum values storing the target point (the one to mutate into the output).
            sim.set_register(&circuit.registers[0], target_x, shot);
            sim.set_register(&circuit.registers[1], target_y, shot);
            // These two registers are classical values storing the offset point.
            sim.set_register(&circuit.registers[2], offset_x, shot);
            sim.set_register(&circuit.registers[3], offset_y, shot);
        }

        // Update the simulator's state by applying the operations from the circuit.
        sim.apply_iter(circuit.operations.iter());

        // Check that the expected output was produced.
        for shot in 0..current_batch_size {
            let i = batch * BATCH_SIZE + shot;
            let output_x = sim.get_register(&circuit.registers[0], shot);
            let output_y = sim.get_register(&circuit.registers[1], shot);
            let expected_x = all_expected_x[i];
            let expected_y = all_expected_y[i];
            assert!(output_x == expected_x && output_y == expected_y, "Circuit produced the wrong elliptic curve point");
        }

        // Check for phase garbage (e.g. incorrectly fixed phase kickback from an HMR instruction).
        let phase = sim.phase;
        for shot in 0..current_batch_size {
            let phase_bit = (phase >> shot) & 1;
            assert!(phase_bit == 0, "Circuit produced phase garbage");
        }

        // Check for any ancillary garbage (by zeroing non-ancillary qubits then looking for unzero'd qubits).
        for register in &circuit.registers {
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
    let avg_toffoli = sim.stats.toffoli_gates / demanded_num_tests as u64;
    println!("Average Simulator Stats: {} clifford gates, {} toffoli gates per shot", avg_clifford, avg_toffoli);
    assert!(avg_toffoli <= demanded_average_non_clifford_count as u64, "Average Toffoli count {} exceeds maximum constraint {}", avg_toffoli, demanded_average_non_clifford_count);
}
