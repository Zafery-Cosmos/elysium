//! Engine-related IPC commands: `get_engine_endpoint`, `engine_status`.

use std::time::Duration;

use serde::Serialize;
use tauri::State;

use crate::engine::{Engine, EngineStatusReport};
use crate::Error;

/// How long `get_engine_endpoint` waits for the sidecar on first call.
const ENDPOINT_WAIT: Duration = Duration::from_secs(45);

#[derive(Debug, Serialize)]
pub struct EngineEndpoint {
    pub port: u16,
    pub token: String,
}

/// Returns `{ port, token }` once the sidecar answers `/health`.
///
/// The token never appears in config files or logs; it only travels over
/// Tauri IPC to the frontend, which uses it as a bearer token against
/// `http://127.0.0.1:<port>`.
#[tauri::command]
pub async fn get_engine_endpoint(engine: State<'_, Engine>) -> Result<EngineEndpoint, Error> {
    engine.wait_until_ready(ENDPOINT_WAIT).await?;
    Ok(EngineEndpoint {
        port: engine.port(),
        token: engine.token().to_string(),
    })
}

/// Current sidecar state: `starting` / `running` / `failed` / `stopped`,
/// restart count and the last stderr lines for diagnostics.
#[tauri::command]
pub fn engine_status(engine: State<'_, Engine>) -> EngineStatusReport {
    engine.status()
}
