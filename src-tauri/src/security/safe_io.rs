//! File I/O for paths the policy has just approved.
//!
//! The policy decides on a path at one instant; the file system can change
//! before the file is opened (a directory swapped for a link, for instance).
//! So each operation opens first, then proves that the open handle is the very
//! file at the approved location, and only then reads or writes through it.

use std::fs::{File, OpenOptions};
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::path::{Component, Path};

use same_file::Handle;
use sha2::{Digest, Sha256};

/// Folders an agent's proposal can never reach, even inside a granted scope.
const PROTECTED_DIRS: [&str; 8] = [
    ".git",
    ".hg",
    ".svn",
    ".ssh",
    ".aws",
    ".gnupg",
    ".venv",
    "node_modules",
];

/// Refuse to follow a link in the last component where the OS can say so.
/// Windows has no equivalent that keeps cloud placeholders readable: there the
/// check after opening is what rejects a link.
fn no_follow(options: &mut OpenOptions) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW);
    }
    #[cfg(not(unix))]
    let _ = options;
}

/// Prove `file` is what lives at the canonical `path` right now.
fn verified(file: File, path: &Path) -> io::Result<Handle> {
    let opened = Handle::from_file(file)?;
    let current = Handle::from_path(path)?;
    if opened != current || path.canonicalize()? != path {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "the path changed while it was being opened",
        ));
    }
    Ok(opened)
}

/// Read a UTF-8 text file at an already-approved canonical path.
pub fn read_text(path: &Path) -> io::Result<String> {
    let mut options = OpenOptions::new();
    options.read(true);
    no_follow(&mut options);
    let handle = verified(options.open(path)?, path)?;
    let mut text = String::new();
    let mut file = handle.as_file();
    file.read_to_string(&mut text)?;
    Ok(text)
}

/// Replace the contents of the file at an already-approved canonical path.
/// The file is only truncated once it has been verified.
pub fn write_text(path: &Path, contents: &str) -> io::Result<()> {
    let mut options = OpenOptions::new();
    options.write(true).create(true).truncate(false);
    no_follow(&mut options);
    let handle = verified(options.open(path)?, path)?;
    let mut file = handle.as_file();
    file.set_len(0)?;
    file.write_all(contents.as_bytes())?;
    file.flush()
}

/// Whether `path` is a repository internal or a file that usually holds secrets.
pub fn is_protected(path: &Path) -> bool {
    let names: Vec<String> = path
        .components()
        .filter_map(|c| match c {
            Component::Normal(name) => Some(name.to_string_lossy().to_lowercase()),
            _ => None,
        })
        .collect();
    let in_protected_dir = names.iter().any(|name| {
        // Windows ignores trailing dots and spaces: ".git." opens ".git".
        PROTECTED_DIRS.contains(&name.trim_end_matches(['.', ' ']))
    });
    let secret_file = names.last().is_some_and(|name| {
        let is_example = matches!(
            name.as_str(),
            ".env.example" | ".env.sample" | ".env.template"
        );
        !is_example && (name == ".env" || name.starts_with(".env."))
    });
    in_protected_dir || secret_file
}

fn conflict() -> io::Error {
    io::Error::new(
        io::ErrorKind::AlreadyExists,
        "conflict: the file changed since the proposal",
    )
}

fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

