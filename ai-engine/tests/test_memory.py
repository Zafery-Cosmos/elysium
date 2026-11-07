"""Project memory: remembered items, file graph (no re-reads), context for agents."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from elysium_engine.memory import filegraph, service
from elysium_engine.memory.filegraph import analyze, resolve_imports


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def site(tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    root = tmp_path_factory.mktemp("memsite")
    _write(root, "src/main.ts", "/** App entry point. */\nimport { greet } from './lib/greet'\nimport React from 'react'\nimport '@/styles.css'\nexport function boot() { return greet() }\n")
    _write(root, "src/lib/greet.ts", "// Says hello.\nexport const greet = () => 'hi'\nexport type Name = string\n")
    _write(root, "src/styles.css", "/* theme */\nbody{margin:0}\n")
    _write(root, "api/app.py", '"""Web API."""\nfrom .models import User\nfrom api.util import clean\nimport fastapi\n\nclass Server: ...\ndef serve(): ...\n')
    _write(root, "api/models.py", '"""Data models."""\nclass User: ...\n')
    _write(root, "api/util.py", "def clean(x): return x\n")
    _write(root, "README.md", "# Demo site\n\nA small demo.\n")
    _write(root, "node_modules/junk/index.js", "module.exports = 1")
    _write(root, ".env", "SECRET=1")
    return root


# ------------------------------------------------------------------ analysis


def test_typescript_summary_symbols_and_imports() -> None:
    a = analyze("src/main.ts", "/** App entry point. */\nimport { greet } from './lib/greet'\nexport function boot() {}\nexport const X = 1\n")
    assert a.summary.startswith("App entry point.") and a.symbols == ["boot", "X"]
    assert "./lib/greet" in a.raw_imports


def test_python_docstring_symbols_and_relative_imports() -> None:
    a = analyze("api/app.py", '"""Web API."""\nfrom .models import User\nimport os\nclass Server: ...\ndef _private(): ...\ndef serve(): ...\n')
    assert a.summary.startswith("Web API.") and a.symbols == ["Server", "serve"]
    assert (1, "models") in a.python_imports and (0, "os") in a.python_imports


def test_broken_python_still_gets_a_summary() -> None:
    assert analyze("x.py", "# broken file\ndef (:\n").summary.startswith("broken file")


# ------------------------------------------------------------------ the graph


def test_scan_builds_a_graph_with_internal_and_external_imports(app, site, tmp_path) -> None:  # type: ignore[no-untyped-def]
    stats = service.scan_project(app.state.session_factory, "p1", site)
    assert stats["files"] == 7 and stats["read"] == 7 and stats["unchanged"] == 0  # node_modules / .env excluded
    with app.state.session_factory() as s:
        main = service.file_detail(s, "p1", "src/main.ts")
        assert [i["path"] for i in main["imports"]] == ["src/lib/greet.ts", "src/styles.css"]
        assert main["external"] == ["react"]
        greet = service.file_detail(s, "p1", "src/lib/greet.ts")
        assert [i["path"] for i in greet["imported_by"]] == ["src/main.ts"]  # navigation both ways
        api = service.file_detail(s, "p1", "api/app.py")
        assert {i["path"] for i in api["imports"]} == {"api/models.py", "api/util.py"}
        assert api["external"] == ["fastapi"]
        paths = {f["path"] for f in service.file_list(s, "p1")}
        assert not any("node_modules" in p or p.endswith(".env") for p in paths)


def test_graph_returns_nodes_edges_and_caps_big_projects(app, site) -> None:  # type: ignore[no-untyped-def]
    service.scan_project(app.state.session_factory, "p1", site)
    with app.state.session_factory() as s:
        g = service.graph(s, "p1")
        ids = {n["id"] for n in g["nodes"]}
        assert g["total"] == 7 and not g["truncated"] and "node_modules/junk/index.js" not in ids
        edges = {(e["source"], e["target"]) for e in g["edges"]}
        assert ("src/main.ts", "src/lib/greet.ts") in edges and ("api/app.py", "api/models.py") in edges
        assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])  # no dangling edge
        main = next(n for n in g["nodes"] if n["id"] == "src/main.ts")
        assert main["degree"] == 2 and main["dir"] == "src" and main["language"]

        small = service.graph(s, "p1", limit=3)
        assert len(small["nodes"]) == 3 and small["truncated"] and small["total"] == 7
        kept = {n["id"] for n in small["nodes"]}
        assert all(e["source"] in kept and e["target"] in kept for e in small["edges"])
        assert service.graph(s, "empty-project") == {"nodes": [], "edges": [], "total": 0, "truncated": False}


def test_unchanged_files_are_not_read_again(app, site, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sf = app.state.session_factory
    service.scan_project(sf, "p1", site)
    reads: list[str] = []
    real = filegraph.analyze
    monkeypatch.setattr(filegraph, "analyze", lambda rel, text: (reads.append(rel), real(rel, text))[1])
    again = service.scan_project(sf, "p1", site)
    assert again["read"] == 0 and again["unchanged"] == 7 and reads == []  # nothing opened: the saving

    time.sleep(0.05)
    _write(site, "src/lib/greet.ts", "// Says hello, changed.\nexport const greet = () => 'yo'\n")
    third = service.scan_project(sf, "p1", site)
    assert third["read"] == 1 and reads == ["src/lib/greet.ts"]
    with sf() as s:
        assert "changed" in service.file_detail(s, "p1", "src/lib/greet.ts")["summary"]


def test_deleted_files_leave_the_graph(app, site) -> None:  # type: ignore[no-untyped-def]
    sf = app.state.session_factory
    service.scan_project(sf, "p1", site)
    (site / "api" / "util.py").unlink()
    stats = service.scan_project(sf, "p1", site)
    assert stats["removed"] == 1
    with sf() as s:
        assert service.file_detail(s, "p1", "api/util.py") is None
        assert "api/util.py" not in {i["path"] for i in service.file_detail(s, "p1", "api/app.py")["imports"]}


def test_a_symlink_leaving_the_project_is_not_indexed(app, site, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
    outside = tmp_path_factory.mktemp("outside") / "secret.py"
    outside.write_text("def leak(): ...\n")
    try:
        os.symlink(outside, site / "leak.py")
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    service.scan_project(app.state.session_factory, "p1", site)
    with app.state.session_factory() as s:
        assert service.file_detail(s, "p1", "leak.py") is None


def test_python_package_resolution() -> None:
    a = analyze("pkg/a.py", "from pkg.b import x\nfrom . import c\nimport requests\n")
    internal, external = resolve_imports(Path("."), "pkg/a.py", a, {"pkg/a.py", "pkg/b.py", "pkg/c.py"})
    assert internal == ["pkg/b.py", "pkg/c.py"] and external == ["requests"]


# -------------------------------------------------------------------- items


def test_short_term_memory_expires_long_term_does_not(app) -> None:  # type: ignore[no-untyped-def]
    with app.state.session_factory() as s:
        short = service.create_item(s, "p1", tier="short", kind="note", title="tmp", content="x", ttl_days=1)
        service.create_item(s, "p1", tier="long", kind="decision", title="Use PostgreSQL", content="because")
        assert short.expires_at is not None
        short.expires_at = short.expires_at.replace(year=2000)
        s.commit()
        titles = [i.title for i in service.list_items(s, "p1")]
        assert titles == ["Use PostgreSQL"]  # the expired one is forgotten


def test_pinned_short_term_item_survives_and_promote_makes_it_long(app) -> None:  # type: ignore[no-untyped-def]
    with app.state.session_factory() as s:
        item = service.create_item(s, "p1", tier="short", kind="fact", title="keep", content="", pinned=True)
        item.expires_at = item.expires_at.replace(year=2000)
        s.commit()
        assert [i.title for i in service.list_items(s, "p1")] == ["keep"]
        service.promote(s, item)
        assert item.tier == "long" and item.expires_at is None


def test_task_result_memory_is_idempotent(app) -> None:  # type: ignore[no-untyped-def]
    sf = app.state.session_factory
    service.remember_task_result(sf, "p1", "t1", "Design", "first")
    service.remember_task_result(sf, "p1", "t1", "Design", "second")
    with sf() as s:
        items = service.list_items(s, "p1")
    assert len(items) == 1 and items[0].content == "second" and items[0].kind == "task_result"


# ------------------------------------------------------------------ context


def test_context_is_bounded_and_prefers_hub_files(app, site) -> None:  # type: ignore[no-untyped-def]
    sf = app.state.session_factory
    service.scan_project(sf, "p1", site)
    with sf() as s:
        service.create_item(s, "p1", tier="long", kind="constraint", title="EU hosting only", content="GDPR applies")
        full = service.build_context(s, "p1", 1500)
    assert "EU hosting only" in full["text"] and "File map (7 files" in full["text"]
    assert "src/lib/greet.ts" in full["text"] and "[used by 1]" in full["text"]

    for i in range(80):  # a big project: the map must stay inside its budget
        _write(site, f"gen/module_{i}.py", f'"""Generated module number {i} doing something useful."""\ndef run_{i}(): ...\n')
    service.scan_project(sf, "p1", site)
    with sf() as s:
        tiny = service.build_context(s, "p1", 300)
    assert tiny["tokens"] <= 305 and "more files in the map" in tiny["text"]


def test_overview_reports_the_saving(app, site) -> None:  # type: ignore[no-untyped-def]
    sf = app.state.session_factory
    service.scan_project(sf, "p1", site)
    with sf() as s:
        data = service.overview(s, "p1")
    assert data["files"]["count"] == 7 and data["files"]["last_scan"]["files"] == 7
    assert data["context"]["tokens"] > 0 and "reread_tokens_avoided" in data["context"]


# --------------------------------------------------------------------- API


async def test_memory_api_end_to_end(auth_client, site) -> None:  # type: ignore[no-untyped-def]
    pid = (await auth_client.post("/projects", json={"name": "Mem"})).json()["id"]
    base = f"/projects/{pid}/memory"

    assert (await auth_client.post(f"{base}/scan", json={})).status_code == 409  # no folder yet
    assert (await auth_client.post(f"{base}/scan", json={"root_path": "relative"})).status_code == 422

    created = (await auth_client.post(base, json={"tier": "long", "kind": "decision", "title": "Use Vite", "content": "fast"})).json()
    assert created["source"] == "user" and created["expires_at"] is None
    short = (await auth_client.post(base, json={"tier": "short", "title": "scratch"})).json()
    assert short["expires_at"] is not None

    listing = (await auth_client.get(base, params={"tier": "long"})).json()["items"]
    assert [i["title"] for i in listing] == ["Use Vite"]
    assert (await auth_client.get(base, params={"q": "fast"})).json()["items"][0]["id"] == created["id"]

    patched = (await auth_client.patch(f"{base}/items/{short['id']}", json={"title": "kept", "pinned": True})).json()
    assert patched["title"] == "kept" and patched["pinned"] is True
    promoted = (await auth_client.post(f"{base}/items/{short['id']}/promote")).json()
    assert promoted["tier"] == "long"
    assert (await auth_client.delete(f"{base}/items/{created['id']}")).status_code == 204
    assert (await auth_client.delete(f"{base}/items/{created['id']}")).status_code == 404

    scan = (await auth_client.post(f"{base}/scan", json={"root_path": str(site)})).json()
    assert scan["files"] == 7 and scan["read"] == 7
    again = (await auth_client.post(f"{base}/scan")).json()  # the folder is remembered
    assert again["read"] == 0 and again["unchanged"] == 7

    files = (await auth_client.get(f"{base}/files")).json()["files"]
    assert any(f["path"] == "src/main.ts" and f["imports"] == 2 for f in files)
    detail = (await auth_client.get(f"{base}/file", params={"path": "src/lib/greet.ts"})).json()
    assert detail["imported_by"][0]["path"] == "src/main.ts"
    assert (await auth_client.get(f"{base}/file", params={"path": "nope.ts"})).status_code == 404

    overview = (await auth_client.get(f"{base}/overview")).json()
    assert overview["items"]["long"] == 1 and overview["files"]["count"] == 7
    context = (await auth_client.get(f"{base}/context")).json()
    assert "File map" in context["text"] and context["tokens"] <= 1500

    assert (await auth_client.get("/projects/ghost/memory")).status_code == 404


async def test_memory_needs_the_token(client) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get("/projects/x/memory")).status_code in (401, 403)


async def test_agents_receive_the_memory(auth_client, app, site) -> None:  # type: ignore[no-untyped-def]
    from elysium_engine.agents.project_manager import build_project_manager

    pid = (await auth_client.post("/projects", json={"name": "Ctx"})).json()["id"]
    await auth_client.post(f"/projects/{pid}/memory", json={"tier": "long", "kind": "constraint", "title": "No cloud", "content": "on-prem"})
    text = (await auth_client.get(f"/projects/{pid}/memory/context")).json()["text"]
    agent = build_project_manager(memory_context=text)
    assert "# Project memory" in agent.system_prompt and "No cloud" in agent.system_prompt
    assert "Project memory" not in build_project_manager().system_prompt  # nothing remembered, nothing added
