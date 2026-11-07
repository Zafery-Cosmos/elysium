"""Live preview: detection, real dev-server processes, ports, security, cleanup.

Integration tests use small real projects in a temp folder.  The "dev servers"
are real Node processes started through ``npm run dev`` exactly as for a real
framework (a few lines of Node honouring ``--port`` / ``-p``); no network and
no framework install are needed.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path

import pytest

from elysium_engine.parent_watch import pid_alive
from elysium_engine.preview.detect import build_command, detect
from elysium_engine.preview.manager import PreviewError, PreviewManager, free_port, probe_http
from elysium_engine.preview.paths import PathRefused, resolve_inside, resolve_root

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="Node/npm not installed")

SERVER_OK = r"""
const http = require('http'); const fs = require('fs');
const a = process.argv; let i = a.indexOf('--port'); if (i < 0) i = a.indexOf('-p');
const port = Number(a[i + 1]);
fs.writeFileSync('env-seen.json', JSON.stringify(Object.keys(process.env)));
http.createServer((q, r) => { r.end('<h1>hello preview</h1>'); }).listen(port, '127.0.0.1', () => {
  console.log('ready in 12 ms');
});
"""

SERVER_CRASH = SERVER_OK.replace("console.log('ready in 12 ms');", "setTimeout(() => process.exit(3), 1200);")
SERVER_NEVER = "setInterval(() => {}, 1000);"
SERVER_BUSY_ONCE = r"""
const fsb = require('fs');
if (!fsb.existsSync('tried')) { fsb.writeFileSync('tried', '1'); console.error('Error: listen EADDRINUSE: address already in use'); process.exit(1); }
""" + SERVER_OK
SERVER_COMPILE_ERROR = SERVER_OK.replace(
    "console.log('ready in 12 ms');",
    "console.log('ready in 12 ms'); setTimeout(() => console.log('Error: Failed to compile ./src/App.tsx'), 600);"
    " setTimeout(() => console.log('hmr update /src/App.tsx'), 2600);",
)


def make_node_project(root: Path, deps: dict[str, str], server: str = SERVER_OK, *, config: str | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(
        json.dumps({"name": "demo", "scripts": {"dev": "node server.js"}, "devDependencies": deps}),
        encoding="utf-8",
    )
    (root / "server.js").write_text(server, encoding="utf-8")
    (root / "node_modules").mkdir(exist_ok=True)
    if config:
        (root / config).write_text("export default {}", encoding="utf-8")
    return root


def make_html_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text("<html><body><h1>Hi static</h1></body></html>", encoding="utf-8")
    (root / ".env").write_text("SECRET=1", encoding="utf-8")
    return root


def wait_for(manager: PreviewManager, project_id: str, states: set[str], timeout: float = 30.0) -> dict:
    end = time.monotonic() + timeout
    view: dict = {}
    while time.monotonic() < end:
        view = manager.status(project_id)
        if view["state"] in states:
            return view
        time.sleep(0.15)
    raise AssertionError(f"never reached {states}; last: {view.get('state')} / {view.get('error')} / {view.get('logs')}")


def get(url: str, path: str = "/") -> tuple[int, str]:
    host_port = url.removeprefix("http://").rstrip("/")
    host, port = host_port.split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    return resp.status, resp.read().decode("utf-8", "replace")


@pytest.fixture
def manager(app, tmp_path):  # type: ignore[no-untyped-def]
    mgr = PreviewManager(app.state.session_factory, forbidden_dirs=(tmp_path / "data",), ready_timeout=25)
    yield mgr
    mgr.stop_all()


@pytest.fixture
def work(tmp_path) -> Path:  # type: ignore[no-untyped-def]
    path = tmp_path / "work"
    path.mkdir()
    return path


# ---------------------------------------------------------------- detection


@pytest.mark.parametrize(
    ("deps", "config", "expected"),
    [
        ({"next": "14", "react": "18"}, None, "next"),
        ({"nuxt": "3", "vue": "3"}, None, "nuxt"),
        ({"astro": "4"}, None, "astro"),
        ({"@sveltejs/kit": "2", "svelte": "4", "vite": "5"}, None, "sveltekit"),
        ({"@angular/core": "17"}, None, "angular"),
        ({"@vue/cli-service": "5", "vue": "2"}, None, "vue-cli"),
        ({"react-scripts": "5", "react": "18"}, None, "cra"),
        ({"vite": "5", "vue": "3"}, None, "vue"),
        ({"vite": "5", "react": "18"}, None, "react-vite"),
        ({"vite": "5", "svelte": "4"}, None, "svelte"),
        ({"vite": "5"}, None, "vite"),
        ({}, "vite.config.js", "vite"),
        ({}, "next.config.js", "next"),
    ],
)
def test_framework_detection(work: Path, deps: dict, config: str | None, expected: str) -> None:
    make_node_project(work, deps, config=config)
    if expected in {"angular", "vue-cli"}:
        scripts = {"angular": {"start": "ng serve"}, "vue-cli": {"serve": "vue-cli-service serve"}}[expected]
        data = json.loads((work / "package.json").read_text())
        data["scripts"] = scripts
        (work / "package.json").write_text(json.dumps(data))
    if expected == "cra":
        data = json.loads((work / "package.json").read_text())
        data["scripts"] = {"start": "react-scripts start"}
        (work / "package.json").write_text(json.dumps(data))
    result = detect(work.resolve())
    assert result.framework == expected and result.runnable, result.error


def test_detection_reports_package_manager_scripts_and_missing_deps(work: Path) -> None:
    make_node_project(work, {"vite": "5"})
    (work / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    shutil.rmtree(work / "node_modules")
    result = detect(work.resolve())
    assert result.package_manager == "pnpm" and result.script == "dev" and result.deps_installed is False


def test_html_project_is_static(work: Path) -> None:
    make_html_project(work)
    result = detect(work.resolve())
    assert result.framework == "static" and result.is_static and result.hot_update == "live-reload"


def test_real_app_root_is_found_in_a_subfolder(work: Path) -> None:
    make_node_project(work / "frontend", {"vite": "5"})
    (work / "README.md").write_text("x", encoding="utf-8")
    result = detect(work.resolve())
    assert result.app_root == (work / "frontend").resolve() and result.framework == "vite"


def test_several_apps_ask_for_a_choice_and_subdir_resolves_it(work: Path) -> None:
    make_node_project(work / "web", {"vite": "5"})
    make_node_project(work / "admin", {"next": "14"})
    ambiguous = detect(work.resolve())
    assert ambiguous.error and sorted(ambiguous.candidates) == ["admin", "web"]
    assert detect(work.resolve(), subdir="admin").framework == "next"


def test_unknown_project_gives_an_explicit_error_and_manual_override(work: Path) -> None:
    work.joinpath("package.json").write_text(json.dumps({"scripts": {"dev": "node x.js"}}))
    unknown = detect(work.resolve())
    assert unknown.framework is None and "manually" in (unknown.error or "")
    assert detect(work.resolve(), framework="vite").runnable
    assert "Unknown" in (detect(work.resolve(), framework="rm -rf").error or "")


def test_launch_command_is_an_argv_list_with_the_port_pinned() -> None:
    argv, _ = build_command("npm", "dev", "vite", 5555)
    assert argv == ["npm", "run", "dev", "--", "--port", "5555", "--strictPort", "--host", "127.0.0.1"]
    argv, _ = build_command("pnpm", "dev", "next", 4000)
    assert argv == ["pnpm", "run", "dev", "-p", "4000", "-H", "127.0.0.1"]
    argv, env = build_command("npm", "start", "cra", 4100)
    assert argv == ["npm", "run", "start"] and env["PORT"] == "4100" and env["HOST"] == "127.0.0.1"


# ---------------------------------------------------------------- path safety


def test_unsafe_roots_are_refused(tmp_path: Path) -> None:
    for bad in ("", "relative/dir", str(tmp_path / "missing"), str(Path(tmp_path.anchor)), str(Path.home())):
        with pytest.raises(PathRefused):
            resolve_root(bad)
    with pytest.raises(PathRefused):
        resolve_root(str(Path(os.environ.get("WINDIR", "/etc"))))
    file = tmp_path / "f.txt"
    file.write_text("x")
    with pytest.raises(PathRefused):
        resolve_root(str(file))
    with pytest.raises(PathRefused):
        resolve_root(str(tmp_path), forbidden=(tmp_path.parent,))


def test_subdir_cannot_escape_the_project(work: Path) -> None:
    (work / "inner").mkdir()
    root = work.resolve()
    assert resolve_inside(root, "inner") == (root / "inner")
    for bad in ("..", "../..", str(work.parent)):
        with pytest.raises(PathRefused):
            resolve_inside(root, bad)


def test_symlink_pointing_outside_is_refused(work: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, work / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    with pytest.raises(PathRefused):
        resolve_inside(work.resolve(), "link")


def test_manager_refuses_a_forbidden_folder(manager: PreviewManager, tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    with pytest.raises(PreviewError) as err:
        manager.configure("p1", str(tmp_path / "data"))
    assert err.value.code == "path_refused"


# ----------------------------------------------------- 1. plain HTML project


def test_html_project_is_served_with_live_reload_and_hides_dotfiles(manager: PreviewManager, work: Path) -> None:
    make_html_project(work)
    manager.configure("p1", str(work))
    assert manager.start("p1")["state"] == "starting"
    view = wait_for(manager, "p1", {"ready"})
    status, body = get(view["url"])
    assert status == 200 and "Hi static" in body and "/__elysium/version" in body
    assert get(view["url"], "/.env")[0] == 403  # secrets in the folder are never served
    assert get(view["url"], "/..%2f..%2fetc/passwd")[0] in (403, 404)
    assert get(view["url"], "/%2e%2e/%2e%2e/secret")[0] in (403, 404)

    # 11. a file change during the preview is noticed (page reloads itself)
    before = json.loads(get(view["url"], "/__elysium/version")[1])["v"]
    time.sleep(0.6)
    (work / "index.html").write_text("<html><body><h1>Changed</h1></body></html>", encoding="utf-8")
    time.sleep(0.6)
    after = json.loads(get(view["url"], "/__elysium/version")[1])["v"]
    assert before != after
    assert "Changed" in get(view["url"])[1]

    port = view["port"]
    manager.stop("p1")
    assert manager.status("p1")["state"] == "stopped" and probe_http(port, 0.5) is None  # 15. cleanup


# ------------------------------------------------ 2/3/4. real dev-server processes


@needs_npm
@pytest.mark.parametrize(
    ("deps", "label"),
    [({"vite": "5", "react": "18"}, "React (Vite)"), ({"next": "14"}, "Next.js"), ({"vite": "5", "vue": "3"}, "Vue (Vite)")],
)
def test_framework_dev_server_starts_and_answers(manager: PreviewManager, work: Path, deps: dict, label: str) -> None:
    make_node_project(work, deps)
    assert manager.configure("p1", str(work))["label"] == label
    with pytest.raises(PreviewError) as err:  # running project scripts needs explicit trust
        manager.start("p1")
    assert err.value.code == "trust_required"
    view = manager.start("p1", trust=True)
    assert view["url"] is None  # never announced before the server answers
    view = wait_for(manager, "p1", {"ready"})
    assert view["url"] == f"http://127.0.0.1:{view['port']}/" and view["pid"]
    assert get(view["url"])[1] == "<h1>hello preview</h1>"
    pid, port = view["pid"], view["port"]
    # the child never sees Elysium's session token
    seen = json.loads((work / "env-seen.json").read_text())
    assert "ELYSIUM_TOKEN" not in seen
    manager.stop("p1")
    time.sleep(0.5)
    assert not pid_alive(pid) and probe_http(port, 0.5) is None  # whole tree gone


@needs_npm
def test_starting_twice_does_not_start_two_servers(manager: PreviewManager, work: Path) -> None:
    make_node_project(work, {"vite": "5"})
    manager.configure("p1", str(work))
    manager.start("p1", trust=True)
    wait_for(manager, "p1", {"ready"})
    first = manager.status("p1")
    again = manager.start("p1", trust=True)
    assert again["pid"] == first["pid"] and again["port"] == first["port"]


@needs_npm
def test_two_projects_run_side_by_side_on_distinct_ports(manager: PreviewManager, tmp_path: Path) -> None:
    a = make_node_project(tmp_path / "a", {"vite": "5"})
    b = make_node_project(tmp_path / "b", {"next": "14"})
    manager.configure("pa", str(a))
    manager.configure("pb", str(b))
    manager.start("pa", trust=True)
    manager.start("pb", trust=True)
    va = wait_for(manager, "pa", {"ready"})
    vb = wait_for(manager, "pb", {"ready"})
    assert va["port"] != vb["port"] and va["pid"] != vb["pid"]
    assert manager.summary()["active"] == 2
    manager.stop("pa")
    assert probe_http(vb["port"], 1) is not None  # the other one is untouched
    assert probe_http(va["port"], 0.5) is None


# --------------------------------------------------------------- failure modes


@needs_npm
def test_missing_dependencies_are_reported_then_installed(manager: PreviewManager, work: Path) -> None:
    make_node_project(work, {}, config="vite.config.js")  # no deps -> `npm install` works offline
    shutil.rmtree(work / "node_modules")
    manager.configure("p1", str(work))
    manager.start("p1", trust=True)
    view = wait_for(manager, "p1", {"deps_missing"})
    assert view["deps_installed"] is False and "not installed" in view["error"]
    manager.start("p1", trust=True, install_deps=True)
    view = wait_for(manager, "p1", {"ready"}, timeout=90)
    assert view["url"]


@needs_npm
def test_port_taken_at_startup_retries_on_another_port(manager: PreviewManager, work: Path) -> None:
    make_node_project(work, {"vite": "5"}, SERVER_BUSY_ONCE)
    manager.configure("p1", str(work))
    manager.start("p1", trust=True)
    view = wait_for(manager, "p1", {"ready", "failed"})
    assert view["state"] == "ready"
    assert any("trying another" in line for line in view["logs"])


@needs_npm
def test_server_that_never_listens_fails_explicitly(app, work: Path) -> None:  # type: ignore[no-untyped-def]
    mgr = PreviewManager(app.state.session_factory, ready_timeout=3)
    try:
        make_node_project(work, {"vite": "5"}, SERVER_NEVER)
        mgr.configure("p1", str(work))
        mgr.start("p1", trust=True)
        view = wait_for(mgr, "p1", {"failed"}, timeout=20)
        assert "did not answer" in view["error"] and view["url"] is None
        assert view["pid"] is None  # the stuck process was killed
    finally:
        mgr.stop_all()


@needs_npm
def test_server_that_dies_is_reported(manager: PreviewManager, work: Path) -> None:
    make_node_project(work, {"vite": "5"}, SERVER_CRASH)
    manager.configure("p1", str(work))
    manager.start("p1", trust=True)
    view = wait_for(manager, "p1", {"failed"}, timeout=30)
    assert "unexpectedly" in view["error"] or "exited" in view["error"]
    # a failed preview can be restarted explicitly (no automatic restart loop)
    assert manager.start("p1", trust=True)["state"] == "starting"


@needs_npm
def test_compile_error_is_surfaced_then_cleared(manager: PreviewManager, work: Path) -> None:
    make_node_project(work, {"vite": "5"}, SERVER_COMPILE_ERROR)
    manager.configure("p1", str(work))
    manager.start("p1", trust=True)
    view = wait_for(manager, "p1", {"compile_error"}, timeout=30)
    assert "Failed to compile" in view["error"]
    view = wait_for(manager, "p1", {"ready"}, timeout=30)
    assert view["error"] is None


def test_unrunnable_project_is_refused_with_the_reason(manager: PreviewManager, work: Path) -> None:
    work.joinpath("package.json").write_text(json.dumps({"scripts": {}}))
    manager.configure("p1", str(work))
    with pytest.raises(PreviewError) as err:
        manager.start("p1", trust=True)
    assert err.value.code == "not_runnable"


def test_start_without_a_folder_is_refused(manager: PreviewManager) -> None:
    with pytest.raises(PreviewError) as err:
        manager.start("nope")
    assert err.value.code == "not_configured"


# ------------------------------------------------- restart of Elysium / orphans


@needs_npm
def test_reconcile_reclaims_a_server_left_by_a_crashed_engine(app, work: Path) -> None:  # type: ignore[no-untyped-def]
    make_node_project(work, {"vite": "5"})
    old = PreviewManager(app.state.session_factory)
    old.configure("p1", str(work))
    old.start("p1", trust=True)
    view = wait_for(old, "p1", {"ready"})
    pid, port = view["pid"], view["port"]

    # "Elysium restarts": a fresh manager on the same database; the old one is gone.
    fresh = PreviewManager(app.state.session_factory)
    assert fresh.reconcile() == 1
    time.sleep(0.5)
    assert not pid_alive(pid) and probe_http(port, 0.5) is None
    status = fresh.status("p1")
    assert status["state"] == "stopped" and status["trusted"] is True and status["root_path"]
    old.stop_all()


def test_reconcile_never_kills_an_unrelated_process(app) -> None:  # type: ignore[no-untyped-def]
    # A stale record whose pid is alive but whose port answers nothing: left alone.
    from elysium_engine.db.models import PreviewRecord

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead_port = s.getsockname()[1]
    with app.state.session_factory() as db:
        db.add(PreviewRecord(project_id="p9", root_path="x", state="ready", pid=os.getpid(), port=dead_port))
        db.commit()
    assert PreviewManager(app.state.session_factory).reconcile() == 0
    assert pid_alive(os.getpid())
    with app.state.session_factory() as db:
        assert db.get(PreviewRecord, "p9").state == "stopped"


# --------------------------------------------------------------------- HTTP API


async def test_api_flow_and_security(auth_client, app, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
    work = tmp_path_factory.mktemp("webproject")  # outside the engine's own data dir
    opened: list[str] = []
    app.state.previews._opener = opened.append  # noqa: SLF001
    pid = (await auth_client.post("/projects", json={"name": "Web"})).json()["id"]
    base = f"/projects/{pid}/preview"

    assert (await auth_client.get(base)).json() == {"project_id": pid, "configured": False, "state": "stopped"}
    assert (await auth_client.post(f"{base}/start", json={})).status_code == 409
    assert (await auth_client.put(base, json={"root_path": "relative/x"})).status_code == 422
    assert (await auth_client.put(base, json={"root_path": str(work), "framework": "bash"})).status_code == 422
    assert (await auth_client.get("/projects/missing/preview")).status_code == 404

    make_html_project(work)
    cfg = (await auth_client.put(base, json={"root_path": str(work)})).json()
    assert cfg["framework"] == "static" and cfg["state"] == "stopped" and cfg["needs_trust"] is False
    assert (await auth_client.post(f"{base}/open-external")).status_code == 409  # not ready yet

    try:
        assert (await auth_client.post(f"{base}/start", json={})).json()["state"] == "starting"
        view = wait_for(app.state.previews, pid, {"ready"})
        assert (await auth_client.post(f"{base}/open-external")).json()["url"] == view["url"]
        assert opened == [view["url"]]
        overview = (await auth_client.get("/admin/overview")).json()
        assert overview["previews"]["active"] == 1 and overview["previews"]["items"][0]["port"] == view["port"]
        assert (await auth_client.put(base, json={"root_path": str(work)})).status_code == 409  # running
    finally:
        assert (await auth_client.post(f"{base}/stop")).json()["state"] == "stopped"


async def test_preview_requires_the_token(client) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get("/projects/x/preview")).status_code in (401, 403)
    assert (await client.post("/projects/x/preview/start", json={})).status_code in (401, 403)


def test_free_port_is_actually_free_and_avoids_given_ports() -> None:
    port = free_port({1, 2})
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))
    assert sys.platform  # keep import used on every OS
