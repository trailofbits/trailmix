use zkp_ecc_lib::circuit::{Op, OperationType, QubitId, BitId, RegisterId, NO_QUBIT, NO_BIT, NO_REG};

#[test]
fn test_op_validate_ccx_valid() {
    let mut op = Op::empty();
    op.kind = OperationType::CCX;
    op.q_control2 = QubitId(2);
    op.q_control1 = QubitId(1);
    op.q_target = QubitId(3);
    op.c_condition = BitId(4);
    op.validate();
}

#[test]
fn test_op_validate_hmr_valid() {
    let mut op = Op::empty();
    op.kind = OperationType::Hmr;
    op.q_target = QubitId(1);
    op.c_target = BitId(2);
    op.c_condition = BitId(3);
    op.validate();
}

#[test]
#[should_panic(expected = "q_control2 != NO_QUBIT")]
fn test_op_validate_hmr_invalid_q_control2() {
    let mut op = Op::empty();
    op.kind = OperationType::Hmr;
    op.q_target = QubitId(1);
    op.c_target = BitId(2);
    op.c_condition = BitId(3);
    op.q_control2 = QubitId(99);
    op.validate();
}

#[test]
#[should_panic(expected = "q_control1 != NO_QUBIT")]
fn test_op_validate_hmr_invalid_q_control1() {
    let mut op = Op::empty();
    op.kind = OperationType::Hmr;
    op.q_target = QubitId(1);
    op.c_target = BitId(2);
    op.c_condition = BitId(3);
    op.q_control1 = QubitId(99);
    op.validate();
}

#[test]
#[should_panic(expected = "c_target != NO_BIT")]
fn test_op_validate_x_invalid_c_target() {
    let mut op = Op::empty();
    op.kind = OperationType::X;
    op.q_target = QubitId(1);
    op.c_target = BitId(99);
    op.validate();
}

#[test]
#[should_panic(expected = "q_target != NO_QUBIT")]
fn test_op_validate_neg_invalid_q_target() {
    let mut op = Op::empty();
    op.kind = OperationType::Neg;
    op.q_target = QubitId(99);
    op.validate();
}

#[test]
fn test_op_validate_reversible_cx_valid() {
    let mut op = Op::empty();
    op.kind = OperationType::CX;
    op.q_control1 = QubitId(1);
    op.q_target = QubitId(2);
    op.validate();
}

#[test]
#[should_panic(expected = "q_target==q_control1")]
fn test_op_validate_reversible_cx_aliasing() {
    let mut op = Op::empty();
    op.kind = OperationType::CX;
    op.q_control1 = QubitId(1);
    op.q_target = QubitId(1);
    op.validate();
}

#[test]
fn test_op_validate_reversible_ccx_valid() {
    let mut op = Op::empty();
    op.kind = OperationType::CCX;
    op.q_control2 = QubitId(2);
    op.q_control1 = QubitId(1);
    op.q_target = QubitId(3);
    op.validate();
}

#[test]
#[should_panic(expected = "q_target==q_control1")]
fn test_op_validate_reversible_ccx_aliasing_target_control1() {
    let mut op = Op::empty();
    op.kind = OperationType::CCX;
    op.q_control2 = QubitId(2);
    op.q_control1 = QubitId(1);
    op.q_target = QubitId(1);
    op.validate();
}

#[test]
#[should_panic(expected = "q_target==q_control2")]
fn test_op_validate_reversible_ccx_aliasing_target_control2() {
    let mut op = Op::empty();
    op.kind = OperationType::CCX;
    op.q_control2 = QubitId(2);
    op.q_control1 = QubitId(1);
    op.q_target = QubitId(2);
    op.validate();
}

#[test]
#[should_panic(expected = "q_control1==q_control2")]
fn test_op_validate_reversible_ccx_aliasing_controls() {
    let mut op = Op::empty();
    op.kind = OperationType::CCX;
    op.q_control2 = QubitId(1);
    op.q_control1 = QubitId(1);
    op.q_target = QubitId(3);
    op.validate();
}

