"""Task-graph API (ADR-005) + the plan-mode ```tasks parser/persister.

Runs against a temp SQLite DB; no provider is configured and the parser/persist
path is exercised directly, so there are never network or LLM calls.
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient

from elysium_engine.agents.project_manager import (
    parse_tasks_block,
    persist_plan_tasks,
    strip_tasks_block,
)
from elysium_engine.db.repository import ProjectRepository, TaskRepository


async def _create_project(auth_client: AsyncClient, name: str = "Demo") -> str:
    response = await auth_client.post("/projects", json={"name": name, "description": "d"})
    assert response.status_code == 201
    return response.json()["id"]


# --- API: CRUD + Kanban move -------------------------------------------------


async def test_task_crud_and_move(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client, "Board")

    assert (await auth_client.get(f"/projects/{project_id}/tasks")).json() == []

    # Create two tasks; the second depends on the first.
    first = (
        await auth_client.post(
            f"/projects/{project_id}/tasks",
            json={"title": "Design schema", "agent_role": "database"},
        )
    ).json()
    second = (
        await auth_client.post(
            f"/projects/{project_id}/tasks",
            json={
                "title": "Build API",
                "description": "REST endpoints",
                "agent_role": "backend",
                "depends_on": [first["id"]],
            },
        )
    ).json()
    assert first["status"] == "todo"
    assert second["depends_on"] == [first["id"]]
    assert first["order_index"] != second["order_index"]

    listed = (await auth_client.get(f"/projects/{project_id}/tasks")).json()
    assert {t["id"] for t in listed} == {first["id"], second["id"]}

    # Drag-and-drop: move the first card to in_progress with a new position.
    moved = await auth_client.patch(
        f"/tasks/{first['id']}", json={"status": "in_progress", "order_index": 3}
    )
    assert moved.status_code == 200
    assert moved.json()["status"] == "in_progress"
    assert moved.json()["order_index"] == 3

    # Fill a result summary + mark done.
    done = await auth_client.patch(
        f"/tasks/{first['id']}",
        json={"status": "done", "result_summary": "schema.sql written"},
    )
    assert done.json()["status"] == "done"
    assert done.json()["result_summary"] == "schema.sql written"

    # Delete the second task.
    assert (await auth_client.delete(f"/tasks/{second['id']}")).status_code == 204
    remaining = (await auth_client.get(f"/projects/{project_id}/tasks")).json()
    assert [t["id"] for t in remaining] == [first["id"]]


async def test_task_accepts_role_name_and_role_label(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client)
    # Roster "name" (e.g. "frontend") and "role" label (e.g. "Frontend") both work.
    for role in ("frontend", "Frontend"):
        r = await auth_client.post(
            f"/projects/{project_id}/tasks",
            json={"title": f"UI {role}", "agent_role": role},
        )
        assert r.status_code == 201, role


async def test_task_unknown_role_422(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client)
    r = await auth_client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Cast a spell", "agent_role": "wizard"},
    )
    assert r.status_code == 422


async def test_task_bad_status_422(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client)
    task = (
        await auth_client.post(
            f"/projects/{project_id}/tasks",
            json={"title": "t", "agent_role": "backend"},
        )
    ).json()
    r = await auth_client.patch(f"/tasks/{task['id']}", json={"status": "almost"})
    assert r.status_code == 422


async def test_task_bad_depends_on_422(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client)
    r = await auth_client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "t", "agent_role": "backend", "depends_on": ["does-not-exist"]},
    )
    assert r.status_code == 422


async def test_task_depends_on_other_project_422(auth_client: AsyncClient) -> None:
    project_a = await _create_project(auth_client, "A")
    project_b = await _create_project(auth_client, "B")
    task_b = (
        await auth_client.post(
            f"/projects/{project_b}/tasks",
            json={"title": "b task", "agent_role": "backend"},
        )
    ).json()
    # A task in project A cannot depend on a task in project B.
    r = await auth_client.post(
        f"/projects/{project_a}/tasks",
        json={"title": "a task", "agent_role": "backend", "depends_on": [task_b["id"]]},
    )
    assert r.status_code == 422


async def test_task_endpoints_404(auth_client: AsyncClient) -> None:
    assert (await auth_client.get("/projects/nope/tasks")).status_code == 404
    assert (await auth_client.patch("/tasks/nope", json={"status": "done"})).status_code == 404
    assert (await auth_client.delete("/tasks/nope")).status_code == 404


# --- Plan-mode parser + persister --------------------------------------------

VALID_BLOCK = (
    "Voici le plan.\n\n"
    "## Liste des tâches\n"
    "1. Modèle de données\n"
    "2. API\n\n"
    "```tasks\n"
    "[\n"
    '  {"title": "Modèle de données", "description": "tables", '
    '"agent_role": "database", "depends_on": []},\n'
    '  {"title": "API REST", "description": "endpoints", '
    '"agent_role": "backend", "depends_on": [0]},\n'
    '  {"title": "Sorcellerie", "agent_role": "wizard", "depends_on": [0]}\n'
    "]\n"
    "```\n"
)


def test_parse_tasks_block_extracts_array() -> None:
    parsed = parse_tasks_block(VALID_BLOCK)
    assert parsed is not None
    assert len(parsed) == 3
    assert parsed[1]["agent_role"] == "backend"


def test_parse_tasks_block_missing_or_broken() -> None:
    assert parse_tasks_block("no block at all") is None
    assert parse_tasks_block("```tasks\n[broken\n```") is None
    assert parse_tasks_block('```tasks\n{"not": "a list"}\n```') is None


def test_strip_tasks_block_removes_machine_block() -> None:
    stripped = strip_tasks_block(VALID_BLOCK)
    assert "```tasks" not in stripped
    assert "Liste des tâches" in stripped


def test_persist_plan_tasks_roles_and_deps(app: FastAPI) -> None:
    factory = app.state.session_factory
    with factory() as session:
        project = ProjectRepository(session).create("Plan project")
        project_id = project.id
        conversation_id = None
        valid_roles = {"database", "backend"}

        parsed = parse_tasks_block(VALID_BLOCK)
        assert parsed is not None
        tasks = persist_plan_tasks(
            session, project_id, conversation_id, parsed, valid_roles
        )

    # The invalid-role task ("wizard") is skipped; two valid tasks persist.
    assert [t.title for t in tasks] == ["Modèle de données", "API REST"]
    assert tasks[0].agent_role == "database"
    assert tasks[1].agent_role == "backend"
    # depends_on [0] resolves to the first persisted task's id.
    assert tasks[1].depends_on == [tasks[0].id]
    assert tasks[0].depends_on == []

    with factory() as session:
        stored = TaskRepository(session).list_by_project(project_id)
    assert len(stored) == 2


def test_persist_plan_tasks_missing_block_persists_nothing(app: FastAPI) -> None:
    factory = app.state.session_factory
    with factory() as session:
        project_id = ProjectRepository(session).create("Empty").id
        assert parse_tasks_block("just prose") is None
        # Nothing to persist -> repository stays empty.
        tasks = TaskRepository(session).list_by_project(project_id)
    assert list(tasks) == []
