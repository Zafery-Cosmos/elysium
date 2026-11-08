"""A project's folder as agents see it: confined reads, and proposed edits.

Expert "complet" never gives a model write access. An agent describes the files
it wants in its answer; this module turns those blocks into ``FileChange`` rows
for a human to review.  The accepted ones are written by the Rust broker.

Reading here is confined too: the path is checked lexically, then resolved, so a
link inside the project cannot make an agent read outside of it.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy.orm import Session

from elysium_engine.db.models import FileChange, FileNode, MemoryFolder, PreviewRecord
from elysium_engine.untrusted import data_block, one_line

MAX_FILE_CHARS = 512_000
MAX_CHANGES_PER_TASK = 40
_MAX_PATH_CHARS = 500
_CONTEXT_FILES = 8
_CONTEXT_CHARS_PER_FILE = 8_000
_CONTEXT_CHARS_TOTAL = 30_000
_MAX_LISTED_PATHS = 200

_FILE_BLOCK = re.compile(
    r'^<elysium-file path="([^"\r\n]{1,600})">\r?\n(.*?)^</elysium-file>[ \t]*$',
    re.MULTILINE | re.DOTALL,
)
_DELETE_BLOCK = re.compile(r'^<elysium-delete path="([^"\r\n]{1,600})"\s*/>[ \t]*$', re.MULTILINE)

_PROTECTED_DIRS = frozenset(
    {".git", ".hg", ".svn", ".ssh", ".aws", ".gnupg", ".venv", "node_modules", ".elysium"}
)
_PROTECTED_NAMES = (".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "id_rsa*", "id_ed25519*",
                    ".npmrc", ".pypirc", ".netrc")
_SECRET_NAME_EXCEPTIONS = frozenset({".env.example", ".env.sample", ".env.template"})
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
)
_WORD = re.compile(r"[A-Za-z0-9_]{4,}")

FILE_FORMAT_INSTRUCTIONS = """EXECUTION MODE: COMPLET. You change the project by proposing files.
Nothing is written until the user reviews and accepts each file.

To create or replace a file, output its COMPLETE new content, never a fragment:
<elysium-file path="relative/path/from/project/root.ext">
full file content
</elysium-file>

To delete a file:
<elysium-delete path="relative/path/from/project/root.ext"/>

Each opening and closing tag stands alone on its line. Use forward slashes and
paths relative to the project root. After the blocks, summarize what you changed
and why in a few lines."""


class UnsafePathError(ValueError):
    """The path cannot be proposed: outside the project, or a protected file."""


class NotTextFileError(ValueError):
    """The file is binary or too large to be reviewed as text."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_secret_name(name: str) -> bool:
    return name not in _SECRET_NAME_EXCEPTIONS and any(fnmatch.fnmatch(name, p) for p in _PROTECTED_NAMES)


def clean_relative_path(raw: str) -> str:
    """Normalize a model-supplied path, or raise :class:`UnsafePathError`."""
    path = raw.strip().replace("\\", "/")
    if not path or len(path) > _MAX_PATH_CHARS:
        raise UnsafePathError("invalid path length")
    if path.startswith(("/", "~")) or ":" in path or any(ord(c) < 32 for c in path):
        raise UnsafePathError("the path must be relative to the project")
    parts = path.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise UnsafePathError("the path must stay inside the project")
        # Windows ignores trailing dots and spaces: ".git." would open ".git".
        if part != part.rstrip(". "):
            raise UnsafePathError("a path component cannot end with a dot or a space")
        lowered = part.lower()
        if lowered.split(".", 1)[0] in _RESERVED_NAMES:
            raise UnsafePathError("reserved Windows device name")
        if lowered in _PROTECTED_DIRS:
            raise UnsafePathError(f"'{part}' is protected")
    if _is_secret_name(parts[-1].lower()):
        raise UnsafePathError(f"'{parts[-1]}' may hold secrets and is protected")
    return str(PurePosixPath(*parts))


def workspace_root(session: Session, project_id: str) -> Path | None:
    """The folder linked to the project (scanned memory folder, else preview folder)."""
    for record in (session.get(MemoryFolder, project_id), session.get(PreviewRecord, project_id)):
        if record is not None and record.root_path and Path(record.root_path).is_dir():
            return Path(record.root_path)
    return None


def read_confined(root: Path, relative: str) -> str | None:
    """Exact text of a project file, ``None`` when it does not exist."""
    clean = clean_relative_path(relative)
    base = root.resolve()
    target = base / clean
    if not target.exists() and not target.is_symlink():
        return None
    resolved = target.resolve()
    if not resolved.is_relative_to(base):
        raise UnsafePathError("the path leaves the project through a link")
    if not resolved.is_file():
        raise NotTextFileError("not a regular file")
    if resolved.stat().st_size > MAX_FILE_CHARS:
        raise NotTextFileError("the file is too large to review")
    try:
        # Bytes, not read_text: newline translation would falsify the digest.
        return resolved.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NotTextFileError("not a UTF-8 text file") from exc