#[test]
fn test_op_validate_reversible_bit_invert_valid() {
    let mut op = Op::empty();
    op.kind = OperationType::BitInvert;
    op.c_target = BitId(1);
    op.c_condition = BitId(1);
    op.validate();
}

#[test]
fn test_op_from_text_empty() {
    assert_eq!(Op::from_text(""), None);
    assert_eq!(Op::from_text("      # test"), None);
}

#[test]
fn test_op_from_text_ccx() {
    let op = Op::from_text("CCX q0 q1 q2 if b3").unwrap();
    assert_eq!(op.kind, OperationType::CCX);
    assert_eq!(op.q_control2, QubitId(0));
    assert_eq!(op.q_control1, QubitId(1));
    assert_eq!(op.q_target, QubitId(2));
    assert_eq!(op.c_condition, BitId(3));
    assert_eq!(op.c_target, NO_BIT);
    assert_eq!(op.r_target, NO_REG);
}

#[test]
fn test_op_from_text_hmr() {
    let op = Op::from_text("HMR q1 b2 if b3").unwrap();
    assert_eq!(op.kind, OperationType::Hmr);
    assert_eq!(op.q_target, QubitId(1));
    assert_eq!(op.c_target, BitId(2));
    assert_eq!(op.c_condition, BitId(3));
    assert_eq!(op.q_control2, NO_QUBIT);
    assert_eq!(op.q_control1, NO_QUBIT);
    assert_eq!(op.r_target, NO_REG);
}

#[test]
fn test_op_from_text_x() {
    let op = Op::from_text("X q1").unwrap();
    assert_eq!(op.kind, OperationType::X);
    assert_eq!(op.q_target, QubitId(1));
    assert_eq!(op.c_condition, NO_BIT);
}

#[test]
fn test_op_from_text_neg() {
    let op = Op::from_text("NEG").unwrap();
    assert_eq!(op.kind, OperationType::Neg);
    assert_eq!(op.c_condition, NO_BIT);
}

#[test]
fn test_op_from_text_neg_if() {
    let op = Op::from_text("NEG if b0").unwrap();
    assert_eq!(op.kind, OperationType::Neg);
    assert_eq!(op.c_condition, BitId(0));
}

#[test]
fn test_op_from_text_neg_if_whitespace() {
    let op = Op::from_text("   NEG   if   b0  # comment").unwrap();
    assert_eq!(op.kind, OperationType::Neg);
    assert_eq!(op.c_condition, BitId(0));
}

#[test]
fn test_op_from_text_append_to_register() {
    let op = Op::from_text("APPEND_TO_REGISTER q2 r1").unwrap();
    assert_eq!(op.kind, OperationType::AppendToRegister);
    assert_eq!(op.q_target, QubitId(2));
    assert_eq!(op.r_target, RegisterId(1));
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_neg_b0() {
    Op::from_text("NEG b0");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_cx_b0() {
    Op::from_text("CX b0");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_hmr_b0() {
    Op::from_text("HMR b0");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_hmr_b0_b0() {
    Op::from_text("HMR b0 b0");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_hmr_0_b0() {
    Op::from_text("HMR 0 b0");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_hmr_q0_q1() {
    Op::from_text("HMR q0 q1");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_hmr_q0_mx() {
    Op::from_text("HMR q0 MX");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_cx_cx() {
    Op::from_text("CX CX");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_test() {
    Op::from_text("test");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_ccx_q0() {
    Op::from_text("CCX q0");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_nop_q0() {
    Op::from_text("NOP q0");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_ccx_q0_q1() {
    Op::from_text("CCX q0 q1");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_ccx_q0_q1_b2() {
    Op::from_text("CCX q0 q1 b2");
}

#[test]
#[should_panic]
fn test_op_from_text_invalid_multiple_lines() {
    Op::from_text("CCX q0 q1 q2\nCX q0 q1");
}
