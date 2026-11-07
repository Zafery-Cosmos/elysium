"""Project memory: remembered items (short/long term) and the file graph."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from elysium_engine.api.deps import get_session
from elysium_engine.db.models import MemoryItem, Project
from elysium_engine.memory import service
from elysium_engine.preview.paths import PathRefused, resolve_root

router = APIRouter(prefix="/projects/{project_id}/memory", tags=["memory"])

Tier = Literal["short", "long"]
Kind = Literal["note", "fact", "decision", "constraint", "preference", "task_result"]


class MemoryIn(BaseModel):
    tier: Tier = "long"
    kind: Kind = "note"
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=8000)
    pinned: bool = False
    ttl_days: int | None = Field(default=None, ge=1, le=365)


class MemoryPatch(BaseModel):
    kind: Kind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=8000)
    pinned: bool | None = None


class ScanIn(BaseModel):
    root_path: str | None = Field(default=None, max_length=1000)


def _project(project_id: str, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def _item(project_id: str, item_id: str, db: Session) -> MemoryItem:
    item = db.get(MemoryItem, item_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(404, "Memory item not found")
    return item


@router.get("/overview")
def get_overview(project_id: str, db: Session = Depends(get_session)) -> dict[str, Any]:
    _project(project_id, db)
    return service.overview(db, project_id)


@router.get("/context")
def get_context(
    project_id: str,
    budget_tokens: int = Query(service.CONTEXT_TOKENS, ge=200, le=8000),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Exactly what the agents receive (so the user can see and judge it)."""
    _project(project_id, db)
    return service.build_context(db, project_id, budget_tokens)


@router.get("")
def list_items(
    project_id: str,
    tier: Tier | None = None,
    kind: Kind | None = None,
    q: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _project(project_id, db)
    items = service.list_items(db, project_id, tier=tier, kind=kind, q=q)
    return {"items": [service.item_view(i) for i in items]}


@router.post("", status_code=201)
def create_item(project_id: str, body: MemoryIn, db: Session = Depends(get_session)) -> dict[str, Any]:
    _project(project_id, db)
    item = service.create_item(
        db, project_id, tier=body.tier, kind=body.kind, title=body.title, content=body.content,
        pinned=body.pinned, source="user", ttl_days=body.ttl_days,
    )  # fmt: skip
    return service.item_view(item)


@router.patch("/items/{item_id}")
def update_item(project_id: str, item_id: str, body: MemoryPatch, db: Session = Depends(get_session)) -> dict[str, Any]:
    _project(project_id, db)
    item = _item(project_id, item_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(item, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    return service.item_view(item)


@router.post("/items/{item_id}/promote")
def promote_item(project_id: str, item_id: str, db: Session = Depends(get_session)) -> dict[str, Any]:
    _project(project_id, db)
    return service.item_view(service.promote(db, _item(project_id, item_id, db)))


@router.delete("/items/{item_id}", status_code=204)
def delete_item(project_id: str, item_id: str, db: Session = Depends(get_session)) -> None:
    _project(project_id, db)
    db.delete(_item(project_id, item_id, db))
    db.commit()


@router.post("/scan")
async def scan(
    project_id: str, request: Request, body: ScanIn | None = None, db: Session = Depends(get_session)
) -> dict[str, Any]:
    """Scan the project folder into the file graph (unchanged files are not re-read)."""
    _project(project_id, db)
    raw = (body.root_path if body else None) or service.folder_for(db, project_id)
    if not raw:
        raise HTTPException(409, {"code": "no_folder", "message": "Choose the project folder first."})
    try:
        root: Path = resolve_root(raw, forbidden=(request.app.state.settings.data_dir,))
    except PathRefused as exc:
        raise HTTPException(422, {"code": "path_refused", "message": str(exc)}) from exc
    service.set_folder(db, project_id, root)
    return await asyncio.to_thread(service.scan_project, request.app.state.session_factory, project_id, root)


@router.get("/files")
def list_files(project_id: str, db: Session = Depends(get_session)) -> dict[str, Any]:
    _project(project_id, db)
    return {"files": service.file_list(db, project_id)}


@router.get("/graph")
def get_graph(project_id: str, db: Session = Depends(get_session)) -> dict[str, Any]:
    """Nodes and edges of the file graph, for the interactive map."""
    _project(project_id, db)
    return service.graph(db, project_id)


@router.get("/file")
def get_file(
    project_id: str, path: str = Query(min_length=1, max_length=500), db: Session = Depends(get_session)
) -> dict[str, Any]:
    _project(project_id, db)
    detail = service.file_detail(db, project_id, path)
    if detail is None:
        raise HTTPException(404, "File not in the map")
    return detail