@dataclass(frozen=True, slots=True)
class ProposalOutcome:
    changes: list[FileChange]
    refused: list[tuple[str, str]]


def has_file_blocks(text: str) -> bool:
    return _FILE_BLOCK.search(text) is not None or _DELETE_BLOCK.search(text) is not None


def strip_file_blocks(text: str) -> str:
    """The agent's explanation, without the file bodies."""
    return _DELETE_BLOCK.sub("", _FILE_BLOCK.sub("", text)).strip()


def _parse_blocks(text: str) -> list[tuple[str, str | None]]:
    found: list[tuple[int, str, str | None]] = [
        (m.start(), m.group(1), m.group(2)) for m in _FILE_BLOCK.finditer(text)
    ]
    found += [(m.start(), m.group(1), None) for m in _DELETE_BLOCK.finditer(text)]
    return [(path, content) for _, path, content in sorted(found, key=lambda item: item[0])]


def propose_changes(
    session: Session,
    *,
    project_id: str,
    conversation_id: str,
    task_id: str,
    agent_name: str,
    root: Path,
    text: str,
) -> ProposalOutcome:
    """Store the agent's file blocks for review. Never touches the disk."""
    changes: list[FileChange] = []
    refused: list[tuple[str, str]] = []
    for raw_path, content in _parse_blocks(text):
        if len(changes) >= MAX_CHANGES_PER_TASK:
            refused.append((raw_path, "too many files in one task"))
            continue
        try:
            path = clean_relative_path(raw_path)
            base = read_confined(root, path)
        except (UnsafePathError, NotTextFileError, OSError) as exc:
            refused.append((raw_path, str(exc)))
            continue
        if content is not None and len(content) > MAX_FILE_CHARS:
            refused.append((path, "the file is too large to review"))
            continue
        if content is None and base is None:
            refused.append((path, "the file to delete does not exist"))
            continue
        pending = (
            session.query(FileChange)
            .filter_by(project_id=project_id, path=path, status="proposed")
            .one_or_none()
        )
        if content == base:  # no real edit; a previous proposal is now moot
            if pending is not None:
                pending.status = "rejected"
            continue
        if pending is None:
            pending = FileChange(
                project_id=project_id,
                path=path,
                base_content=base,
                base_sha256=sha256_text(base) if base is not None else None,
            )
            session.add(pending)
        pending.conversation_id = conversation_id
        pending.task_id = task_id
        pending.agent_name = agent_name
        pending.action = "delete" if content is None else "write"
        pending.new_content = content
        changes.append(pending)
    session.commit()
    return ProposalOutcome(changes=changes, refused=refused)


def _relevant_paths(session: Session, project_id: str, query: str) -> tuple[list[str], list[str]]:
    """(every known path, the paths most related to ``query`` first)."""
    nodes = list(session.query(FileNode).filter_by(project_id=project_id).order_by(FileNode.path))
    words = {w.lower() for w in _WORD.findall(query)}

    def score(node: FileNode) -> int:
        haystack = " ".join([node.path, node.summary or "", " ".join(node.symbols or [])]).lower()
        path_hits = sum(3 for w in words if w in node.path.lower())
        return path_hits + sum(1 for w in words if w in haystack)

    ranked = sorted((n for n in nodes if score(n) > 0), key=score, reverse=True)
    return [n.path for n in nodes], [n.path for n in ranked]


def files_context(
    session: Session,
    project_id: str,
    root: Path,
    query: str,
    overlay: dict[str, str | None] | None = None,
) -> str:
    """Listing + contents of the files most related to ``query``, as delimited data.

    ``overlay`` holds what earlier tasks of this run proposed: a later task must
    build on those, even though they are not on disk yet.
    """
    overlay = overlay or {}
    paths, ranked = _relevant_paths(session, project_id, query)
    ordered = [*overlay, *(p for p in ranked if p not in overlay)]
    sections: list[str] = []
    budget = _CONTEXT_CHARS_TOTAL
    for path in ordered[:_CONTEXT_FILES]:
        try:
            content = overlay[path] if path in overlay else read_confined(root, path)
        except (UnsafePathError, NotTextFileError, OSError):
            continue
        if content is None or budget <= 0:
            continue
        cut = content[: min(_CONTEXT_CHARS_PER_FILE, budget)]
        budget -= len(cut)
        marker = " (cut for size: do not rewrite this file blindly)" if len(cut) < len(content) else ""
        sections.append(f"--- {one_line(path)}{marker}\n{cut}")
    listing = "\n".join(one_line(p) for p in paths[:_MAX_LISTED_PATHS])
    if len(paths) > _MAX_LISTED_PATHS:
        listing += f"\n… and {len(paths) - _MAX_LISTED_PATHS} more"
    parts: list[str] = []
    if listing:
        parts.append("Project files:\n" + data_block(listing))
    if sections:
        parts.append("Current content of the most relevant files:\n" + data_block("\n\n".join(sections)))
    return "\n\n".join(parts)
