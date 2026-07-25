# Releasing & auto-update

## Cutting a release
1. Bump `version` in `src-tauri/tauri.conf.json` (and keep it as the single
   source of truth for the app version).
2. Commit, then tag: `git tag vX.Y.Z && git push <remote> vX.Y.Z`.
3. The **Release** workflow (`.github/workflows/release.yml`) fans out across
   Windows / macOS / Linux runners, builds the Python engine into a PyInstaller
   sidecar, bundles the installers, signs the updater artifacts, and drafts a
   GitHub Release with `latest.json` attached.
4. Publish the draft: `gh release edit vX.Y.Z --draft=false --prerelease=false`
   (so `releases/latest` resolves and in-app auto-update can find it).

## In-app auto-update
- Configured in `tauri.conf.json` → `plugins.updater` (endpoint =
  `releases/latest/download/latest.json`, plus the public key) and
  `bundle.createUpdaterArtifacts: true`.
- The frontend `UpdatePrompt` component checks on startup (Tauri only) and, if a
  newer signed version exists, shows an in-app popup to download + install +
  relaunch. No external browser step.
- **Signing keys** (generated once with `pnpm tauri signer generate`):
  - Public key: committed in `tauri.conf.json` (safe to share).
  - Private key + password: stored as GitHub repo secrets
    `TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.
    ⚠️ If lost, existing installs can no longer be updated — keep a backup.
- Auto-update only triggers for versions **newer than the installed one**, so
  it starts working from the *next* release after a user installs vX.Y.Z.
