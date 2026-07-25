"""The persisted task-graph API (ADR-005, AI_SYSTEM.md §4).

This is the data layer a Kanban board reads and writes; the orchestrator loop
that *executes* the graph is a later phase. Endpoints:

- ``GET  /projects/{id}/tasks`` — the board (ordered by status then position).
- ``POST /projects/{id}/tasks`` — add a card.
- ``PATCH /tasks/{id}``         — partial update; drag-and-drop moves a card.
- ``DELETE /tasks/{id}``        — remove a card.

Validation: ``agent_role`` must be in the project roster (built-in role or a
custom agent name), ``status`` is enum-checked by Pydantic, and every id in
``depends_on`` must be an existing task in the same project.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from elysium_engine.api.deps import get_session
from elysium_engine.api.schemas import TaskCreate, TaskOut, TaskUpdate
from elysium_engine.db.models import Project, Task
from elysium_engine.db.repository import AgentRepository, ProjectRepository, TaskRepository

router = APIRouter()


def _project_or_404(session: Session, project_id: str) -> Project:
    project = ProjectRepository(session).get(project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


def _task_or_404(session: Session, task_id: str) -> Task:
    task = TaskRepository(session).get(task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return task


def _validate_role(session: Session, project_id: str, agent_role: str) -> None:
    valid = AgentRepository(session).role_identifiers(project_id)
    if agent_role not in valid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown agent role '{agent_role}'. It must be one of the "
                f"project's agents: {sorted(valid)}."
            ),
        )


def _validate_depends_on(
    session: Session, project_id: str, depends_on: list[str], self_id: str | None = None
) -> None:
    repo = TaskRepository(session)
    for dep_id in depends_on:
        if dep_id == self_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A task cannot depend on itself.",
            )
        dep = repo.get(dep_id)
        if dep is None or dep.project_id != project_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"depends_on references unknown task '{dep_id}' in this project.",
            )


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_tasks(project_id: str, session: Session = Depends(get_session)) -> list[TaskOut]:
    _project_or_404(session, project_id)
    tasks = TaskRepository(session).list_by_project(project_id)
    return [TaskOut.model_validate(t) for t in tasks]


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    project_id: str, body: TaskCreate, session: Session = Depends(get_session)
) -> TaskOut:
    _project_or_404(session, project_id)
    _validate_role(session, project_id, body.agent_role)
    _validate_depends_on(session, project_id, body.depends_on)
    task = TaskRepository(session).create(
        project_id,
        title=body.title,
        agent_role=body.agent_role,
        description=body.description,
        status=body.status,
        depends_on=body.depends_on,
    )
    return TaskOut.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: str, body: TaskUpdate, session: Session = Depends(get_session)
) -> TaskOut:
    task = _task_or_404(session, task_id)
    if body.agent_role is not None:
        _validate_role(session, task.project_id, body.agent_role)
    if body.depends_on is not None:
        _validate_depends_on(session, task.project_id, body.depends_on, self_id=task.id)
    updated = TaskRepository(session).update(
        task,
        title=body.title,
        description=body.description,
        agent_role=body.agent_role,
        status=body.status,
        order_index=body.order_index,
        result_summary=body.result_summary,
        depends_on=body.depends_on,
    )
    return TaskOut.model_validate(updated)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: str, session: Session = Depends(get_session)) -> Response:
    task = _task_or_404(session, task_id)
    TaskRepository(session).delete(task)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
