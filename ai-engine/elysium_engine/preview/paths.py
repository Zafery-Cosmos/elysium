"""Path validation for the preview feature.

The folder comes from the frontend (native picker) so it is never trusted
as-is: it is resolved to its real location (symlinks / junctions followed),
must be an existing directory and must not be a system location, a drive
root or the user's whole home.  Sub-paths are re-checked against the real
root at the point of use.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


class PathRefused(ValueError):
    """The folder is not acceptable for a preview."""


def _system_dirs() -> list[Path]:
    dirs: list[Path] = []
    if sys.platform == "win32":
        for var in ("WINDIR", "SYSTEMROOT", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA"):
            value = os.environ.get(var)
            if value:
                dirs.append(Path(value))
    else:
        # (not /var or /home: web projects legitimately live in /var/www etc.)
        for name in ("/etc", "/usr", "/bin", "/sbin", "/lib", "/proc", "/sys", "/dev", "/boot"):
            dirs.append(Path(name))
    return dirs


def _same_or_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def resolve_root(raw: object, *, forbidden: tuple[Path, ...] = ()) -> Path:
    """Return the real path of ``raw`` or raise :class:`PathRefused`."""
    if not isinstance(raw, str) or not raw.strip():
        raise PathRefused("Folder path is required.")
    if "\x00" in raw:
        raise PathRefused("Invalid folder path.")
    candidate = Path(raw.strip())
    if not candidate.is_absolute():
        raise PathRefused("The folder path must be absolute.")
    try:
        real = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PathRefused(f"Folder not found: {raw}") from exc
    if not real.is_dir():
        raise PathRefused("The path is not a folder.")
    if real == Path(real.anchor):
        raise PathRefused("A drive or filesystem root cannot be previewed.")
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None
    if home is not None and real == home:
        raise PathRefused("Pick the project folder, not your whole home folder.")
    for system in _system_dirs():
        try:
            system = system.resolve()
        except (OSError, RuntimeError):
            continue
        if _same_or_inside(real, system):
            raise PathRefused("System folders cannot be previewed.")
    for blocked in forbidden:
        if _same_or_inside(real, blocked.resolve()):
            raise PathRefused("This folder belongs to Elysium itself.")
    return real


def resolve_inside(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root``; refuse anything that escapes it."""
    if "\x00" in relative:
        raise PathRefused("Invalid sub-folder.")
    rel = Path(relative)
    if rel.is_absolute():
        raise PathRefused("The sub-folder must be relative to the project folder.")
    try:
        real = (root / rel).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PathRefused(f"Sub-folder not found: {relative}") from exc
    if not _same_or_inside(real, root):
        raise PathRefused("The sub-folder is outside the project folder.")
    if not real.is_dir():
        raise PathRefused("The sub-folder is not a folder.")
    return real


def is_inside(root: Path, candidate: Path) -> bool:
    """True when the *real* location of ``candidate`` is inside ``root``."""
    try:
        return _same_or_inside(candidate.resolve(), root)
    except (OSError, RuntimeError, ValueError):  # ValueError: NUL byte in the path
        return False
