//! Application-level error type shared by all IPC commands.
//!
//! Tauri v2 requires command error types to implement `serde::Serialize`;
//! we serialize to a structured `{ kind, message }` object so the frontend
//! can branch on the kind without parsing English prose.

use serde::ser::SerializeStruct;
use serde::{Serialize, Serializer};

use crate::security::policy::PolicyError;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// The permission broker rejected the operation (deny by default).
    #[error("permission denied: {0}")]
    PermissionDenied(#[from] PolicyError),

    /// The AI engine sidecar is not (yet) able to serve requests.
    #[error("engine not ready: {0}")]
    EngineNotReady(String),

    /// The engine sidecar could not be spawned at all.
    #[error("failed to start the AI engine: {0}")]
    EngineSpawn(String),

    /// Recording the audit entry failed; privileged operations fail closed.
    #[error("audit log unavailable: {0}")]
    Audit(String),

    #[error("dialog error: {0}")]
    Dialog(String),

    /// Unexpected internal state (e.g. a poisoned lock).
    #[error("internal error: {0}")]
    Internal(String),

    #[error("i/o error: {0}")]
    Io(#[from] std::io::Error),

    #[error(transparent)]
    Tauri(#[from] tauri::Error),
}

impl Error {
    fn kind(&self) -> &'static str {
        match self {
            Error::PermissionDenied(_) => "permission_denied",
            Error::EngineNotReady(_) => "engine_not_ready",
            Error::EngineSpawn(_) => "engine_spawn",
            Error::Audit(_) => "audit",
            Error::Dialog(_) => "dialog",
            Error::Internal(_) => "internal",
            Error::Io(_) => "io",
            Error::Tauri(_) => "tauri",
        }
    }
}

impl Serialize for Error {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut s = serializer.serialize_struct("Error", 2)?;
        s.serialize_field("kind", self.kind())?;
        s.serialize_field("message", &self.to_string())?;
        s.end()
    }
}
