//! Append-only JSON-lines audit log for privileged operations.
//!
//! Every brokered operation — allowed or denied — produces one line in
//! `<app-data>/audit.jsonl`. Privileged commands fail closed if the entry
//! cannot be written (an unauditable action is treated as an unauthorized
//! action).

use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Serialize;

/// Outcome of a brokered operation.
#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Decision {
    Allow,
    Deny,
}

/// One audit record. Serialized as a single JSON line.
#[derive(Debug, Serialize)]
pub struct AuditEntry<'a> {
    /// Milliseconds since the Unix epoch.
    pub ts_ms: u128,
    /// Project the operation was performed for.
    pub project: &'a str,
    /// Operation name (`fs_read`, `fs_write`, `fs_list`, `scope_grant`, …).
    pub action: &'a str,
    /// Path involved, when applicable (canonical when the check passed,
    /// as-requested when it was rejected before resolution).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<&'a str>,
    pub decision: Decision,
    /// Denial reason or extra context (e.g. granted level).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<&'a str>,
}

pub struct AuditLog {
    path: PathBuf,
    file: Mutex<File>,
}

impl AuditLog {
    /// Open (create if needed) the audit log in append mode.
    pub fn open(path: PathBuf) -> std::io::Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let file = OpenOptions::new().create(true).append(true).open(&path)?;
        Ok(Self {
            path,
            file: Mutex::new(file),
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Append one entry. Errors bubble up so callers can fail closed.
    pub fn record(&self, entry: &AuditEntry<'_>) -> std::io::Result<()> {
        let line = serde_json::to_string(entry)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
        let mut file = self
            .file
            .lock()
            .map_err(|_| std::io::Error::new(std::io::ErrorKind::Other, "audit lock poisoned"))?;
        writeln!(file, "{line}")?;
        file.flush()
    }
}

pub fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writes_one_json_line_per_entry() {
        let dir = tempfile::tempdir().unwrap();
        let log = AuditLog::open(dir.path().join("audit.jsonl")).unwrap();
        log.record(&AuditEntry {
            ts_ms: now_ms(),
            project: "p1",
            action: "fs_read",
            path: Some("/tmp/x"),
            decision: Decision::Allow,
            detail: None,
        })
        .unwrap();
        log.record(&AuditEntry {
            ts_ms: now_ms(),
            project: "p1",
            action: "fs_write",
            path: Some("/etc/passwd"),
            decision: Decision::Deny,
            detail: Some("out of scope"),
        })
        .unwrap();

        let contents = std::fs::read_to_string(log.path()).unwrap();
        let lines: Vec<&str> = contents.lines().collect();
        assert_eq!(lines.len(), 2);
        let first: serde_json::Value = serde_json::from_str(lines[0]).unwrap();
        assert_eq!(first["action"], "fs_read");
        assert_eq!(first["decision"], "allow");
        let second: serde_json::Value = serde_json::from_str(lines[1]).unwrap();
        assert_eq!(second["decision"], "deny");
        assert_eq!(second["detail"], "out of scope");
    }
}
