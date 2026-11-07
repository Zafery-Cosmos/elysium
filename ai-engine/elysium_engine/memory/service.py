"""Memory operations: remembered items, file-graph scans, and the context agents receive."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.db.models import FileNode, MemoryFolder, MemoryItem, PreviewRecord
from elysium_engine.memory.filegraph import ScanResult, resolve_imports, scan_folder

log = logging.getLogger(__name__)

TIERS = ("short", "long")
KINDS = ("note", "fact", "decision", "constraint", "preference", "task_result")
SHORT_TERM_DAYS = 14
CONTEXT_TOKENS = 1_500


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def estimate_tokens(text: str) -> int:
    return max(0, (len(text) + 3) // 4)


def item_view(item: MemoryItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "tier": item.tier,
        "kind": item.kind,
        "title": item.title,
        "content": item.content,
        "source": item.source,
        "pinned": item.pinned,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


# ------------------------------------------------------------------- items


def purge_expired(session: Session, project_id: str) -> int:
    """Short-term memory forgets: expired, unpinned items are removed."""
    result = session.execute(
        delete(MemoryItem).where(
            MemoryItem.project_id == project_id,
            MemoryItem.expires_at.is_not(None),
            MemoryItem.expires_at < _now(),
            MemoryItem.pinned.is_(False),
        )
    )
    session.commit()
    return int(result.rowcount or 0)


def list_items(
    session: Session, project_id: str, *, tier: str | None = None, kind: str | None = None, q: str | None = None, limit: int = 200
) -> list[MemoryItem]:
    purge_expired(session, project_id)
    stmt = select(MemoryItem).where(MemoryItem.project_id == project_id)
    if tier:
        stmt = stmt.where(MemoryItem.tier == tier)
    if kind:
        stmt = stmt.where(MemoryItem.kind == kind)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(MemoryItem.title.ilike(like), MemoryItem.content.ilike(like)))
    stmt = stmt.order_by(MemoryItem.pinned.desc(), MemoryItem.updated_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def create_item(
    session: Session,
    project_id: str,
    *,
    tier: str,
    kind: str,
    title: str,
    content: str,
    pinned: bool = False,
    source: str = "user",
    source_ref: str | None = None,
    ttl_days: int | None = None,
) -> MemoryItem:
    expires = None
    if tier == "short":
        expires = _now() + timedelta(days=ttl_days or SHORT_TERM_DAYS)
    item = MemoryItem(
        project_id=project_id, tier=tier, kind=kind, title=title.strip()[:200], content=content.strip(),
        pinned=pinned, source=source, source_ref=source_ref, expires_at=expires,
    )  # fmt: skip
    session.add(item)
    session.commit()
    return item


def promote(session: Session, item: MemoryItem) -> MemoryItem:
    """Short-term -> long-term: it stops expiring."""
    item.tier, item.expires_at = "long", None
    session.commit()
    return item


def remember_task_result(
    session_factory: sessionmaker[Session], project_id: str, task_id: str, title: str, text: str
) -> None:
    """Short-term memory of what a task concluded (idempotent per task)."""
    try:
        with session_factory() as session:
            ref = f"task:{task_id}"[:80]
            existing = session.scalar(
                select(MemoryItem).where(MemoryItem.project_id == project_id, MemoryItem.source_ref == ref)
            )
            if existing is not None:
                existing.content = text.strip()[:2000]
                session.commit()
                return
            create_item(
                session, project_id, tier="short", kind="task_result", title=title, content=text.strip()[:2000],
                source="system", source_ref=ref,
            )  # fmt: skip
    except IntegrityError:
        log.info("task result for %s already remembered", task_id)
    except Exception:  # memory must never break a run
        log.exception("could not remember the result of task %s", task_id)


# ------------------------------------------------------------------ folder


def folder_for(session: Session, project_id: str) -> str | None:
    folder = session.get(MemoryFolder, project_id)
    if folder is not None:
        return folder.root_path
    preview = session.get(PreviewRecord, project_id)  # share the folder chosen for the preview
    return preview.root_path if preview is not None else None


def set_folder(session: Session, project_id: str, root: Path) -> None:
    folder = session.get(MemoryFolder, project_id) or MemoryFolder(project_id=project_id, root_path=str(root))
    folder.root_path = str(root)
    session.add(folder)
    session.commit()


# -------------------------------------------------------------- file graph


def scan_project(session_factory: sessionmaker[Session], project_id: str, root: Path) -> dict[str, Any]:
    """Scan ``root`` into the graph; files unchanged since the last scan are not re-read."""
    with session_factory() as session:
        existing = {
            n.path: (n.size, n.mtime_ns, n.sha1)
            for n in session.scalars(select(FileNode).where(FileNode.project_id == project_id))
        }
    result: ScanResult = scan_folder(root, existing)
    known = set(result.unchanged) | {c.path for c in result.changed}
    now = _now()
    with session_factory() as session:
        for scanned in result.changed:
            internal, external = resolve_imports(root, scanned.path, scanned.analysis, known)
            node = session.get(FileNode, (project_id, scanned.path)) or FileNode(project_id=project_id, path=scanned.path)
            node.language = scanned.analysis.language
            node.size, node.mtime_ns, node.sha1 = scanned.size, scanned.mtime_ns, scanned.sha1
            node.summary = scanned.analysis.summary
            node.symbols, node.imports, node.external = scanned.analysis.symbols, internal, external
            node.scanned_at = now
            session.add(node)
        if result.removed:
            session.execute(delete(FileNode).where(FileNode.project_id == project_id, FileNode.path.in_(result.removed)))
        # Unchanged files may point at files that have since been deleted.
        if result.removed:
            gone = set(result.removed)
            for node in session.scalars(select(FileNode).where(FileNode.project_id == project_id)):
                if gone.intersection(node.imports):
                    node.imports = [p for p in node.imports if p not in gone]
        stats = {
            "files": len(known),
            "read": len(result.changed),  # files actually opened this time
            "unchanged": len(result.unchanged),  # files NOT re-read
            "removed": len(result.removed),
            "skipped": result.skipped,
            "truncated": result.truncated,
            "bytes_covered": result.bytes_covered,
        }
        folder = session.get(MemoryFolder, project_id) or MemoryFolder(project_id=project_id, root_path=str(root))
        folder.root_path, folder.last_scan_at, folder.last_scan = str(root), now, stats
        session.add(folder)
        session.commit()
    return stats


def _importers(nodes: list[FileNode]) -> dict[str, list[str]]:
    reverse: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        for target in node.imports:
            reverse[target].append(node.path)
    return reverse


def file_list(session: Session, project_id: str) -> list[dict[str, Any]]:
    nodes = list(session.scalars(select(FileNode).where(FileNode.project_id == project_id).order_by(FileNode.path)))
    reverse = _importers(nodes)
    return [
        {
            "path": n.path, "language": n.language, "size": n.size, "summary": n.summary,
            "imports": len(n.imports), "imported_by": len(reverse.get(n.path, [])),
        }  # fmt: skip
        for n in nodes
    ]


def file_detail(session: Session, project_id: str, path: str) -> dict[str, Any] | None:
    node = session.get(FileNode, (project_id, path))
    if node is None:
        return None
    nodes = {n.path: n for n in session.scalars(select(FileNode).where(FileNode.project_id == project_id))}
    reverse = _importers(list(nodes.values()))

    def brief(p: str) -> dict[str, Any]:
        other = nodes.get(p)
        return {"path": p, "summary": other.summary if other else "", "language": other.language if other else None}

    return {
        "path": node.path, "language": node.language, "size": node.size, "summary": node.summary,
        "symbols": node.symbols, "external": node.external,
        "imports": [brief(p) for p in node.imports],
        "imported_by": [brief(p) for p in sorted(reverse.get(node.path, []))],
        "scanned_at": node.scanned_at.isoformat(),
    }  # fmt: skip


def overview(session: Session, project_id: str) -> dict[str, Any]:
    purge_expired(session, project_id)
    short = session.scalars(select(MemoryItem).where(MemoryItem.project_id == project_id, MemoryItem.tier == "short")).all()
    long_ = session.scalars(select(MemoryItem).where(MemoryItem.project_id == project_id, MemoryItem.tier == "long")).all()
    nodes = list(session.scalars(select(FileNode).where(FileNode.project_id == project_id)))
    folder = session.get(MemoryFolder, project_id)
    languages = Counter(n.language or "other" for n in nodes)
    context = build_context(session, project_id)
    covered = sum(n.size for n in nodes)
    return {
        "project_id": project_id,
        "folder": folder_for(session, project_id),
        "items": {"short": len(short), "long": len(long_)},
        "files": {
            "count": len(nodes),
            "bytes": covered,
            "languages": dict(languages.most_common(8)),
            "last_scan_at": folder.last_scan_at.isoformat() if folder and folder.last_scan_at else None,
            "last_scan": folder.last_scan if folder else None,
        },
        "context": {
            "tokens": context["tokens"],
            # What reading every mapped file again would cost, versus the map the agents get.
            "reread_tokens_avoided": max(0, covered // 4 - context["tokens"]) if nodes else 0,
        },
    }


# ----------------------------------------------------------------- context


def build_context(session: Session, project_id: str, budget_tokens: int = CONTEXT_TOKENS) -> dict[str, Any]:
    """The compact memory block given to the agents (bounded by ``budget_tokens``)."""
    budget = budget_tokens * 4  # characters
    items = list_items(session, project_id, limit=100)
    nodes = list(session.scalars(select(FileNode).where(FileNode.project_id == project_id)))
    reverse = _importers(nodes)
    lines: list[str] = []
    used = 0

    def add(line: str) -> bool:
        nonlocal used
        if used + len(line) + 1 > budget:
            return False
        lines.append(line)
        used += len(line) + 1
        return True

    long_items = [i for i in items if i.tier == "long"]
    short_items = [i for i in items if i.tier == "short"]
    # Half the budget at most goes to remembered items; the rest to the file map.
    cap = budget // 2
    if long_items or short_items:
        add("## Project memory")
    for label, group in (("Long-term", long_items), ("Recent (short-term)", short_items)):
        if not group:
            continue
        add(f"### {label}")
        for item in group:
            text = f"- [{item.kind}] {item.title}" + (f": {' '.join(item.content.split())[:300]}" if item.content else "")
            if used + len(text) > cap or not add(text):
                break
    if nodes:
        langs = Counter(n.language or "other" for n in nodes).most_common(4)
        add(f"## File map ({len(nodes)} files; " + ", ".join(f"{k} {v}" for k, v in langs) + ")")
        add("Use this map instead of re-reading files; open a file only when you need its exact content.")
        entry = {"main", "index", "app", "__main__", "server", "cli", "lib"}
        ranked = sorted(
            nodes,
            key=lambda n: (-len(reverse.get(n.path, [])), 0 if Path(n.path).stem.lower() in entry else 1, n.path),
        )
        shown = 0
        for node in ranked:
            if not node.summary and not reverse.get(node.path):
                continue
            hubs = len(reverse.get(node.path, []))
            line = f"- {node.path}" + (f" — {node.summary}" if node.summary else "") + (f" [used by {hubs}]" if hubs else "")
            if not add(line):
                break
            shown += 1
        omitted = len(nodes) - shown
        if omitted > 0:
            add(f"(+{omitted} more files in the map)")
    text = "\n".join(lines)
    return {"text": text, "tokens": estimate_tokens(text), "budget_tokens": budget_tokens, "items": len(items), "files": len(nodes)}
