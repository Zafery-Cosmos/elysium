//! Elysium Rust core.
//!
//! Responsibilities (see `docs/ARCHITECTURE.md` §2 and ADR-003):
//! - window/application lifecycle (Tauri v2),
//! - spawning and supervising the Python AI engine sidecar,
//! - the permission broker: every privileged operation (filesystem today,
//!   shell/network later) is policy-checked and audit-logged here. The
//!   frontend and the Python engine never touch the OS directly.

pub mod commands;
pub mod engine;
mod error;
pub mod security;

pub use error::Error;

use tauri::Manager;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // --- Permission broker -------------------------------------
            let app_data = app.path().app_data_dir()?;
            std::fs::create_dir_all(&app_data)?;
            let audit = security::audit::AuditLog::open(app_data.join("audit.jsonl"))?;
            app.manage(security::SecurityState::new(audit));

            // --- AI engine sidecar -------------------------------------
            // Generates the session token, picks a free localhost port and
            // starts the supervisor task (spawn, health poll, restart with
            // backoff, stderr capture).
            let engine = engine::Engine::launch()?;
            app.manage(engine);

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::engine::get_engine_endpoint,
            commands::engine::engine_status,
            commands::fs::pick_directory,
            commands::fs::fs_scope_grant,
            commands::fs::fs_read,
            commands::fs::fs_write,
            commands::fs::fs_list,
        ])
        .build(tauri::generate_context!())
        .expect("error while building the Elysium application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                // Make sure the Python sidecar never outlives the app.
                if let Some(engine) = app_handle.try_state::<engine::Engine>() {
                    engine.shutdown();
                }
            }
        });
}