/// Apply one reviewed change, only if the file is still what was reviewed.
///
/// `expected` is the SHA-256 the file must have, `None` when it must not exist.
/// `contents` is the new text, `None` to delete the file.
pub fn apply_change(path: &Path, expected: Option<&str>, contents: Option<&str>) -> io::Result<()> {
    let Some(expected) = expected else {
        let Some(contents) = contents else {
            return Err(conflict());
        };
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        no_follow(&mut options);
        let file = match options.open(path) {
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => return Err(conflict()),
            other => other?,
        };
        let handle = verified(file, path)?;
        let mut file = handle.as_file();
        file.write_all(contents.as_bytes())?;
        return file.flush();
    };

    let mut options = OpenOptions::new();
    options.read(true).write(true);
    no_follow(&mut options);
    let file = match options.open(path) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Err(conflict()),
        other => other?,
    };
    let handle = verified(file, path)?;
    let mut file = handle.as_file();
    let mut current = Vec::new();
    file.read_to_end(&mut current)?;
    if !sha256_hex(&current).eq_ignore_ascii_case(expected) {
        return Err(conflict());
    }
    match contents {
        Some(contents) => {
            file.seek(SeekFrom::Start(0))?;
            file.set_len(0)?;
            file.write_all(contents.as_bytes())?;
            file.flush()
        }
        None => {
            // Windows cannot remove a file that is still open.
            drop(handle);
            std::fs::remove_file(path)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(text: &str) -> String {
        sha256_hex(text.as_bytes())
    }

    fn file_in_temp() -> (tempfile::TempDir, std::path::PathBuf) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().canonicalize().unwrap().join("a.txt");
        (dir, path)
    }

    #[test]
    fn creates_only_when_the_file_is_still_absent() {
        let (_dir, path) = file_in_temp();
        apply_change(&path, None, Some("new")).unwrap();
        assert_eq!(read_text(&path).unwrap(), "new");
        let error = apply_change(&path, None, Some("other")).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
        assert_eq!(read_text(&path).unwrap(), "new");
    }

    #[test]
    fn replaces_only_what_was_reviewed_and_truncates() {
        let (_dir, path) = file_in_temp();
        write_text(&path, "a long original").unwrap();
        apply_change(&path, Some(&digest("a long original")), Some("short")).unwrap();
        assert_eq!(read_text(&path).unwrap(), "short");
        let error = apply_change(&path, Some(&digest("stale")), Some("x")).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
        assert_eq!(read_text(&path).unwrap(), "short");
    }

    #[test]
    fn deletes_only_what_was_reviewed() {
        let (_dir, path) = file_in_temp();
        write_text(&path, "x").unwrap();
        assert!(apply_change(&path, Some(&digest("y")), None).is_err());
        assert!(path.exists());
        apply_change(&path, Some(&digest("x")), None).unwrap();
        assert!(!path.exists());
        assert!(apply_change(&path, Some(&digest("x")), None).is_err());
    }

    #[test]
    fn a_change_is_reversible_byte_for_byte() {
        let (_dir, path) = file_in_temp();
        std::fs::write(&path, b"one\r\ntwo\n").unwrap();
        apply_change(&path, Some(&digest("one\r\ntwo\n")), Some("new\n")).unwrap();
        apply_change(&path, Some(&digest("new\n")), Some("one\r\ntwo\n")).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), b"one\r\ntwo\n");
    }

    #[test]
    fn protected_paths() {
        for path in [
            "/p/.git/config",
            "/p/.GIT./hooks/x",
            "/p/.env",
            "/p/api/.env.production",
            "/p/node_modules/a.js",
        ] {
            assert!(is_protected(Path::new(path)), "{path}");
        }
        for path in ["/p/src/a.ts", "/p/.env.example", "/p/.github/ci.yml"] {
            assert!(!is_protected(Path::new(path)), "{path}");
        }
    }

    #[test]
    fn writes_then_reads_back_and_truncates() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().canonicalize().unwrap().join("a.txt");
        write_text(&path, "long content").unwrap();
        write_text(&path, "short").unwrap();
        assert_eq!(read_text(&path).unwrap(), "short");
    }

    #[test]
    fn a_non_canonical_path_is_refused() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().canonicalize().unwrap();
        std::fs::create_dir(root.join("real")).unwrap();
        std::fs::write(root.join("real").join("a.txt"), "x").unwrap();
        let detour = link_dir(&root.join("real"), &root.join("link"));
        assert!(read_text(&detour.join("a.txt")).is_err());
        assert!(write_text(&detour.join("a.txt"), "y").is_err());
        assert_eq!(
            std::fs::read_to_string(root.join("real").join("a.txt")).unwrap(),
            "x"
        );
    }

    #[cfg(unix)]
    fn link_dir(target: &Path, link: &Path) -> std::path::PathBuf {
        std::os::unix::fs::symlink(target, link).unwrap();
        link.to_path_buf()
    }

    /// A junction needs no special privilege, unlike a Windows symlink.
    #[cfg(windows)]
    fn link_dir(target: &Path, link: &Path) -> std::path::PathBuf {
        crate::security::policy::test_support::junction(target, link);
        link.to_path_buf()
    }
}
