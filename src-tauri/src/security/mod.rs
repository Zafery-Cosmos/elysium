//! Permission broker (ADR-003).
//!
//! Deny by default: an operation is only allowed if a user-granted scope
//! covers the (canonicalized) path *and* the grant's permission level allows
//! the operation class. Every decision — allow or deny — is written to a
//! JSON-lines audit log in the app data directory.

pub mod audit;
pub mod policy;

use std::sync::Mutex;

use audit::AuditLog;
use policy::Policy;

/// Shared broker state managed by Tauri.
pub struct SecurityState {
    /// Per-project directory scope grants. A `std::sync::Mutex` is fine here:
    /// the critical sections are short and never `.await`.
    pub policy: Mutex<Policy>,
    /// Append-only JSON-lines audit log.
    pub audit: AuditLog,
}

impl SecurityState {
    pub fn new(audit: AuditLog) -> Self {
        Self {
            policy: Mutex::new(Policy::default()),
            audit,
        }
    }
}
