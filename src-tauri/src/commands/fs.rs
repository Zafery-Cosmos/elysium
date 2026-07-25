//! Filesystem IPC commands, all routed through the permission broker.
//!
//! `pick_directory` is the only command that shows UI (the native folder
//! picker). The `fs_*` commands are policy-checked against the scopes the
//! user granted via `fs_scope_grant` and audited — allow *and* deny.

use std::path::{Path, PathBuf};

use serde::Serialize;
use tauri::{AppHandle, State};
use tauri_plugin_dialog::DialogExt;

use crate::security::audit::{now_ms, AuditEntry, Decision};
use crate::security::policy::{Operation, PermissionLevel};
use crate::security::SecurityState;
use crate::Error;

/// One entry returned by `fs_list`.
#[derive(Debug, Serialize)]
pub struct FsEntry {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
    /// File size in bytes; `None` for directories or unreadable metadata.
    pub size: Option<u64>,
}

/// Open the native folder picker. Returns the chosen absolute path, or
/// `None` if the user cancelled. Picking a folder does **not** grant any
/// scope — the frontend must follow up with `fs_scope_grant`.
#[tauri::command]
pub async fn pick_directory(app: AppHandle) -> Result<Option<String>, Error> {
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog().file().blocking_pick_folder()
    })
    .await
    .map_err(|e| Error::Dialog(e.to_string()))?;

    match picked {
        Some(file_path) => {
            let path = file_path
                .into_path()
                .map_err(|e| Error::Dialog(e.to_string()))?;
            Ok(Some(path.to_string_lossy().into_owned()))
        }
        None => Ok(None),
    }
}

/// Grant a directory scope (with a permission level) to a project.
/// Returns the canonical root that was actually stored.
#[tauri::command]
pub fn fs_scope_grant(
    state: State<'_, SecurityState>,
    project_id: String,
    path: String,
    level: PermissionLevel,
) -> Result<String, Error> {
    let requested = PathBuf::from(&path);
    let result = {
        let mut policy = state
            .policy
            .lock()
            .map_err(|_| Error::Internal("policy lock poisoned".into()))?;
        policy.grant(&project_id, &requested, level)
    };

    match result {
        Ok(canonical) => {
            let canonical_str = canonical.to_string_lossy().into_owned();
            let detail = format!("level={level:?}");
            record_or_fail(
                &state,
                &project_id,
                "scope_grant",
                Some(&canonical_str),
                Decision::Allow,
                Some(&detail),
            )?;
            Ok(canonical_str)
        }
        Err(err) => {
            record_denial(&state, &project_id, "scope_grant", &path, &err.to_string());
            Err(Error::PermissionDenied(err))
        }
    }
}

/// Read a UTF-8 text file inside a granted scope.
#[tauri::command]
pub fn fs_read(
    state: State<'_, SecurityState>,
    project_id: String,
    path: String,
) -> Result<String, Error> {
    let canonical = authorize(&state, &project_id, Path::new(&path), Operation::Read)?;
    Ok(std::fs::read_to_string(canonical)?)
}

/// Write a UTF-8 text file inside a granted scope. Denied by default for
/// any path outside a granted scope or under a `ReadOnly` grant. Missing
/// parent directories inside the scope are created.
#[tauri::command]
pub fn fs_write(
    state: State<'_, SecurityState>,
    project_id: String,
    path: String,
    contents: String,
) -> Result<(), Error> {
    let canonical = authorize(&state, &project_id, Path::new(&path), Operation::Write)?;
    if let Some(parent) = canonical.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(canonical, contents)?;
    Ok(())
}

/// List a directory inside a granted scope (non-recursive).
#[tauri::command]
pub fn fs_list(
    state: State<'_, SecurityState>,
    project_id: String,
    path: String,
) -> Result<Vec<FsEntry>, Error> {
    let canonical = authorize(&state, &project_id, Path::new(&path), Operation::List)?;
    let mut entries = Vec::new();
    for entry in std::fs::read_dir(canonical)? {
        let entry = entry?;
        let metadata = entry.metadata().ok();
        let is_dir = metadata.as_ref().map(|m| m.is_dir()).unwrap_or(false);
        entries.push(FsEntry {
            name: entry.file_name().to_string_lossy().into_owned(),
            path: entry.path().to_string_lossy().into_owned(),
            is_dir,
            size: metadata.and_then(|m| if m.is_file() { Some(m.len()) } else { None }),
        });
    }
    // Directories first, then case-sensitive by name.
    entries.sort_by(|a, b| b.is_dir.cmp(&a.is_dir).then_with(|| a.name.cmp(&b.name)));
    Ok(entries)
}

/// Policy-check one operation and audit the decision.
///
/// Allowed operations fail closed if the audit entry cannot be written;
/// denials are returned even if their audit write fails (denying is safe).
fn authorize(
    state: &SecurityState,
    project_id: &str,
    path: &Path,
    op: Operation,
) -> Result<PathBuf, Error> {
    let result = {
        let policy = state
            .policy
            .lock()
            .map_err(|_| Error::Internal("policy lock poisoned".into()))?;
        policy.check(project_id, path, op)
    };

    match result {
        Ok(canonical) => {
            let canonical_str = canonical.to_string_lossy().into_owned();
            record_or_fail(
                state,
                project_id,
                op.as_str(),
                Some(&canonical_str),
                Decision::Allow,
                None,
            )?;
            Ok(canonical)
        }
        Err(err) => {
            record_denial(
                state,
                project_id,
                op.as_str(),
                &path.to_string_lossy(),
                &err.to_string(),
            );
            Err(Error::PermissionDenied(err))
        }
    }
}

fn record_or_fail(
    state: &SecurityState,
    project: &str,
    action: &str,
    path: Option<&str>,
    decision: Decision,
    detail: Option<&str>,
) -> Result<(), Error> {
    state
        .audit
        .record(&AuditEntry {
            ts_ms: now_ms(),
            project,
            action,
            path,
            decision,
            detail,
        })
        .map_err(|e| Error::Audit(e.to_string()))
}

fn record_denial(state: &SecurityState, project: &str, action: &str, path: &str, detail: &str) {
    // Denying is always safe, so a failed audit write must not turn a
    // denial into a different error; log it to stderr instead.
    if let Err(e) = state.audit.record(&AuditEntry {
        ts_ms: now_ms(),
        project,
        action,
        path: Some(path),
        decision: Decision::Deny,
        detail: Some(detail),
    }) {
        eprintln!("[elysium] failed to audit denial: {e}");
    }
}
