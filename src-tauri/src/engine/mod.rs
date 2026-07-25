//! AI engine sidecar lifecycle (ADR-002).
//!
//! The Rust core owns the Python engine process:
//! - generates a per-session bearer token (32 random bytes, hex),
//! - picks a free port on 127.0.0.1,
//! - spawns the engine (dev: `python -m elysium_engine` from `../ai-engine`,
//!   preferring its `.venv`; release: the bundled PyInstaller binary),
//! - polls `GET /health` until the engine answers,
//! - supervises it: keeps the last stderr lines for diagnostics and restarts
//!   with exponential backoff if it dies,
//! - kills it on app exit.

mod supervisor;

use std::collections::VecDeque;
use std::net::TcpListener;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use rand::rngs::OsRng;
use rand::RngCore;
use serde::Serialize;

use crate::Error;

/// How many trailing stderr lines to keep for `engine_status`.
const STDERR_TAIL_LINES: usize = 50;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EngineState {
    /// Process spawned (or about to be), `/health` not confirmed yet.
    Starting,
    /// `/health` answered 200; the endpoint is usable.
    Running,
    /// The process died or never became healthy; the supervisor will retry.
    Failed,
    /// The app is shutting down; no restart will happen.
    Stopped,
}

/// Snapshot returned by the `engine_status` IPC command.
#[derive(Debug, Serialize)]
pub struct EngineStatusReport {
    pub state: EngineState,
    pub port: u16,
    /// Number of times the supervisor restarted the process.
    pub restarts: u32,
    /// Most recent stderr lines (oldest first).
    pub last_stderr: Vec<String>,
}

/// State shared between the public handle and the supervisor task.
pub(crate) struct Shared {
    pub(crate) state: Mutex<EngineState>,
    pub(crate) stderr_tail: Mutex<VecDeque<String>>,
    pub(crate) child: Mutex<Option<tokio::process::Child>>,
    pub(crate) shutting_down: AtomicBool,
    pub(crate) restarts: AtomicU32,
}

impl Shared {
    fn new() -> Self {
        Self {
            state: Mutex::new(EngineState::Starting),
            stderr_tail: Mutex::new(VecDeque::with_capacity(STDERR_TAIL_LINES)),
            child: Mutex::new(None),
            shutting_down: AtomicBool::new(false),
            restarts: AtomicU32::new(0),
        }
    }

    pub(crate) fn set_state(&self, state: EngineState) {
        if let Ok(mut guard) = self.state.lock() {
            *guard = state;
        }
    }

    pub(crate) fn state(&self) -> EngineState {
        self.state.lock().map(|g| *g).unwrap_or(EngineState::Failed)
    }

    pub(crate) fn push_stderr_line(&self, line: String) {
        if let Ok(mut tail) = self.stderr_tail.lock() {
            if tail.len() == STDERR_TAIL_LINES {
                tail.pop_front();
            }
            tail.push_back(line);
        }
    }

    pub(crate) fn stderr_tail(&self) -> Vec<String> {
        self.stderr_tail
            .lock()
            .map(|t| t.iter().cloned().collect())
            .unwrap_or_default()
    }
}

/// Public handle to the supervised engine, managed as Tauri state.
pub struct Engine {
    port: u16,
    token: String,
    shared: Arc<Shared>,
}

