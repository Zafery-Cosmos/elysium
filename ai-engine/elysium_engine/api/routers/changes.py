"""Review of the files agents proposed.

The engine has no route that writes a project file. The desktop app writes an
accepted change through the Rust broker, then reports it here; these routes only
hold the review state and refuse transitions that make no sense.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from elysium_engine.api.deps import get_session
from elysium_engine.db.models import FileChange, Project
from elysium_engine.workspace import sha256_text, workspace_root

router = APIRouter()

_TRANSITIONS = {
    "applied": ("proposed",),
    "rejected": ("proposed",),
    "reverted": ("applied",),
}


class ChangeSummaryOut(BaseModel):
    id: str
    path: str
    action: str
    agent_name: str
    status: str
    created_at: datetime


class ChangeDetailOut(ChangeSummaryOut):
    base_content: str | None
    new_content: str | None
    # What the broker must find on disk before writing, in each direction.
    base_sha256: str | None
    new_sha256: str | None


class ChangeStatusIn(BaseModel):
    status: str


class ActionDecisionIn(BaseModel):
    approved: bool


def _project_or_404(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


def _change_or_404(session: Session, change_id: str) -> FileChange:
    change = session.get(FileChange, change_id)
    if change is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Change not found.")
    return change


def _summary(change: FileChange) -> ChangeSummaryOut:
    return ChangeSummaryOut(
        id=change.id,
        path=change.path,
        action=change.action,
        agent_name=change.agent_name,
        status=change.status,
        created_at=change.created_at,
    )


@router.get("/projects/{project_id}/workspace")
def get_workspace(project_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    _project_or_404(session, project_id)
    root = workspace_root(session, project_id)
    return {"root_path": str(root) if root is not None else None}


@router.get("/projects/{project_id}/changes", response_model=list[ChangeSummaryOut])
def list_changes(
    project_id: str, session: Session = Depends(get_session)
) -> list[ChangeSummaryOut]:
    _project_or_404(session, project_id)
    rows = (
        session.query(FileChange)
        .filter(FileChange.project_id == project_id, FileChange.status.in_(("proposed", "applied")))
        .order_by(FileChange.created_at, FileChange.path)
        .all()
    )
    return [_summary(row) for row in rows]


@router.get("/changes/{change_id}", response_model=ChangeDetailOut)
def read_change(change_id: str, session: Session = Depends(get_session)) -> ChangeDetailOut:
    change = _change_or_404(session, change_id)
    return ChangeDetailOut(
        **_summary(change).model_dump(),
        base_content=change.base_content,
        new_content=change.new_content,
        base_sha256=change.base_sha256,
        new_sha256=sha256_text(change.new_content) if change.new_content is not None else None,
    )


@router.post("/changes/{change_id}/status", response_model=ChangeSummaryOut)
def set_change_status(
    change_id: str, body: ChangeStatusIn, session: Session = Depends(get_session)
) -> ChangeSummaryOut:
    change = _change_or_404(session, change_id)
    allowed_from = _TRANSITIONS.get(body.status)
    if allowed_from is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown status.")
    if change.status not in allowed_from:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"A change that is '{change.status}' cannot become '{body.status}'.",
        )
    change.status = body.status
    session.commit()
    return _summary(change)


@router.get("/conversations/{conversation_id}/actions")
def list_actions(conversation_id: str, request: Request) -> list[dict[str, Any]]:
    """Tool calls waiting for the user's decision."""
    return request.app.state.actions.pending_for(conversation_id)


@router.post(
    "/conversations/{conversation_id}/actions/{action_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def decide_action(
    conversation_id: str, action_id: str, body: ActionDecisionIn, request: Request
) -> Response:
    if not request.app.state.actions.resolve(action_id, conversation_id, body.approved):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such action is waiting.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
