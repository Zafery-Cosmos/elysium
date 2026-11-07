"""Live preview of a project's web app (dev server lifecycle).

The frontend only ever sends a *folder* and a few switches.  It cannot send a
command: the launch command is built by :mod:`elysium_engine.preview`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from elysium_engine.api.deps import get_session
from elysium_engine.db.models import Project
from elysium_engine.preview.detect import KNOWN_FRAMEWORKS
from elysium_engine.preview.manager import PreviewError, PreviewManager

router = APIRouter(prefix="/projects/{project_id}/preview", tags=["preview"])

_HTTP = {
    "path_refused": 422,
    "not_runnable": 422,
    "not_configured": 409,
    "trust_required": 409,
    "running": 409,
    "not_ready": 409,
}


class PreviewConfigIn(BaseModel):
    root_path: str = Field(min_length=1, max_length=1000)
    subdir: str | None = Field(default=None, max_length=300)
    framework: str | None = Field(default=None, max_length=30)


class PreviewStartIn(BaseModel):
    trust: bool = False
    install_deps: bool = False


def get_manager(request: Request) -> PreviewManager:
    return request.app.state.previews  # type: ignore[no-any-return]


def _project(project_id: str, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def _wrap(error: PreviewError) -> HTTPException:
    return HTTPException(_HTTP.get(error.code, 400), {"code": error.code, "message": error.message})


@router.get("")
def get_preview(
    project_id: str, db: Session = Depends(get_session), manager: PreviewManager = Depends(get_manager)
) -> dict[str, Any]:
    _project(project_id, db)
    return manager.status(project_id)


@router.put("")
def configure_preview(
    project_id: str,
    body: PreviewConfigIn,
    db: Session = Depends(get_session),
    manager: PreviewManager = Depends(get_manager),
) -> dict[str, Any]:
    _project(project_id, db)
    if body.framework is not None and body.framework not in KNOWN_FRAMEWORKS:
        raise HTTPException(422, {"code": "bad_framework", "message": "Unknown framework."})
    try:
        return manager.configure(
            project_id, body.root_path, subdir=body.subdir, framework=body.framework
        )
    except PreviewError as exc:
        raise _wrap(exc) from exc


@router.post("/start")
def start_preview(
    project_id: str,
    body: PreviewStartIn,
    db: Session = Depends(get_session),
    manager: PreviewManager = Depends(get_manager),
) -> dict[str, Any]:
    _project(project_id, db)
    try:
        return manager.start(project_id, trust=body.trust, install_deps=body.install_deps)
    except PreviewError as exc:
        raise _wrap(exc) from exc


@router.post("/stop")
def stop_preview(
    project_id: str, db: Session = Depends(get_session), manager: PreviewManager = Depends(get_manager)
) -> dict[str, Any]:
    _project(project_id, db)
    return manager.stop(project_id)


@router.post("/restart")
def restart_preview(
    project_id: str, db: Session = Depends(get_session), manager: PreviewManager = Depends(get_manager)
) -> dict[str, Any]:
    _project(project_id, db)
    try:
        return manager.restart(project_id)
    except PreviewError as exc:
        raise _wrap(exc) from exc


@router.post("/open-external")
def open_external(
    project_id: str, db: Session = Depends(get_session), manager: PreviewManager = Depends(get_manager)
) -> dict[str, str]:
    """Open the *verified* preview URL in the system browser (no URL is accepted)."""
    _project(project_id, db)
    try:
        return {"url": manager.open_external(project_id)}
    except PreviewError as exc:
        raise _wrap(exc) from exc
