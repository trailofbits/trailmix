//! Compatibility shim. `poc_arith` was split into purpose modules (`ripple_add`
//! / `compare` / `const_add` / `shift`); this re-exports the two symbols still
//! referenced via the old path by `gcd_jump.rs`.
pub use crate::arith::shift::{left_shift, right_shift};