impl Engine {
    /// Generate credentials, reserve a port and start the supervisor task.
    /// Returns immediately; readiness is reported via `engine_status` /
    /// awaited by `get_engine_endpoint`.
    pub fn launch() -> Result<Self, Error> {
        let port = pick_free_port()?;
        let token = generate_token();
        let shared = Arc::new(Shared::new());

        let task = supervisor::Supervisor::new(port, token.clone(), Arc::clone(&shared));
        tauri::async_runtime::spawn(async move { task.run().await });

        Ok(Self {
            port,
            token,
            shared,
        })
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn token(&self) -> &str {
        &self.token
    }

    pub fn status(&self) -> EngineStatusReport {
        EngineStatusReport {
            state: self.shared.state(),
            port: self.port,
            restarts: self.shared.restarts.load(Ordering::Relaxed),
            last_stderr: self.shared.stderr_tail(),
        }
    }

    /// Wait until the engine is `Running`, or fail with the stderr tail.
    pub async fn wait_until_ready(&self, timeout: Duration) -> Result<(), Error> {
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            match self.shared.state() {
                EngineState::Running => return Ok(()),
                EngineState::Stopped => {
                    return Err(Error::EngineNotReady("engine was stopped".into()))
                }
                EngineState::Starting | EngineState::Failed => {}
            }
            if tokio::time::Instant::now() >= deadline {
                let tail = self.shared.stderr_tail().join("\n");
                return Err(Error::EngineNotReady(format!(
                    "engine did not become healthy in time; last stderr:\n{tail}"
                )));
            }
            tokio::time::sleep(Duration::from_millis(150)).await;
        }
    }

    /// Stop supervision and kill the child process. Idempotent; callable
    /// from the (synchronous) Tauri exit handler.
    pub fn shutdown(&self) {
        self.shared.shutting_down.store(true, Ordering::SeqCst);
        self.shared.set_state(EngineState::Stopped);
        if let Ok(mut slot) = self.shared.child.lock() {
            if let Some(child) = slot.as_mut() {
                // Best-effort kill; `kill_on_drop(true)` is the safety net.
                kill_tree(child);
            }
            *slot = None;
        }
    }
}

/// Kill a supervised child and, on Unix, its whole process group.
///
/// The engine is spawned as its own process group leader (see
/// `supervisor::build_command`), so this also reaches any process it forked
/// itself — notably a PyInstaller `--onefile` bootloader, which forks the
/// real interpreter and waits on it. Killing only the bootloader's PID would
/// otherwise leave that interpreter running as an orphan after the app
/// exits, which is exactly the leak this guards against.
#[cfg(unix)]
pub(crate) fn kill_tree(child: &mut tokio::process::Child) {
    if let Some(pid) = child.id() {
        // SAFETY: `kill` with a negative pid targets the whole process
        // group; this is a plain libc call with no preconditions beyond a
        // valid signal number, which SIGKILL is.
        unsafe {
            libc::kill(-(pid as i32), libc::SIGKILL);
        }
    }
    let _ = child.start_kill();
}

#[cfg(not(unix))]
pub(crate) fn kill_tree(child: &mut tokio::process::Child) {
    let _ = child.start_kill();
}

/// Ask the OS for a free localhost port.
///
/// Note: the port is released before the sidecar binds it, so a race is
/// theoretically possible; the supervisor treats a bind failure like any
/// other startup failure and retries with a fresh spawn.
fn pick_free_port() -> Result<u16, Error> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    Ok(listener.local_addr()?.port())
}

/// 32 random bytes from the OS CSPRNG, hex-encoded (64 chars).
fn generate_token() -> String {
    let mut bytes = [0u8; 32];
    OsRng.fill_bytes(&mut bytes);
    let mut token = String::with_capacity(64);
    for byte in bytes {
        use std::fmt::Write;
        // Writing to a String cannot fail.
        let _ = write!(token, "{byte:02x}");
    }
    token
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn token_is_64_hex_chars_and_unique() {
        let a = generate_token();
        let b = generate_token();
        assert_eq!(a.len(), 64);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b);
    }

    #[test]
    fn free_port_is_non_zero() {
        let port = pick_free_port().unwrap();
        assert_ne!(port, 0);
    }

    #[test]
    fn stderr_tail_is_bounded() {
        let shared = Shared::new();
        for i in 0..(STDERR_TAIL_LINES + 10) {
            shared.push_stderr_line(format!("line {i}"));
        }
        let tail = shared.stderr_tail();
        assert_eq!(tail.len(), STDERR_TAIL_LINES);
        assert_eq!(
            tail.last().unwrap(),
            &format!("line {}", STDERR_TAIL_LINES + 9)
        );
    }
}
