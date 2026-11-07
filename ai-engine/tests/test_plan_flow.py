"""Plan mode: a new plan replaces the old one; a refused plan is removed."""

from __future__ import annotations

from elysium_engine.agents.project_manager import build_plan_finalizer
from elysium_engine.db.repository import AgentRepository, TaskRepository

PLAN_TEXT = """Voici le plan.

```tasks
[
  {"title": "Modeliser les donnees", "description": "", "agent_role": "database", "depends_on": []},
  {"title": "Construire l'API", "description": "", "agent_role": "backend", "depends_on": [0]},
  {"title": "Faire l'interface", "description": "", "agent_role": "frontend", "depends_on": [1]}
]
```
"""


async def _project_and_conversation(auth_client):  # type: ignore[no-untyped-def]
    project_id = (await auth_client.post("/projects", json={"name": "P"})).json()["id"]
    conversation_id = (
        await auth_client.post(f"/projects/{project_id}/conversations", json={})
    ).json()["id"]
    return project_id, conversation_id


def _finalizer(app, project_id, conversation_id):  # type: ignore[no-untyped-def]
    with app.state.session_factory() as session:
        roles = AgentRepository(session).role_identifiers(project_id)
    return build_plan_finalizer(app.state.session_factory, project_id, conversation_id, roles)


def _tasks(app, project_id):  # type: ignore[no-untyped-def]
    with app.state.session_factory() as session:
        return list(TaskRepository(session).list_by_project(project_id))


async def test_asking_for_the_plan_twice_does_not_duplicate_the_board(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    project_id, conversation_id = await _project_and_conversation(auth_client)
    finalize = _finalizer(app, project_id, conversation_id)

    first = finalize(PLAN_TEXT)
    assert first[0][1]["count"] == 3 and first[0][1]["replaced"] == 0
    second = finalize(PLAN_TEXT)

    assert len(_tasks(app, project_id)) == 3  # replaced, not 6
    assert second[0][1]["replaced"] == 3
    assert "3 tasks" in second[0][1]["summary"]  # readable text for the activity feed


async def test_replanning_keeps_started_and_hand_made_tasks(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    project_id, conversation_id = await _project_and_conversation(auth_client)
    finalize = _finalizer(app, project_id, conversation_id)
    finalize(PLAN_TEXT)

    with app.state.session_factory() as session:
        repo = TaskRepository(session)
        done = repo.list_by_project(project_id)[0]
        repo.update(done, status="done", result_summary="shipped")
        repo.create(project_id, "Added by hand", "qa")  # no conversation id

    finalize(PLAN_TEXT)

    titles = sorted(t.title for t in _tasks(app, project_id))
    assert "Added by hand" in titles  # manual task survived
    statuses = [t.status for t in _tasks(app, project_id)]
    assert statuses.count("done") == 1  # started work survived
    assert len(titles) == 1 + 1 + 3  # hand-made + done + the NEW plan's 3


async def test_refusing_a_plan_removes_only_unstarted_plan_tasks(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    project_id, conversation_id = await _project_and_conversation(auth_client)
    _finalizer(app, project_id, conversation_id)(PLAN_TEXT)
    with app.state.session_factory() as session:
        repo = TaskRepository(session)
        repo.update(repo.list_by_project(project_id)[0], status="in_progress")
        repo.create(project_id, "Added by hand", "qa")

    response = await auth_client.delete(f"/conversations/{conversation_id}/plan")
    assert response.status_code == 200 and response.json() == {"deleted": 2}

    remaining = {t.title: t.status for t in _tasks(app, project_id)}
    assert "Added by hand" in remaining
    assert "in_progress" in remaining.values()
    assert len(remaining) == 2


async def test_refusing_a_plan_for_an_unknown_conversation_is_404(auth_client) -> None:  # type: ignore[no-untyped-def]
    assert (await auth_client.delete("/conversations/nope/plan")).status_code == 404
