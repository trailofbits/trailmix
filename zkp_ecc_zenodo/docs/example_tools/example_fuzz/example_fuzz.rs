use std::env;
use zkp_ecc_lib::{Circuit, Simulator, QubitOrBit, QubitId};
use ruint::aliases::U256;
use rand::{Rng, rngs::OsRng};

use std::io::{BufRead, stdin};
use sha3::{Shake256, digest::{Update, ExtendableOutput, XofReader}};

fn check_block<R: XofReader>(sim: &mut Simulator<R>, lines: &Vec<String>, expected_outputs: &Vec<Vec<U256>>, reg: &Vec<Vec<QubitOrBit>>, shots: usize) -> bool {
    for s in 0..lines.len() {
        let phase = (sim.phase >> s) & 1 != 0;
        let mut failed = phase;
        for k in 0..reg.len() {
            if sim.get_register(&reg[k], s) != expected_outputs[s][k] {
                failed = true;
            }
        }
        if failed {
            eprintln!("Test failed: {}", lines[s]);
            eprint!("    actual outputs:");
            for k in 0..reg.len() {
                eprint!(" {}", sim.get_register(&reg[k], s));
            }
            if phase {
                eprint!("\n    inverted phase");
            }
            eprintln!("");
            eprintln!("tests passed before failure: {}", shots + s);
            return true
        }
    }
    for register in reg {
        for qb in register {
            if let QubitOrBit::Qubit(q) = qb {
                *sim.qubit_mut(*q) = 0;
            }
        }
    }
    let mut failed: usize = 64;
    for q in 0..sim.num_qubits {
        let v = sim.qubit(QubitId(q.try_into().unwrap()));
        if v != 0 {
            for s in 0..lines.len() {
                if (v >> s) & 1 != 0 && s < failed {
                    failed = s;
                }
            }
        }
    }
    if failed < 64 {
        let s = failed;
        eprintln!("Test failed: {}", lines[s]);
        eprint!("    some ancillary qubits weren't cleared to 0:");
        for q in 0..sim.num_qubits {
            if (sim.qubit(QubitId(q.try_into().unwrap())) >> s) & 1 != 0 {
                eprint!(" q{}", q);
            }
        }
        eprintln!("");
        eprintln!("tests passed before failure: {}", shots + s);
        return true;
    }
    false
}

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() != 2 {
        eprintln!("Usage: fuzz <circuit_path> (with test cases fed to stdin)");
        return
    }

    // Seed the simulator's CSPRNG with system entropy.
    let mut hasher = Shake256::default();
    let random_val: u64 = OsRng.gen();
    hasher.update(&random_val.to_le_bytes());
    let mut xof = hasher.finalize_xof();

    // Parse the circuit.
    let circuit = Circuit::from_kmx(&args[1]).unwrap();

    let mut sim = Simulator::new(
        circuit.num_qubits as usize,
        circuit.num_bits as usize,
        &mut xof,
    );

    // Start simulating shots according to lines from stdin like "a b -> c d".
    let mut shot_index = 0;
    let mut expected_outputs: Vec<Vec<U256>> = Vec::new();
    let mut lines : Vec<String> = Vec::new();
    let mut shots : usize = 0;
    for line in stdin().lock().lines() {
        let line = line.expect("stdin");
        let (inp, out) = line.split_once(" -> ").unwrap();
        let inputs: Vec<U256> = inp.split_whitespace().filter_map(|s| s.parse::<U256>().ok()).collect();
        let outputs: Vec<U256> = out.split_whitespace().filter_map(|s| s.parse::<U256>().ok()).collect();
        expected_outputs.push(outputs);
        if inputs.len() != circuit.registers.len() || expected_outputs[expected_outputs.len() - 1].len() != circuit.registers.len() {
            eprintln!("Line had wrong number of inputs or outputs: {}", line);
            return
        }
        lines.push(line);
        for k in 0..circuit.registers.len() {
            sim.set_register(&circuit.registers[k], inputs[k], shot_index);
        }
        shot_index += 1;
        if shot_index == 64 {
            sim.apply_iter(circuit.operations.iter());
            if check_block(&mut sim, &lines, &expected_outputs, &circuit.registers, shots) {
                return;
            }
            sim.clear_for_shot();
            lines.clear();
            expected_outputs.clear();
            shot_index = 0;
            shots += 64;
        }
    }

    if shot_index > 0 {
        sim.apply_iter(circuit.operations.iter());
        if check_block(&mut sim, &lines, &expected_outputs, &circuit.registers, shots) {
            return;
        }
        shots += shot_index;
    }

    print!("pass ({} shots)\n", shots);
}
