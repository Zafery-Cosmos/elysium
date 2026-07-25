"""Folder import — build a compact project-context summary from a directory.

TRUST ASSUMPTION: in desktop mode this scanner only ever runs on a path the
Rust broker has already scoped (the user picked the folder, the broker granted
access to *that* directory).  The engine therefore treats ``root`` as trusted
and does not itself sandbox the traversal — but it still refuses to slurp file
*contents* wholesale: it records structure (paths, sizes), a language
histogram and a short README excerpt only, never the full source into the DB.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

# Directories never worth importing (deps, VCS, build output, tool caches).
SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        ".hg",
        ".svn",
        "venv",
        ".venv",
        "env",
        ".env",
        "dist",
        "build",
        "target",
        "out",
        "__pycache__",
        ".idea",
        ".vscode",
        ".next",
        ".nuxt",
        ".svelte-kit",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "vendor",
        ".gradle",
        ".tox",
        ".terraform",
    }
)

# Files above this size are recorded as skipped (never read into the DB).
MAX_FILE_BYTES = 1_048_576  # ~1 MiB

# Bytes sniffed to decide whether a file is binary (NUL byte => binary).
_BINARY_SNIFF_BYTES = 8192

# Characters of a top-level README kept as project context.
_README_EXCERPT_CHARS = 2000

_LANGUAGE_BY_EXT: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".swift": "Swift",
    ".m": "Objective-C",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".sql": "SQL",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "SCSS",
    ".less": "Less",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".xml": "XML",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".txt": "Text",
    ".dockerfile": "Dockerfile",
}

_README_NAMES = ("readme.md", "readme.txt", "readme.rst", "readme")


@dataclass(slots=True)
class ImportFile:
    path: str  # relative to root, POSIX separators
    size: int
    language: str | None


@dataclass(slots=True)
class ImportStats:
    total_files: int = 0
    total_dirs: int = 0
    total_size: int = 0
    skipped_files: int = 0
    truncated: bool = False
    languages: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class ImportSummary:
    root: str
    stats: ImportStats
    tree: list[ImportFile]
    readme_excerpt: str | None = None


class ImportError_(ValueError):
    """Raised when the requested path is not an importable directory."""


def detect_language(name: str) -> str | None:
    lower = name.lower()
    if lower == "dockerfile" or lower.startswith("dockerfile."):
        return "Dockerfile"
    if lower.startswith("makefile"):
        return "Makefile"
    return _LANGUAGE_BY_EXT.get(Path(lower).suffix)


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(_BINARY_SNIFF_BYTES)
    except OSError:
        return True  # unreadable -> treat as skippable


def _excluded(rel_path: str, exclude_globs: list[str]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in exclude_globs)


def _read_readme_excerpt(root: Path) -> str | None:
    for entry in sorted(root.iterdir() if root.is_dir() else []):
        if entry.is_file() and entry.name.lower() in _README_NAMES:
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
            excerpt = text[:_README_EXCERPT_CHARS].strip()
            return excerpt or None
    return None


def scan_folder(
    path: str | os.PathLike[str],
    *,
    max_files: int = 2000,
    exclude_globs: list[str] | None = None,
) -> ImportSummary:
    """Scan ``path`` into a compact, DB-friendly project-context summary.

    Skips dependency/VCS/build directories, binary files and files larger than
    ``MAX_FILE_BYTES``, and caps the number of included files at ``max_files``
    (``stats.truncated`` flags when the cap was hit).  Never reads source file
    contents into the summary — only structure, sizes and a language
    histogram, plus a top-level README excerpt when present.
    """
    exclude_globs = exclude_globs or []
    root = Path(path)
    if not root.is_dir():
        raise ImportError_(f"Not a directory: {path}")

    stats = ImportStats()
    tree: list[ImportFile] = []

    for current_dir, dir_names, file_names in os.walk(root):
        # Prune skip dirs in place so os.walk never descends into them.
        dir_names[:] = sorted(d for d in dir_names if d not in SKIP_DIRS)
        stats.total_dirs += len(dir_names)

        for file_name in sorted(file_names):
            abs_path = Path(current_dir) / file_name
            rel_path = abs_path.relative_to(root).as_posix()

            if _excluded(rel_path, exclude_globs):
                stats.skipped_files += 1
                continue
            try:
                size = abs_path.stat().st_size
            except OSError:
                stats.skipped_files += 1
                continue
            if size > MAX_FILE_BYTES or _is_binary(abs_path):
                stats.skipped_files += 1
                continue
            if stats.total_files >= max_files:
                stats.truncated = True
                stats.skipped_files += 1
                continue

            language = detect_language(file_name)
            tree.append(ImportFile(path=rel_path, size=size, language=language))
            stats.total_files += 1
            stats.total_size += size
            if language is not None:
                stats.languages[language] = stats.languages.get(language, 0) + 1

    tree.sort(key=lambda f: f.path)
    stats.languages = dict(
        sorted(stats.languages.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return ImportSummary(
        root=str(root),
        stats=stats,
        tree=tree,
        readme_excerpt=_read_readme_excerpt(root),
    )
