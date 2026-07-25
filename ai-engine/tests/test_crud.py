"""Projects / conversations / messages CRUD and the message->event flow.

Runs against a temp SQLite DB. No provider is configured, so the triggered
PM run deterministically records an error event — never a network call.
"""

from __future__ import annotations

import asyncio

from httpx import AsyncClient


async def _create_project(auth_client: AsyncClient, name: str = "Demo") -> str:
    response = await auth_client.post("/projects", json={"name": name, "description": "d"})
    assert response.status_code == 201
    return response.json()["id"]


async def _create_conversation(auth_client: AsyncClient, project_id: str) -> str:
    response = await auth_client.post(f"/projects/{project_id}/conversations", json={})
    assert response.status_code == 201
    return response.json()["id"]


async def test_project_crud_cycle(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client, "Resto app")

    response = await auth_client.get("/projects")
    assert [p["name"] for p in response.json()] == ["Resto app"]

    response = await auth_client.get(f"/projects/{project_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "active"

    response = await auth_client.patch(
        f"/projects/{project_id}", json={"name": "Resto v2", "description": "better"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Resto v2"
    assert response.json()["description"] == "better"

    # DELETE archives (reversible), it does not destroy.
    response = await auth_client.delete(f"/projects/{project_id}")
    assert response.status_code == 204
    assert (await auth_client.get("/projects")).json() == []
    archived = (await auth_client.get("/projects", params={"include_archived": True})).json()
    assert [p["status"] for p in archived] == ["archived"]


async def test_unknown_project_404(auth_client: AsyncClient) -> None:
    assert (await auth_client.get("/projects/nope")).status_code == 404
    assert (await auth_client.patch("/projects/nope", json={"name": "x"})).status_code == 404
    assert (await auth_client.get("/projects/nope/conversations")).status_code == 404


async def test_conversations_crud(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client)
    assert (await auth_client.get(f"/projects/{project_id}/conversations")).json() == []

    conversation_id = await _create_conversation(auth_client, project_id)
    listed = (await auth_client.get(f"/projects/{project_id}/conversations")).json()
    assert [c["id"] for c in listed] == [conversation_id]
    assert listed[0]["project_id"] == project_id


async def test_message_post_and_history(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client)
    conversation_id = await _create_conversation(auth_client, project_id)

    response = await auth_client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "I want an app to book restaurants"},
    )
    assert response.status_code == 202
    message_id = response.json()["id"]

    history = (await auth_client.get(f"/conversations/{conversation_id}/messages")).json()
    assert [m["id"] for m in history] == [message_id]
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "I want an app to book restaurants"

    response = await auth_client.post("/conversations/nope/messages", json={"content": "x"})
    assert response.status_code == 404


async def test_message_triggers_agent_events_on_stream(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client)
    conversation_id = await _create_conversation(auth_client, project_id)

    response = await auth_client.post(
        f"/conversations/{conversation_id}/messages", json={"content": "hello"}
    )
    assert response.status_code == 202
    await asyncio.sleep(0.1)  # let the (provider-less) PM run finish

    response = await auth_client.get(f"/conversations/{conversation_id}/stream")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: agent_status" in body
    # No provider configured -> the run reports a recoverable error event.
    assert "event: error" in body
    assert "No AI model is configured" in body


async def test_stream_after_cursor_skips_replayed_events(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client)
    conversation_id = await _create_conversation(auth_client, project_id)
    await auth_client.post(f"/conversations/{conversation_id}/messages", json={"content": "hi"})
    await asyncio.sleep(0.1)

    full = (await auth_client.get(f"/conversations/{conversation_id}/stream")).text
    last_id = max(int(line[4:]) for line in full.splitlines() if line.startswith("id: "))
    tail = (
        await auth_client.get(
            f"/conversations/{conversation_id}/stream", params={"after": last_id}
        )
    ).text
    assert tail == ""


async def test_agents_roster(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client)
    roster = (await auth_client.get("/agents", params={"project_id": project_id})).json()
    names = [a["name"] for a in roster]
    assert names == [
        "project_manager",
        "architect",
        "frontend",
        "backend",
        "database",
        "devops",
        "security",
        "qa",
    ]
    pm = roster[0]
    assert pm["role"] == "Project Manager"
    assert pm["model_ref"] == "auto"
    # Every agent carries a least-privilege permission profile (AI_SYSTEM.md §1).
    for agent in roster:
        profile = agent["permission_profile"]
        assert profile["filesystem"] in {"none", "read", "read_write"}
        assert isinstance(profile["shell"], bool)
        assert isinstance(profile["network"], bool)
    # Security is read-only, no shell/network; DevOps gets shell + network.
    by_name = {a["name"]: a["permission_profile"] for a in roster}
    assert by_name["security"]["filesystem"] == "read"
    assert by_name["security"]["shell"] is False
    assert by_name["devops"]["shell"] is True
    assert by_name["devops"]["network"] is True


async def test_models_listing_and_provider_config(auth_client: AsyncClient) -> None:
    providers = (await auth_client.get("/models")).json()["providers"]
    by_name = {p["name"]: p for p in providers}
    assert {"anthropic", "openai", "ollama", "deepseek", "mistral"} <= set(by_name)
    # Nothing configured yet; reachability is only probed on demand.
    assert all(p["configured"] is False for p in providers)
    assert all(p["reachable"] is None for p in providers)

    # Configure the local Ollama provider: no API key needed.
    response = await auth_client.put("/models/providers/ollama", json={})
    assert response.status_code == 200
    assert response.json()["configured"] is True

    # Configure a remote provider with a key (kept out of the DB and response).
    response = await auth_client.put(
        "/models/providers/anthropic", json={"api_key": "sk-test-not-a-real-key"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert "sk-test" not in response.text

    providers = (await auth_client.get("/models")).json()["providers"]
    by_name = {p["name"]: p for p in providers}
    assert by_name["ollama"]["configured"] is True
    assert by_name["anthropic"]["configured"] is True
    assert by_name["openai"]["configured"] is False
