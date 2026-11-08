//! Scope policy: which directories a project may touch, and at which level.
//!
//! Path safety model:
//! 1. requested paths must be absolute,
//! 2. `.` / `..` components are rejected outright (defense in depth),
//! 3. the path is canonicalized — for a not-yet-existing leaf (e.g. a file
//!    about to be created) the deepest existing ancestor is canonicalized
//!    and the remaining plain components are re-appended,
//! 4. the canonical result must be inside a canonical granted root.
//!
//! Because canonicalization resolves symlinks, a symlink inside a granted
//! scope that points outside of it resolves outside and is denied.

use std::collections::{HashMap, HashSet};
use std::path::{Component, Path, PathBuf};

use serde::{Deserialize, Serialize};

/// Permission levels a user can grant to a project scope.
///
/// v0 only brokers filesystem operations; `Administration` and `Automatic`
/// will additionally gate shell/network/deploy capabilities and the
/// "act without asking" mode in later phases.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PermissionLevel {
    /// Read and list only. Writes are always denied.
    ReadOnly,
    /// Read/write inside the granted scope (the default for coding work).
    Development,
    /// Development plus privileged operations (introduced in later phases).
    Administration,
    /// Like Administration, without per-action confirmation prompts.
    Automatic,
}

/// Classes of privileged filesystem operations brokered in v0.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Operation {
    Read,
    List,
    Write,
}

impl Operation {
    pub fn as_str(self) -> &'static str {
        match self {
            Operation::Read => "fs_read",
            Operation::List => "fs_list",
            Operation::Write => "fs_write",
        }
    }
}

impl PermissionLevel {
    /// Whether this level allows the given operation class.
    pub fn allows(self, op: Operation) -> bool {
        match op {
            Operation::Read | Operation::List => true,
            Operation::Write => !matches!(self, PermissionLevel::ReadOnly),
        }
    }
}

/// A user-granted directory scope for one project.
#[derive(Clone, Debug)]
pub struct ScopeGrant {
    /// Canonicalized root directory (canonicalized at grant time).
    pub root: PathBuf,
    pub level: PermissionLevel,
}

#[derive(Debug, thiserror::Error)]
pub enum PolicyError {
    #[error("path must be absolute: `{0}`")]
    RelativePath(String),
    #[error("path traversal components (`.`/`..`) are rejected: `{0}`")]
    Traversal(String),
    #[error("path could not be resolved: `{path}`: {source}")]
    Resolve {
        path: String,
        source: std::io::Error,
    },
    #[error("no directory scope has been granted to project `{0}`")]
    NoGrants(String),
    #[error("path is outside every scope granted to project `{project}`: `{path}`")]
    OutOfScope { project: String, path: String },
    #[error("operation `{op}` is not allowed by the granted permission level for `{path}`")]
    LevelDenied { op: &'static str, path: String },
    #[error("scope root must be an existing directory: `{0}`")]
    NotADirectory(String),
    #[error("a scope can only be granted on a folder chosen in the native picker: `{0}`")]
    NotPicked(String),
    #[error("the path goes through a link whose target does not exist: `{0}`")]
    DanglingLink(String),
}

/// Per-project scope grants. Pure data + logic; no Tauri types, so it is
/// fully unit-testable.
#[derive(Default)]
pub struct Policy {
    grants: HashMap<String, Vec<ScopeGrant>>,
    /// Canonical folders the user chose in the native picker this session.
    picked: HashSet<PathBuf>,
}

impl Policy {
    /// Remember a folder the user chose in the native picker.
    pub fn remember_picked(&mut self, root: &Path) -> Result<PathBuf, PolicyError> {
        let canonical = resolve_strict(root)?;
        self.picked.insert(canonical.clone());
        Ok(canonical)
    }

    /// Grant a scope on behalf of the webview: only on a folder the user
    /// really chose, so a compromised page cannot grant itself the whole disk.
    pub fn grant_picked(
        &mut self,
        project_id: &str,
        root: &Path,
        level: PermissionLevel,
    ) -> Result<PathBuf, PolicyError> {
        let canonical = resolve_strict(root)?;
        if !self.picked.contains(&canonical) {
            return Err(PolicyError::NotPicked(display(&canonical)));
        }
        self.grant(project_id, &canonical, level)
    }

