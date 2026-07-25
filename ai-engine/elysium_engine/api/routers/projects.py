"""Projects CRUD + per-project conversations and the agent roster."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from elysium_engine.agents.base import Agent
from elysium_engine.agents.roster import default_roster
from elysium_engine.api.deps import get_session
from elysium_engine.api.schemas import (
    AgentOut,
    AgentPermissionsUpdate,
    ConversationCreate,
    ConversationOut,
    ImportFileOut,
    ImportFolderIn,
    ImportStatsOut,
    ImportSummaryOut,
    PermissionProfile,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from elysium_engine.db.models import AgentRecord, Project
from elysium_engine.db.repository import (
    AgentRepository,
    ConversationRepository,
    MemoryRepository,
    ProjectRepository,
)
from elysium_engine.importer import ImportError_, ImportSummary, scan_folder

router = APIRouter()


def _agent_out_from_record(record: AgentRecord) -> AgentOut:
    return AgentOut(
        id=record.id,
        name=record.name,
        role=record.role,
        model_ref=record.model_ref,
        allowed_tools=list(record.allowed_tools),
        permissions=list(record.permissions),
        permission_profile=PermissionProfile(
            filesystem=record.filesystem,  # type: ignore[arg-type]
            shell=record.shell,
            network=record.network,
            allowed_tools=list(record.allowed_tools),
        ),
    )


def _agent_out_from_template(agent: Agent) -> AgentOut:
    return AgentOut(
        name=agent.name,
        role=agent.role,
        model_ref=agent.model_ref,
        allowed_tools=list(agent.allowed_tools),
        permissions=list(agent.permissions),
        permission_profile=PermissionProfile(
            filesystem=agent.filesystem,  # type: ignore[arg-type]
            shell=agent.shell,
            network=agent.network,
            allowed_tools=list(agent.allowed_tools),
        ),
    )


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
    # Seed the fixed V1 roster with least-privilege permission profiles.
    agents = AgentRepository(session)
    for agent in default_roster():
        agents.create(
            project.id,
            name=agent.name,
            role=agent.role,
            model_ref=agent.model_ref,
            system_prompt=agent.system_prompt,
            allowed_tools=list(agent.allowed_tools),
            permissions=list(agent.permissions),
            filesystem=agent.filesystem,
            shell=agent.shell,
            network=agent.network,
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
    """Roster for the active project (with permission profiles); without one,
    the default roster template."""
    if project_id is None:
        return [_agent_out_from_template(agent) for agent in default_roster()]
    _get_or_404(session, project_id)
    records = AgentRepository(session).list_for_project(project_id)
    return [_agent_out_from_record(r) for r in records]


@router.patch("/agents/{role}/permissions", response_model=AgentOut)
def update_agent_permissions(
    role: str,
    body: AgentPermissionsUpdate,
    project_id: str,
    session: Session = Depends(get_session),
) -> AgentOut:
    """Adjust one role's permission profile within a project."""
    _get_or_404(session, project_id)
    repo = AgentRepository(session)
    record = repo.get_by_role(project_id, role)
    if record is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No '{role}' agent in this project."
        )
    updated = repo.update_permissions(
        record,
        filesystem=body.filesystem,
        shell=body.shell,
        network=body.network,
        allowed_tools=body.allowed_tools,
    )
    return _agent_out_from_record(updated)


def _summary_out(summary: ImportSummary) -> ImportSummaryOut:
    return ImportSummaryOut(
        root=summary.root,
        stats=ImportStatsOut(
            total_files=summary.stats.total_files,
            total_dirs=summary.stats.total_dirs,
            total_size=summary.stats.total_size,
            skipped_files=summary.stats.skipped_files,
            truncated=summary.stats.truncated,
            languages=summary.stats.languages,
        ),
        tree=[
            ImportFileOut(path=f.path, size=f.size, language=f.language)
            for f in summary.tree
        ],
        readme_excerpt=summary.readme_excerpt,
    )


@router.post("/projects/{project_id}/import-folder", response_model=ImportSummaryOut)
def import_folder(
    project_id: str,
    body: ImportFolderIn,
    session: Session = Depends(get_session),
) -> ImportSummaryOut:
    """Scan a (broker-scoped) folder into a compact project-context summary.

    Persists a compact summary as a ``memory`` row (kind ``import_summary``);
    file *contents* are never stored — only structure, a language histogram and
    a README excerpt.
    """
    _get_or_404(session, project_id)
    try:
        summary = scan_folder(
            body.path, max_files=body.max_files, exclude_globs=body.exclude_globs
        )
    except ImportError_ as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    out = _summary_out(summary)
    # Store a compact summary (structure + histogram + excerpt), not contents.
    MemoryRepository(session).add(
        project_id,
        kind="import_summary",
        content=out.model_dump_json(),
    )
    return out
