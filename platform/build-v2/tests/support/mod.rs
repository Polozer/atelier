//! Test-only build-v2 judgement harness.
//!
//! The oracle owns its fixture inputs, selection, identity rules and expected run sets. It is
//! included directly by integration tests and is not part of the library API.
pub mod adapter;
pub mod check;
pub mod model;
pub mod random;
pub mod snapshot;
pub mod spec;
pub mod work;