    /// Grant a directory scope to a project. The root must exist and be a
    /// directory; it is stored canonicalized. Granting the same root again
    /// replaces the previous level (so a user can upgrade/downgrade).
    pub fn grant(
        &mut self,
        project_id: &str,
        root: &Path,
        level: PermissionLevel,
    ) -> Result<PathBuf, PolicyError> {
        let canonical = resolve_strict(root)?;
        if !canonical.is_dir() {
            return Err(PolicyError::NotADirectory(display(root)));
        }
        let grants = self.grants.entry(project_id.to_string()).or_default();
        if let Some(existing) = grants.iter_mut().find(|g| g.root == canonical) {
            existing.level = level;
        } else {
            grants.push(ScopeGrant {
                root: canonical.clone(),
                level,
            });
        }
        Ok(canonical)
    }

    /// Check `op` on `path` for `project_id`.
    ///
    /// Returns the canonicalized path the caller must use for the actual
    /// I/O (never the raw request), or a denial. Deny by default.
    pub fn check(
        &self,
        project_id: &str,
        path: &Path,
        op: Operation,
    ) -> Result<PathBuf, PolicyError> {
        let grants = self
            .grants
            .get(project_id)
            .filter(|g| !g.is_empty())
            .ok_or_else(|| PolicyError::NoGrants(project_id.to_string()))?;

        let canonical = resolve_lenient(path)?;

        // The most specific grant decides: a read-only folder nested in a
        // writable one stays read-only.
        let closest = grants
            .iter()
            .filter(|grant| canonical.starts_with(&grant.root))
            .max_by_key(|grant| grant.root.components().count());
        match closest {
            Some(grant) if grant.level.allows(op) => Ok(canonical),
            Some(_) => Err(PolicyError::LevelDenied {
                op: op.as_str(),
                path: display(&canonical),
            }),
            None => Err(PolicyError::OutOfScope {
                project: project_id.to_string(),
                path: display(&canonical),
            }),
        }
    }

