"""Projects CRUD + per-project conversations and the agent roster."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from elysium_engine.agents.project_manager import build_project_manager
from elysium_engine.api.deps import get_session
from elysium_engine.api.schemas import (
    AgentOut,
    ConversationCreate,
    ConversationOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from elysium_engine.db.models import Project
from elysium_engine.db.repository import (
    AgentRepository,
    ConversationRepository,
    ProjectRepository,
)

router = APIRouter()


def _get_or_404(session: Session, project_id: str) -> Project:
    project = ProjectRepository(session).get(project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    include_archived: bool = False, session: Session = Depends(get_session)
) -> list[ProjectOut]:
    projects = ProjectRepository(session).list(include_archived=include_archived)
    return [ProjectOut.model_validate(p) for p in projects]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)) -> ProjectOut:
    project = ProjectRepository(session).create(body.name, body.description)
    # Every project starts with its Project Manager on the roster.
    pm = build_project_manager()
    AgentRepository(session).create(
        project.id,
        name=pm.name,
        role=pm.role,
        model_ref=pm.model_ref,
        system_prompt=pm.system_prompt,
        allowed_tools=list(pm.allowed_tools),
        permissions=list(pm.permissions),
    )
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}", response_model=ProjectOut)
def read_project(project_id: str, session: Session = Depends(get_session)) -> ProjectOut:
    return ProjectOut.model_validate(_get_or_404(session, project_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str, body: ProjectUpdate, session: Session = Depends(get_session)
) -> ProjectOut:
    project = _get_or_404(session, project_id)
    updated = ProjectRepository(session).update(
        project, name=body.name, description=body.description, status=body.status
    )
    return ProjectOut.model_validate(updated)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_project(project_id: str, session: Session = Depends(get_session)) -> Response:
    # Contract: DELETE archives (reversible), it does not destroy data.
    project = _get_or_404(session, project_id)
    ProjectRepository(session).archive(project)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/conversations", response_model=list[ConversationOut])
def list_conversations(
    project_id: str, session: Session = Depends(get_session)
) -> list[ConversationOut]:
    _get_or_404(session, project_id)
    conversations = ConversationRepository(session).list_for_project(project_id)
    return [ConversationOut.model_validate(c) for c in conversations]


@router.post(
    "/projects/{project_id}/conversations",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    project_id: str, body: ConversationCreate, session: Session = Depends(get_session)
) -> ConversationOut:
    _get_or_404(session, project_id)
    conversation = ConversationRepository(session).create(project_id, body.title)
    return ConversationOut.model_validate(conversation)


@router.get("/agents", response_model=list[AgentOut])
def list_agents(
    project_id: str | None = None, session: Session = Depends(get_session)
) -> list[AgentOut]:
    """Roster for the active project; without one, the default roster template."""
    if project_id is None:
        pm = build_project_manager()
        return [
            AgentOut(
                name=pm.name,
                role=pm.role,
                model_ref=pm.model_ref,
                allowed_tools=list(pm.allowed_tools),
                permissions=list(pm.permissions),
            )
        ]
    _get_or_404(session, project_id)
    records = AgentRepository(session).list_for_project(project_id)
    return [
        AgentOut(
            id=r.id,
            name=r.name,
            role=r.role,
            model_ref=r.model_ref,
            allowed_tools=list(r.allowed_tools),
            permissions=list(r.permissions),
        )
        for r in records
    ]
