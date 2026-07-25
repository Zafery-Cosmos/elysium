# Security Policy

Elysium's security model is central to the product: agents act on a user's
machine, so every privileged operation is brokered, scoped and audited. The
threat model and design (permission broker, sidecar isolation, prompt
injection stance, secrets handling) live in
[`docs/SECURITY.md`](docs/SECURITY.md).

## Supported versions

Elysium is in early development (v0.1 foundation). Only the latest `main`
and the most recent release receive security fixes.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub
issues, discussions or pull requests.**

Instead, use one of:

- **GitHub private vulnerability reporting** (preferred): *Security* tab →
  *Report a vulnerability* on the repository.
- Email the maintainers at `security@elysium.dev` (PGP available on request).

Include as much of the following as you can:

- affected component (`frontend`, `src-tauri`, `ai-engine`, packaging),
- reproduction steps or proof of concept,
- impact assessment (what an attacker gains — e.g. filesystem access outside
  a granted scope, token exfiltration, prompt-injection privilege escalation),
- suggested fix if you have one.

## What to expect

- **Acknowledgement** within 72 hours.
- An assessment and, if confirmed, a fix plan within 14 days.
- Credit in the release notes (unless you prefer to stay anonymous).

Please give us a reasonable window to ship a fix before public disclosure.

## Scope notes

Reports we consider especially relevant:

- escaping a granted filesystem scope (path traversal, symlink tricks, TOCTOU),
- accessing the engine's HTTP API without the session bearer token, or from a
  non-loopback origin,
- secrets appearing in plaintext (DB, config, logs, audit entries),
- prompt-injected content causing actions beyond granted capabilities.

Out of scope: vulnerabilities in third-party model providers themselves, and
issues requiring an already-compromised machine.