    /// Grants currently held by a project (canonical roots + levels).
    pub fn grants_for(&self, project_id: &str) -> Vec<ScopeGrant> {
        self.grants.get(project_id).cloned().unwrap_or_default()
    }
}

fn display(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

/// Lexical screening shared by both resolvers: absolute, and free of
/// `.` / `..` components.
fn screen(path: &Path) -> Result<(), PolicyError> {
    if !path.is_absolute() {
        return Err(PolicyError::RelativePath(display(path)));
    }
    if path
        .components()
        .any(|c| matches!(c, Component::ParentDir | Component::CurDir))
    {
        return Err(PolicyError::Traversal(display(path)));
    }
    Ok(())
}

/// Canonicalize a path that must already exist (scope roots).
fn resolve_strict(path: &Path) -> Result<PathBuf, PolicyError> {
    screen(path)?;
    path.canonicalize().map_err(|source| PolicyError::Resolve {
        path: display(path),
        source,
    })
}

/// Canonicalize a request path, tolerating a not-yet-existing tail
/// (e.g. `fs_write` creating a new file): the deepest existing ancestor is
/// canonicalized (resolving symlinks) and the remaining plain components
/// are appended.
fn resolve_lenient(path: &Path) -> Result<PathBuf, PolicyError> {
    screen(path)?;

    if let Ok(canonical) = path.canonicalize() {
        return Ok(canonical);
    }

    let mut existing: &Path = path;
    let mut tail: Vec<std::ffi::OsString> = Vec::new();
    loop {
        // `symlink_metadata`, not `exists()`: a link whose target is missing
        // "does not exist" for `exists()`, yet writing through it creates the
        // file wherever it points, possibly outside every scope.
        match std::fs::symlink_metadata(existing) {
            Ok(metadata) => {
                if metadata.file_type().is_symlink() && existing.canonicalize().is_err() {
                    return Err(PolicyError::DanglingLink(display(existing)));
                }
                break;
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(source) => {
                return Err(PolicyError::Resolve {
                    path: display(path),
                    source,
                })
            }
        }
        let (Some(parent), Some(name)) = (existing.parent(), existing.file_name()) else {
            // Walked up to the filesystem root without finding anything
            // that exists — treat as unresolvable.
            return Err(PolicyError::Resolve {
                path: display(path),
                source: std::io::Error::new(std::io::ErrorKind::NotFound, "no existing ancestor"),
            });
        };
        tail.push(name.to_os_string());
        existing = parent;
    }

    let mut canonical = existing
        .canonicalize()
        .map_err(|source| PolicyError::Resolve {
            path: display(path),
            source,
        })?;
    for name in tail.into_iter().rev() {
        canonical.push(name);
    }
    Ok(canonical)
}

#[cfg(all(test, windows))]
pub(crate) mod test_support {
    use std::path::Path;
    use std::process::Command;

    /// Create a directory junction (no privilege needed, unlike a symlink).
    pub(crate) fn junction(target: &Path, link: &Path) {
        let status = Command::new("cmd")
            .arg("/C")
            .arg("mklink")
            .arg("/J")
            .arg(strip_verbatim(link))
            .arg(strip_verbatim(target))
            .output()
            .expect("run mklink");
        assert!(status.status.success(), "mklink failed: {status:?}");
    }

    fn strip_verbatim(path: &Path) -> String {
        path.to_string_lossy()
            .trim_start_matches(r"\\?\")
            .to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tempdir() -> tempfile::TempDir {
        tempfile::tempdir().expect("create tempdir")
    }

    #[test]
    fn a_nested_read_only_grant_is_not_overridden_by_its_parent() {
        let mut policy = Policy::default();
        let root = tempdir();
        let locked = root.path().join("locked");
        std::fs::create_dir(&locked).unwrap();
        policy
            .grant("p1", root.path(), PermissionLevel::Development)
            .unwrap();
        policy
            .grant("p1", &locked, PermissionLevel::ReadOnly)
            .unwrap();

        let err = policy
            .check("p1", &locked.join("a.txt"), Operation::Write)
            .unwrap_err();
        assert!(matches!(err, PolicyError::LevelDenied { .. }));
        assert!(policy
            .check("p1", &root.path().join("a.txt"), Operation::Write)
            .is_ok());
    }

    #[test]
    fn a_nested_writable_grant_opens_only_that_folder() {
        let mut policy = Policy::default();
        let root = tempdir();
        let open = root.path().join("open");
        std::fs::create_dir(&open).unwrap();
        policy
            .grant("p1", root.path(), PermissionLevel::ReadOnly)
            .unwrap();
        policy
            .grant("p1", &open, PermissionLevel::Development)
            .unwrap();
        assert!(policy
            .check("p1", &open.join("a.txt"), Operation::Write)
            .is_ok());
        assert!(policy
            .check("p1", &root.path().join("a.txt"), Operation::Write)
            .is_err());
    }

    #[test]
    fn the_webview_can_only_grant_a_folder_the_user_picked() {
        let mut policy = Policy::default();
        let picked = tempdir();
        let other = tempdir();
        policy.remember_picked(picked.path()).unwrap();

        let err = policy
            .grant_picked("p1", other.path(), PermissionLevel::Development)
            .unwrap_err();
        assert!(matches!(err, PolicyError::NotPicked(_)));
        assert!(policy.grants_for("p1").is_empty());

        policy
            .grant_picked("p1", picked.path(), PermissionLevel::Development)
            .unwrap();
        assert_eq!(policy.grants_for("p1").len(), 1);
    }

    #[cfg(unix)]
    #[test]
    fn a_dangling_link_cannot_be_written_through() {
        let mut policy = Policy::default();
        let scope = tempdir();
        let outside = tempdir();
        let link = scope.path().join("planted.txt");
        std::os::unix::fs::symlink(outside.path().join("created.txt"), &link).unwrap();
        policy
            .grant("p1", scope.path(), PermissionLevel::Development)
            .unwrap();
        let err = policy.check("p1", &link, Operation::Write).unwrap_err();
        assert!(matches!(err, PolicyError::DanglingLink(_)));
    }

    #[cfg(windows)]
    #[test]
    fn a_junction_escape_is_denied() {
        let mut policy = Policy::default();
        let scope = tempdir();
        let outside = tempdir();
        std::fs::write(outside.path().join("secret.txt"), b"secret").unwrap();
        let link = scope.path().join("link");
        test_support::junction(outside.path(), &link);
        policy
            .grant("p1", scope.path(), PermissionLevel::Development)
            .unwrap();

        let err = policy
            .check("p1", &link.join("secret.txt"), Operation::Read)
            .unwrap_err();
        assert!(matches!(err, PolicyError::OutOfScope { .. }));
        let err = policy
            .check("p1", &link.join("planted.txt"), Operation::Write)
            .unwrap_err();
        assert!(matches!(err, PolicyError::OutOfScope { .. }));
    }

    #[cfg(windows)]
    #[test]
    fn a_dangling_junction_cannot_be_written_through() {
        let mut policy = Policy::default();
        let scope = tempdir();
        let outside = tempdir();
        let target = outside.path().join("gone");
        std::fs::create_dir(&target).unwrap();
        let link = scope.path().join("link");
        test_support::junction(&target, &link);
        std::fs::remove_dir(&target).unwrap();
        policy
            .grant("p1", scope.path(), PermissionLevel::Development)
            .unwrap();
        let err = policy
            .check("p1", &link.join("new.txt"), Operation::Write)
            .unwrap_err();
        assert!(matches!(err, PolicyError::DanglingLink(_)));
    }

    #[test]
    fn levels_gate_writes_not_reads() {
        for level in [
            PermissionLevel::ReadOnly,
            PermissionLevel::Development,
            PermissionLevel::Administration,
            PermissionLevel::Automatic,
        ] {
            assert!(level.allows(Operation::Read));
            assert!(level.allows(Operation::List));
        }
        assert!(!PermissionLevel::ReadOnly.allows(Operation::Write));
        assert!(PermissionLevel::Development.allows(Operation::Write));
        assert!(PermissionLevel::Administration.allows(Operation::Write));
        assert!(PermissionLevel::Automatic.allows(Operation::Write));
    }

    #[test]
    fn deny_by_default_without_grants() {
        let policy = Policy::default();
        let dir = tempdir();
        let err = policy
            .check("p1", &dir.path().join("a.txt"), Operation::Read)
            .unwrap_err();
        assert!(matches!(err, PolicyError::NoGrants(_)));
    }

    #[test]
    fn relative_paths_are_rejected() {
        let mut policy = Policy::default();
        let dir = tempdir();
        policy
            .grant("p1", dir.path(), PermissionLevel::Development)
            .unwrap();
        let err = policy
            .check("p1", Path::new("src/main.rs"), Operation::Read)
            .unwrap_err();
        assert!(matches!(err, PolicyError::RelativePath(_)));
    }

    #[test]
    fn dotdot_components_are_rejected() {
        let mut policy = Policy::default();
        let dir = tempdir();
        policy
            .grant("p1", dir.path(), PermissionLevel::Development)
            .unwrap();
        let sneaky = dir.path().join("sub").join("..").join("..").join("etc");
        let err = policy.check("p1", &sneaky, Operation::Read).unwrap_err();
        assert!(matches!(err, PolicyError::Traversal(_)));
    }

    #[test]
    fn out_of_scope_is_denied() {
        let mut policy = Policy::default();
        let inside = tempdir();
        let outside = tempdir();
        policy
            .grant("p1", inside.path(), PermissionLevel::Development)
            .unwrap();
        let err = policy
            .check("p1", &outside.path().join("x.txt"), Operation::Read)
            .unwrap_err();
        assert!(matches!(err, PolicyError::OutOfScope { .. }));
    }

    #[test]
    fn write_denied_on_read_only_grant() {
        let mut policy = Policy::default();
        let dir = tempdir();
        policy
            .grant("p1", dir.path(), PermissionLevel::ReadOnly)
            .unwrap();
        let target = dir.path().join("notes.md");
        assert!(policy.check("p1", &target, Operation::Read).is_ok());
        let err = policy.check("p1", &target, Operation::Write).unwrap_err();
        assert!(matches!(err, PolicyError::LevelDenied { .. }));
    }

    #[test]
    fn write_allowed_inside_development_grant_for_new_file() {
        let mut policy = Policy::default();
        let dir = tempdir();
        policy
            .grant("p1", dir.path(), PermissionLevel::Development)
            .unwrap();
        // `new_dir` and `file.txt` do not exist yet: the lenient resolver
        // must still anchor them inside the canonical scope root.
        let target = dir.path().join("new_dir").join("file.txt");
        let resolved = policy.check("p1", &target, Operation::Write).unwrap();
        assert!(resolved.starts_with(dir.path().canonicalize().unwrap()));
    }

    #[test]
    fn grants_are_per_project() {
        let mut policy = Policy::default();
        let dir = tempdir();
        policy
            .grant("p1", dir.path(), PermissionLevel::Development)
            .unwrap();
        let err = policy
            .check("p2", &dir.path().join("a.txt"), Operation::Read)
            .unwrap_err();
        assert!(matches!(err, PolicyError::NoGrants(_)));
    }

    #[test]
    fn regranting_same_root_updates_level() {
        let mut policy = Policy::default();
        let dir = tempdir();
        policy
            .grant("p1", dir.path(), PermissionLevel::ReadOnly)
            .unwrap();
        policy
            .grant("p1", dir.path(), PermissionLevel::Development)
            .unwrap();
        assert_eq!(policy.grants_for("p1").len(), 1);
        assert!(policy
            .check("p1", &dir.path().join("a.txt"), Operation::Write)
            .is_ok());
    }

    #[test]
    fn grant_root_must_be_a_directory() {
        let mut policy = Policy::default();
        let dir = tempdir();
        let file = dir.path().join("not_a_dir.txt");
        std::fs::write(&file, b"x").unwrap();
        let err = policy
            .grant("p1", &file, PermissionLevel::Development)
            .unwrap_err();
        assert!(matches!(err, PolicyError::NotADirectory(_)));
    }

    #[cfg(unix)]
    #[test]
    fn symlink_escape_is_denied() {
        let mut policy = Policy::default();
        let scope = tempdir();
        let outside = tempdir();
        std::fs::write(outside.path().join("secret.txt"), b"secret").unwrap();
        std::os::unix::fs::symlink(outside.path(), scope.path().join("link")).unwrap();
        policy
            .grant("p1", scope.path(), PermissionLevel::Development)
            .unwrap();

        // Existing target through the symlink escapes the scope.
        let via_link = scope.path().join("link").join("secret.txt");
        let err = policy.check("p1", &via_link, Operation::Read).unwrap_err();
        assert!(matches!(err, PolicyError::OutOfScope { .. }));

        // A new file under the symlinked directory would also land outside.
        let new_via_link = scope.path().join("link").join("planted.txt");
        let err = policy
            .check("p1", &new_via_link, Operation::Write)
            .unwrap_err();
        assert!(matches!(err, PolicyError::OutOfScope { .. }));
    }

    #[test]
    fn sibling_prefix_directory_is_not_in_scope() {
        // `/tmp/xyz-extra` must not match a grant on `/tmp/xyz` — the check
        // is component-wise (Path::starts_with), not a string prefix.
        let mut policy = Policy::default();
        let parent = tempdir();
        let root = parent.path().join("proj");
        let sibling = parent.path().join("proj-extra");
        std::fs::create_dir_all(&root).unwrap();
        std::fs::create_dir_all(&sibling).unwrap();
        policy
            .grant("p1", &root, PermissionLevel::Development)
            .unwrap();
        let err = policy
            .check("p1", &sibling.join("a.txt"), Operation::Read)
            .unwrap_err();
        assert!(matches!(err, PolicyError::OutOfScope { .. }));
    }
}
