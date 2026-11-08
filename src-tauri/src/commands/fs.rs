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
use crate::security::{safe_io, SecurityState};
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
/// scope — the frontend must follow up with `fs_scope_grant`, which only
/// accepts folders that came through here.
#[tauri::command]
pub async fn pick_directory(
    app: AppHandle,
    state: State<'_, SecurityState>,
) -> Result<Option<String>, Error> {
    let picked =
        tauri::async_runtime::spawn_blocking(move || app.dialog().file().blocking_pick_folder())
            .await
            .map_err(|e| Error::Dialog(e.to_string()))?;

    match picked {
        Some(file_path) => {
            let path = file_path
                .into_path()
                .map_err(|e| Error::Dialog(e.to_string()))?;
            state
                .policy
                .lock()
                .map_err(|_| Error::Internal("policy lock poisoned".into()))?
                .remember_picked(&path)?;
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
        policy.grant_picked(&project_id, &requested, level)
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
    Ok(safe_io::read_text(&canonical)?)
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
    // Creating the parents may have gone through a directory swapped in the
    // meantime: decide again now that they exist.
    let recheck = state
        .policy
        .lock()
        .map_err(|_| Error::Internal("policy lock poisoned".into()))?
        .check(&project_id, Path::new(&path), Operation::Write)?;
    if recheck != canonical {
        return Err(Error::Internal(
            "the path changed during the operation".into(),
        ));
    }
    safe_io::write_text(&canonical, &contents)?;
    Ok(())
}

/// Apply a change the user accepted in the review panel.
///
/// The webview only gets here after a human decision. The broker still checks
/// the scope, refuses protected files, and writes only if the file on disk is
/// the one that was reviewed (`expected_sha256`, `None` = must not exist).
#[tauri::command]
pub fn fs_apply_change(
    state: State<'_, SecurityState>,
    project_id: String,
    path: String,
    expected_sha256: Option<String>,
    contents: Option<String>,
) -> Result<(), Error> {
    let requested = Path::new(&path);
    if safe_io::is_protected(requested) {
        record_denial(
            &state,
            &project_id,
            "fs_apply_change",
            &path,
            "protected path",
        );
        return Err(Error::Internal("this file is protected".into()));
    }
    let canonical = authorize(&state, &project_id, requested, Operation::Write)?;
    // A link inside the project must not reach a protected file either.
    if safe_io::is_protected(&canonical) {
        record_denial(
            &state,
            &project_id,
            "fs_apply_change",
            &path,
            "protected path",
        );
        return Err(Error::Internal("this file is protected".into()));
    }
    if contents.is_some() {
        if let Some(parent) = canonical.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let recheck = state
            .policy
            .lock()
            .map_err(|_| Error::Internal("policy lock poisoned".into()))?
            .check(&project_id, requested, Operation::Write)?;
        if recheck != canonical {
            return Err(Error::Internal(
                "the path changed during the operation".into(),
            ));
        }
    }
    safe_io::apply_change(&canonical, expected_sha256.as_deref(), contents.as_deref())?;
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
