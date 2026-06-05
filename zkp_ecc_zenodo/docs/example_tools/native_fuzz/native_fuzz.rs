// Native counterpart of the SP1 guest (`program/src/main.rs`). Runs the
// IDENTICAL validation -- same `zkp_ecc_lib::Simulator` (the simulator that
// gets compiled into the SP1 guest), same Fiat-Shamir test-case generation
// seeded from the circuit text, same value/phase/ancilla/avg-Toffoli checks
// -- but reads its inputs from CLI args + a file instead of `sp1_zkvm::io`,
// so it can run natively (fast) on the full 9000-shot demand.
//
// Usage:
//   native_fuzz <circuit.kmx> <qubit_counts> <toffoli_counts> <total_ops> <num_tests>

use zkp_ecc_lib::{
    circuit::{Circuit, QubitOrBit},
    Simulator, WeierstrassEllipticCurve,
};
use sha2::{Digest, Sha256};
use sha3::{digest::{ExtendableOutput, Update, XofReader}, Shake256};
use ruint::aliases::U256;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 6 {
        eprintln!("Usage: native_fuzz <circuit.kmx> <qubit_counts> <toffoli_counts> <total_ops> <num_tests>");
        std::process::exit(1);
    }
    let kmx_path = &args[1];
    let demanded_qubit_count: u32 = args[2].parse().expect("qubit_counts");
    let demanded_average_non_clifford_count: u32 = args[3].parse().expect("toffoli_counts");
    let demanded_total_ops: u32 = args[4].parse().expect("total_ops");
    let demanded_num_tests: u32 = args[5].parse().expect("num_tests");

    // Read the circuit's raw text bytes (sp1 guest reads these via io::read_vec).
    let private_circuit_kmx_bytes = std::fs::read(kmx_path).expect("read kmx file");

    // (Guest commits a SHA256 of the circuit bytes; here we just print it.)
    let mut hasher = Sha256::default();
    Digest::update(&mut hasher, &private_circuit_kmx_bytes);
    let circuit_hash: [u8; 32] = hasher.finalize().into();
    println!("Circuit hash commitment: {}", hex_encode(&circuit_hash));

    let circuit_text = String::from_utf8(private_circuit_kmx_bytes).expect("Invalid UTF-8");
    let circuit = Circuit::from_text(&circuit_text);

    println!(
        "Circuit Stats: {} qubits, {} bits, {} registers, {} operations",
        circuit.num_qubits, circuit.num_bits, circuit.num_registers, circuit.operations.len()
    );

    // Register-shape checks (target_x, target_y quantum; offset_x, offset_y classical).
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

    assert!(circuit.num_qubits <= demanded_qubit_count, "Qubit count {} exceeds maximum constraint {}", circuit.num_qubits, demanded_qubit_count);
    assert!(circuit.operations.len() as u32 <= demanded_total_ops, "Total ops {} exceeds maximum constraint {}", circuit.operations.len(), demanded_total_ops);

    let curve = WeierstrassEllipticCurve {
        modulus: U256::from_str_radix("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F", 16).unwrap(),
        a: U256::from(0),
        b: U256::from(7),
        gx: U256::from_str_radix("79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798", 16).unwrap(),
        gy: U256::from_str_radix("483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8", 16).unwrap(),
        order: U256::from_str_radix("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16).unwrap(),
    };

    // Fiat-Shamir: seed a CSPRNG from the circuit text, generate the test cases.
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

    // Same simulator that gets compiled into the SP1 guest, seeded with the
    // same xof (so HMR randomness matches the guest stream too).
    let mut sim = Simulator::new(circuit.num_qubits as usize, circuit.num_bits as usize, &mut xof);

    const BATCH_SIZE: usize = 64;
    let num_batches = (demanded_num_tests as usize).div_ceil(BATCH_SIZE);
    for batch in 0..num_batches {
        let current_batch_size = std::cmp::min(BATCH_SIZE, (demanded_num_tests as usize) - batch * BATCH_SIZE);
        sim.clear_for_shot();
        for shot in 0..current_batch_size {
            let i = batch * BATCH_SIZE + shot;
            sim.set_register(&circuit.registers[0], all_target_x[i], shot);
            sim.set_register(&circuit.registers[1], all_target_y[i], shot);
            sim.set_register(&circuit.registers[2], all_offset_x[i], shot);
            sim.set_register(&circuit.registers[3], all_offset_y[i], shot);
        }

        sim.apply_iter(circuit.operations.iter());

        for shot in 0..current_batch_size {
            let i = batch * BATCH_SIZE + shot;
            let output_x = sim.get_register(&circuit.registers[0], shot);
            let output_y = sim.get_register(&circuit.registers[1], shot);
            assert!(output_x == all_expected_x[i] && output_y == all_expected_y[i], "Circuit produced the wrong elliptic curve point (shot {i})");
        }

        let phase = sim.phase;
        for shot in 0..current_batch_size {
            assert!((phase >> shot) & 1 == 0, "Circuit produced phase garbage");
        }

        for register in &circuit.registers {
            for qb in register {
                if let QubitOrBit::Qubit(q) = *qb {
                    *sim.qubit_mut(q) = 0;
                }
            }
        }
        for q in 0..sim.num_qubits {
            let v = sim.qubit(zkp_ecc_lib::circuit::QubitId(q.try_into().unwrap()));
            assert!(v == 0, "Circuit left garbage behind ({q} was not cleared to 0)");
        }
        if (batch + 1) % 16 == 0 || batch + 1 == num_batches {
            eprintln!("[native_fuzz] batch {}/{} ok ({} shots)", batch + 1, num_batches, (batch + 1) * BATCH_SIZE);
        }
    }

    let avg_clifford = sim.stats.clifford_gates / demanded_num_tests as u64;
    let avg_toffoli = sim.stats.toffoli_gates / demanded_num_tests as u64;
    println!("Average Simulator Stats: {avg_clifford} clifford gates, {avg_toffoli} toffoli gates per shot");
    assert!(avg_toffoli <= demanded_average_non_clifford_count as u64, "Average Toffoli count {avg_toffoli} exceeds maximum constraint {demanded_average_non_clifford_count}");

    println!("PASS: {demanded_num_tests} shots, all value/phase/ancilla/budget checks held.");
}

fn hex_encode(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}
