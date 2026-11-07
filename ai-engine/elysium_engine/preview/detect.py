"""Identify what kind of web project a folder holds, and how to start it.

Detection is based on manifests and config files only (nothing is executed).
Nothing here accepts a command from the outside: the launch command is built
from a fixed table per framework, plus the project's own ``package.json``
script name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from elysium_engine.preview.paths import PathRefused, resolve_inside

SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", ".nuxt", ".svelte-kit", "__pycache__"}

# framework id -> (label, preferred scripts, hot-update kind)
_FRAMEWORKS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "next": ("Next.js", ("dev", "start"), "hmr"),
    "nuxt": ("Nuxt", ("dev", "start"), "hmr"),
    "astro": ("Astro", ("dev", "start"), "hmr"),
    "sveltekit": ("SvelteKit", ("dev", "start"), "hmr"),
    "angular": ("Angular", ("start", "serve", "dev"), "live-reload"),
    "vue-cli": ("Vue CLI", ("serve", "dev"), "hmr"),
    "cra": ("React (Create React App)", ("start",), "hmr"),
    "vue": ("Vue (Vite)", ("dev", "start"), "hmr"),
    "react-vite": ("React (Vite)", ("dev", "start"), "hmr"),
    "svelte": ("Svelte (Vite)", ("dev", "start"), "hmr"),
    "vite": ("Vite", ("dev", "start"), "hmr"),
    "static": ("HTML / CSS / JavaScript", (), "live-reload"),
}
KNOWN_FRAMEWORKS = frozenset(_FRAMEWORKS)

_VITE_FAMILY = {"vite", "vue", "react-vite", "svelte", "sveltekit"}


@dataclass(slots=True)
class Detection:
    app_root: Path | None = None
    framework: str | None = None
    label: str | None = None
    package_manager: str | None = None
    script: str | None = None
    deps_installed: bool = True
    hot_update: str = "full-reload"
    candidates: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def runnable(self) -> bool:
        return self.error is None and self.framework is not None

    @property
    def is_static(self) -> bool:
        return self.framework == "static"


def _read_package(folder: Path) -> dict | None:
    manifest = folder / "package.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _has_any(folder: Path, *prefixes: str) -> bool:
    try:
        names = [p.name for p in folder.iterdir()]
    except OSError:
        return False
    return any(name.startswith(prefix) for name in names for prefix in prefixes)


def _framework_of(folder: Path, package: dict | None) -> str | None:
    deps: dict = {}
    if package:
        deps.update(package.get("devDependencies") or {})
        deps.update(package.get("dependencies") or {})
    if "next" in deps or _has_any(folder, "next.config."):
        return "next"
    if "nuxt" in deps or "nuxt3" in deps or _has_any(folder, "nuxt.config."):
        return "nuxt"
    if "astro" in deps or _has_any(folder, "astro.config."):
        return "astro"
    if "@sveltejs/kit" in deps:
        return "sveltekit"
    if "@angular/core" in deps or (folder / "angular.json").is_file():
        return "angular"
    if "@vue/cli-service" in deps:
        return "vue-cli"
    if "react-scripts" in deps:
        return "cra"
    if "vite" in deps or _has_any(folder, "vite.config."):
        if "vue" in deps:
            return "vue"
        if "svelte" in deps:
            return "svelte"
        if "react" in deps:
            return "react-vite"
        return "vite"
    if (folder / "index.html").is_file():
        return "static"
    return None


def detect_package_manager(folder: Path, package: dict | None) -> str:
    declared = str((package or {}).get("packageManager", "")).split("@")[0]
    if declared in {"npm", "pnpm", "yarn", "bun"}:
        return declared
    if (folder / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (folder / "yarn.lock").is_file():
        return "yarn"
    if (folder / "bun.lockb").is_file() or (folder / "bun.lock").is_file():
        return "bun"
    return "npm"


def _candidates(root: Path) -> list[Path]:
    found: list[Path] = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return found
    for entry in entries:
        if entry.name in SKIP_DIRS or entry.name.startswith("."):
            continue
        if entry.is_dir() and ((entry / "package.json").is_file() or (entry / "index.html").is_file()):
            found.append(entry)
    return found


def _locate_app_root(root: Path, subdir: str | None) -> tuple[Path | None, list[str], str | None]:
    if subdir:
        try:
            return resolve_inside(root, subdir), [], None
        except PathRefused as exc:
            return None, [], str(exc)
    if (root / "package.json").is_file() or (root / "index.html").is_file():
        return root, [], None
    options = _candidates(root)
    names = [p.name for p in options]
    if len(options) == 1:
        return options[0], names, None
    known = [p for p in options if _framework_of(p, _read_package(p)) not in (None, "static")]
    if len(known) == 1:
        return known[0], names, None
    if not options:
        return None, [], "No package.json or index.html found in this folder."
    return None, names, "Several web apps found: pick one (sub-folder)."


def detect(root: Path, *, subdir: str | None = None, framework: str | None = None) -> Detection:
    """Inspect ``root`` (a validated real path) and describe how to preview it."""
    app_root, names, error = _locate_app_root(root, subdir)
    if app_root is None:
        return Detection(candidates=names, error=error)

    package = _read_package(app_root)
    if package == {} and (app_root / "package.json").is_file():
        return Detection(app_root=app_root, error="package.json is not valid JSON.")

    chosen = framework or _framework_of(app_root, package)
    if framework is not None and framework not in KNOWN_FRAMEWORKS:
        return Detection(app_root=app_root, error=f"Unknown framework '{framework}'.")
    if chosen is None:
        return Detection(
            app_root=app_root,
            candidates=names,
            error="Framework not recognised. Choose it manually.",
        )

    label, scripts_wanted, hot = _FRAMEWORKS[chosen]
    result = Detection(
        app_root=app_root, framework=chosen, label=label, hot_update=hot, candidates=names
    )
    if chosen == "static":
        return result

    result.package_manager = detect_package_manager(app_root, package)
    available = (package or {}).get("scripts") or {}
    result.script = next((s for s in scripts_wanted if s in available), None)
    if result.script is None:
        result.error = (
            f"No {' / '.join(scripts_wanted)} script in package.json to start {label}."
        )
    result.deps_installed = (app_root / "node_modules").is_dir()
    return result


def port_arguments(framework: str, port: int) -> tuple[list[str], dict[str, str]]:
    """Extra CLI arguments and environment that pin host/port for a framework."""
    host = "127.0.0.1"
    if framework in _VITE_FAMILY:
        return ["--port", str(port), "--strictPort", "--host", host], {}
    if framework == "next":
        return ["-p", str(port), "-H", host], {}
    if framework in {"nuxt", "astro", "angular", "vue-cli"}:
        return ["--port", str(port), "--host", host], {}
    if framework == "cra":
        return [], {"PORT": str(port), "HOST": host, "BROWSER": "none"}
    return [], {}


def build_command(package_manager: str, script: str, framework: str, port: int) -> tuple[list[str], dict[str, str]]:
    """argv (no shell) + extra environment that starts ``script`` on ``port``."""
    args, env = port_arguments(framework, port)
    if package_manager == "npm":
        argv = ["npm", "run", script] + (["--", *args] if args else [])
    else:
        argv = [package_manager, "run", script, *args]
    return argv, env


def install_command(package_manager: str) -> list[str]:
    return [package_manager, "install"]
