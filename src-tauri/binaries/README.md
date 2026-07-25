# Engine sidecar binaries

Release builds bundle the Python AI engine as a PyInstaller binary declared in
`tauri.conf.json` under `bundle.externalBin` (`binaries/elysium-engine`).

Tauri expects one file per target triple in this directory, for example:

- `elysium-engine-x86_64-unknown-linux-gnu`
- `elysium-engine-aarch64-apple-darwin`
- `elysium-engine-x86_64-pc-windows-msvc.exe`

Build it from `ai-engine/` with PyInstaller, then copy/rename the output here.
In development (`cargo tauri dev` / debug builds) this directory is not used:
the Rust core spawns `python -m elysium_engine` from `ai-engine/` directly,
preferring `ai-engine/.venv` when it exists.

Note: `bundle.externalBin` is intentionally NOT set in tauri.conf.json yet —
Tauri requires the per-target binary to exist at build time, which would break
`pnpm tauri dev` before the PyInstaller sidecar exists. Re-add
`"externalBin": ["binaries/elysium-engine"]` when wiring release packaging.
