// HARD RULE: no `unsafe` Rust except for explicitly-approved C FFI.
// Every existing `unsafe` block must be either (a) part of an approved
// FFI call site with a per-site `#[allow(unsafe_code)]` and the call
// site recorded in feedback_no_unsafe.md, or (b) rewritten in safe
// Rust. New unsafe is forbidden without explicit user approval.
#![deny(unsafe_code)]

pub mod circuit;

pub mod arith;
pub mod ec;
pub mod inversion;
pub mod tracker;

// Backwards-compatible re-exports: callers still use
// `circuit_gen::poc_arith`, `crate::mbu_primitives`, etc.
pub use arith::{khattar_gidney, mod_arith, rfold_mbu, schrottenloher};
pub use ec::point_add;
pub use tracker::{debugger, phase_lattice};
