//! Engine process supervisor: spawn → health-poll → watch → restart.

use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use tokio::process::Command;

use super::{EngineState, Shared};
use crate::Error;

/// Give the engine up to this long to answer `/health` after spawning.
const HEALTH_DEADLINE: Duration = Duration::from_secs(30);
/// Delay between two health probes.
const HEALTH_PROBE_INTERVAL: Duration = Duration::from_millis(250);
/// Poll interval while watching a healthy child for exit.
const CHILD_WATCH_INTERVAL: Duration = Duration::from_millis(500);
/// Restart backoff bounds.
const BACKOFF_INITIAL: Duration = Duration::from_secs(1);
const BACKOFF_MAX: Duration = Duration::from_secs(30);

pub(crate) struct Supervisor {
    port: u16,
    token: String,
    shared: Arc<Shared>,
}

impl Supervisor {
    pub(crate) fn new(port: u16, token: String, shared: Arc<Shared>) -> Self {
        Self {
            port,
            token,
            shared,
        }
    }

    pub(crate) async fn run(self) {
        let mut backoff = BACKOFF_INITIAL;
        loop {
            if self.shared.shutting_down.load(Ordering::SeqCst) {
                self.shared.set_state(EngineState::Stopped);
                return;
            }

            self.shared.set_state(EngineState::Starting);
            match self.spawn_once().await {
                Ok(became_healthy) => {
                    if became_healthy {
                        // Ran fine for a while; restart promptly next time.
                        backoff = BACKOFF_INITIAL;
                    }
                }
                Err(err) => {
                    self.shared
                        .push_stderr_line(format!("[supervisor] spawn failed: {err}"));
                }
            }

            if self.shared.shutting_down.load(Ordering::SeqCst) {
                self.shared.set_state(EngineState::Stopped);
                return;
            }

            self.shared.set_state(EngineState::Failed);
            self.shared.restarts.fetch_add(1, Ordering::Relaxed);
            self.shared.push_stderr_line(format!(
                "[supervisor] engine exited; restarting in {}s",
                backoff.as_secs()
            ));
            tokio::time::sleep(backoff).await;
            backoff = (backoff * 2).min(BACKOFF_MAX);
        }
    }

    /// Spawn the engine once and watch it until it exits.
    /// Returns `Ok(true)` if it became healthy before dying.
    async fn spawn_once(&self) -> Result<bool, Error> {
        let mut command = build_command()?;
        command
            .env("ELYSIUM_TOKEN", &self.token)
            .env("ELYSIUM_PORT", self.port.to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .kill_on_drop(true);

        let mut child = command
            .spawn()
            .map_err(|e| Error::EngineSpawn(e.to_string()))?;

        // Stream stderr into the bounded tail buffer.
        if let Some(stderr) = child.stderr.take() {
            let shared = Arc::clone(&self.shared);
            tauri::async_runtime::spawn(async move {
                let mut lines = BufReader::new(stderr).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    shared.push_stderr_line(line);
                }
            });
        }

        // Park the child where `Engine::shutdown` can reach it, then watch
        // it via `try_wait` so we never hold the lock across an await.
        if let Ok(mut slot) = self.shared.child.lock() {
            *slot = Some(child);
        }

        let became_healthy = self.poll_health().await;
        if became_healthy {
            self.shared.set_state(EngineState::Running);
        } else {
            self.shared
                .push_stderr_line("[supervisor] engine never answered /health".into());
            self.kill_child();
        }

        // Watch for exit (or for shutdown).
        loop {
            if self.shared.shutting_down.load(Ordering::SeqCst) {
                self.kill_child();
                return Ok(became_healthy);
            }
            let exited = match self.shared.child.lock() {
                Ok(mut slot) => match slot.as_mut() {
                    Some(child) => match child.try_wait() {
                        Ok(Some(status)) => {
                            self.shared.push_stderr_line(format!(
                                "[supervisor] engine process exited: {status}"
                            ));
                            *slot = None;
                            true
                        }
                        Ok(None) => false,
                        Err(e) => {
                            self.shared
                                .push_stderr_line(format!("[supervisor] wait error: {e}"));
                            *slot = None;
                            true
                        }
                    },
                    None => true,
                },
                Err(_) => true,
            };
            if exited {
                return Ok(became_healthy);
            }
            tokio::time::sleep(CHILD_WATCH_INTERVAL).await;
        }
    }

    fn kill_child(&self) {
        if let Ok(mut slot) = self.shared.child.lock() {
            if let Some(child) = slot.as_mut() {
                let _ = child.start_kill();
            }
        }
    }

    /// Probe `/health` until it answers 200 or the deadline passes.
    async fn poll_health(&self) -> bool {
        let deadline = tokio::time::Instant::now() + HEALTH_DEADLINE;
        while tokio::time::Instant::now() < deadline {
            if self.shared.shutting_down.load(Ordering::SeqCst) {
                return false;
            }
            if probe_health(self.port, &self.token).await {
                return true;
            }
            // Stop early if the process already died.
            if let Ok(mut slot) = self.shared.child.lock() {
                match slot.as_mut() {
                    Some(child) => {
                        if matches!(child.try_wait(), Ok(Some(_))) {
                            return false;
                        }
                    }
                    None => return false,
                }
            }
            tokio::time::sleep(HEALTH_PROBE_INTERVAL).await;
        }
        false
    }
}

/// One minimal HTTP/1.1 request to `/health`, no HTTP client dependency.
async fn probe_health(port: u16, token: &str) -> bool {
    let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)).await else {
        return false;
    };
    let request = format!(
        "GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nAccept: application/json\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).await.is_err() {
        return false;
    }
    let mut response = Vec::with_capacity(512);
    if tokio::time::timeout(Duration::from_secs(2), stream.read_to_end(&mut response))
        .await
        .is_err()
    {
        return false;
    }
    let head = String::from_utf8_lossy(&response);
    head.starts_with("HTTP/1.1 200") || head.starts_with("HTTP/1.0 200")
}

/// Locate what to run.
///
/// Debug builds: `python -m elysium_engine` from `<repo>/ai-engine`,
/// preferring the project virtualenv. Release builds: the PyInstaller
/// sidecar bundled next to the app executable (see
/// `tauri.conf.json` → `bundle.externalBin`).
fn build_command() -> Result<Command, Error> {
    if cfg!(debug_assertions) {
        let engine_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(|repo_root| repo_root.join("ai-engine"))
            .ok_or_else(|| Error::EngineSpawn("cannot locate repository root".into()))?;

        let venv_python = if cfg!(windows) {
            engine_dir.join(".venv").join("Scripts").join("python.exe")
        } else {
            engine_dir.join(".venv").join("bin").join("python")
        };
        let python = if venv_python.exists() {
            venv_python
        } else {
            PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
        };

        let mut command = Command::new(python);
        command
            .arg("-m")
            .arg("elysium_engine")
            .current_dir(&engine_dir);
        Ok(command)
    } else {
        let exe = std::env::current_exe().map_err(|e| Error::EngineSpawn(e.to_string()))?;
        let dir = exe
            .parent()
            .ok_or_else(|| Error::EngineSpawn("executable has no parent directory".into()))?;
        let name = if cfg!(windows) {
            "elysium-engine.exe"
        } else {
            "elysium-engine"
        };
        let sidecar = dir.join(name);
        if !sidecar.exists() {
            return Err(Error::EngineSpawn(format!(
                "bundled engine binary not found at {}",
                sidecar.display()
            )));
        }
        Ok(Command::new(sidecar))
    }
}
