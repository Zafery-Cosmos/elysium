"""CLI sign-in sessions: pasted codes, redirect addresses and device codes.

A tiny Python script stands in for the vendor CLI (same prompts as the real
``claude auth login`` / ``codex login --device-auth``); nothing real is opened.
"""

from __future__ import annotations

import sys
import time

import pytest

from elysium_engine.providers.cli_login import (
    CliLoginManager,
    LoginSession,
    interpret_pasted,
)

FAKE_CLAUDE = r"""
import sys
print("Opening browser to sign in...")
print("If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?client_id=x&state=ST123")
sys.stdout.write("Paste code here if prompted > ")
sys.stdout.flush()
line = sys.stdin.readline().strip()
if line == "good#ST123":
    print("Login successful")
    sys.exit(0)
print("Login failed: That code wasn't accepted.")
sys.exit(1)
"""

FAKE_CODEX_DEVICE = (
    "import sys, time\n"
    "print('\\x1b[90mWelcome to Codex\\x1b[0m')\n"
    "print('1. Open this link in your browser and sign in to your account')\n"
    "print('   \\x1b[94mhttps://auth.openai.com/codex/device\\x1b[0m')\n"
    "print('2. Enter this one-time code (expires in 15 minutes)')\n"
    "print('   \\x1b[94m4MY5-YITK9\\x1b[0m')\n"
    "sys.stdout.flush()\n"
    "time.sleep(30)\n"
)


def _wait(predicate, timeout: float = 8.0) -> bool:  # type: ignore[no-untyped-def]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def manager():  # type: ignore[no-untyped-def]
    mgr = CliLoginManager()
    yield mgr
    mgr.shutdown()


def _start_claude(manager: CliLoginManager) -> LoginSession:
    session = manager.start("claude-code", [sys.executable, "-c", FAKE_CLAUDE])
    assert _wait(lambda: session.auth_url is not None)
    return session


# --------------------------------------------------------- interpret_pasted


def test_bare_code_goes_to_stdin() -> None:
    assert interpret_pasted(" abc#def \n").value == "abc#def"
    assert interpret_pasted("abc").kind == "stdin"


def test_vendor_redirect_address_becomes_code_and_state() -> None:
    pasted = interpret_pasted(
        "https://platform.claude.com/oauth/code/callback?code=C0DE&state=S1"
    )
    assert (pasted.kind, pasted.value) == ("stdin", "C0DE#S1")


def test_loopback_address_is_forwarded_when_state_matches() -> None:
    url = "http://127.0.0.1:54321/callback?code=C0DE&state=S1"
    pasted = interpret_pasted(url, expected_state="S1")
    assert (pasted.kind, pasted.value) == ("forward", url)


def test_loopback_address_with_other_state_is_refused() -> None:
    with pytest.raises(ValueError, match="different sign-in"):
        interpret_pasted("http://localhost:1455/auth/callback?code=C&state=OTHER", "S1")


@pytest.mark.parametrize("raw", ["", "   ", "https://example.com/no-code", "a\nb"])
def test_garbage_is_refused(raw: str) -> None:
    with pytest.raises(ValueError):
        interpret_pasted(raw)


# ------------------------------------------------------------------ session


def test_pasted_code_signs_in(manager: CliLoginManager) -> None:
    session = _start_claude(manager)
    assert session.accepts_input and not session.finished
    assert session.auth_state == "ST123"
    session.submit("good#ST123")
    assert _wait(lambda: session.finished)
    assert session.succeeded and session.error is None


def test_pasted_redirect_address_signs_in(manager: CliLoginManager) -> None:
    session = _start_claude(manager)
    session.submit("https://platform.claude.com/oauth/code/callback?code=good&state=ST123")
    assert _wait(lambda: session.succeeded)


def test_wrong_code_reports_the_cli_message(manager: CliLoginManager) -> None:
    session = _start_claude(manager)
    session.submit("nope#ST123")
    assert _wait(lambda: session.finished)
    assert not session.succeeded
    assert "wasn't accepted" in (session.error or "")
    with pytest.raises(ValueError, match="already over"):
        session.submit("good#ST123")


def test_loopback_callback_is_replayed_locally(
    manager: CliLoginManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        "elysium_engine.providers.cli_login.httpx.get",
        lambda url, **_kw: seen.append(url),
    )
    session = _start_claude(manager)
    url = "http://127.0.0.1:54321/callback?code=good&state=ST123"
    session.submit(url)
    assert seen == [url]
    with pytest.raises(ValueError, match="different sign-in"):
        session.submit("http://127.0.0.1:54321/callback?code=good&state=EVIL")
    assert seen == [url]  # the foreign callback was never replayed


def test_device_code_is_extracted_without_ansi(manager: CliLoginManager) -> None:
    session = manager.start(
        "codex", [sys.executable, "-c", FAKE_CODEX_DEVICE], device=True
    )
    assert _wait(lambda: session.device_code is not None)
    assert session.auth_url == "https://auth.openai.com/codex/device"
    assert session.device_code == "4MY5-YITK9"
    assert session.accepts_input is False  # nothing to paste in device mode


def test_cancel_kills_the_process(manager: CliLoginManager) -> None:
    session = manager.start(
        "codex", [sys.executable, "-c", FAKE_CODEX_DEVICE], device=True
    )
    assert _wait(lambda: session.device_code is not None)
    manager.cancel("codex")
    assert _wait(lambda: session.finished)
    assert session.error == "Sign-in cancelled."


def test_new_start_replaces_previous_session(manager: CliLoginManager) -> None:
    first = _start_claude(manager)
    second = _start_claude(manager)
    assert first is not second
    assert _wait(lambda: first.finished)  # the old one was cancelled


async def test_login_route_rejects_non_cli_provider(auth_client) -> None:  # type: ignore[no-untyped-def]
    response = await auth_client.post("/models/providers/openai/login")
    assert response.status_code == 422


# ------------------------------------------- already signed in / switch account


def _fake_cli(monkeypatch, app, *, signed_in: bool, calls: list[str]):  # type: ignore[no-untyped-def]
    """Replace everything that would touch the real CLI (never log the user out)."""
    registry = app.state.registry
    monkeypatch.setattr("elysium_engine.providers.registry.find_binary", lambda _n: "claude")

    async def state(name: str):  # type: ignore[no-untyped-def]
        if calls and calls[-1] == "logout":
            return False, "Not signed in", None
        if not signed_in:
            return False, "Not signed in", None
        return True, None, {"email": "me@example.com", "plan": "max", "method": "claude.ai"}

    async def logout(name: str):  # type: ignore[no-untyped-def]
        calls.append("logout")
        return True, ""

    monkeypatch.setattr(registry, "cli_state", state)
    monkeypatch.setattr(registry, "cli_logout", logout)
    monkeypatch.setattr(
        registry, "cli_login_argv", lambda name, mode="browser": [sys.executable, "-c", FAKE_CLAUDE]
    )


async def test_existing_session_is_reported_not_silently_accepted(  # type: ignore[no-untyped-def]
    auth_client, app, monkeypatch
) -> None:
    calls: list[str] = []
    _fake_cli(monkeypatch, app, signed_in=True, calls=calls)
    body = (await auth_client.post("/models/providers/claude-code/login", json={})).json()
    assert body["state"] == "signed_in" and body["already_signed_in"] is True
    assert body["account"]["email"] == "me@example.com" and body["account"]["plan"] == "max"
    assert calls == []  # nothing was logged out, nothing was started


async def test_switching_account_signs_out_then_starts_a_new_login(  # type: ignore[no-untyped-def]
    auth_client, app, monkeypatch
) -> None:
    calls: list[str] = []
    _fake_cli(monkeypatch, app, signed_in=True, calls=calls)
    try:
        body = (
            await auth_client.post("/models/providers/claude-code/login", json={"force": True})
        ).json()
        assert calls == ["logout"]
        assert body["state"] == "pending" and body["auth_url"].startswith("https://")
        assert body["accepts_input"] is True and body["already_signed_in"] is False
    finally:
        app.state.login_manager.shutdown()


async def test_logout_endpoint(auth_client, app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    _fake_cli(monkeypatch, app, signed_in=True, calls=calls)
    body = (await auth_client.post("/models/providers/claude-code/logout")).json()
    assert body["state"] == "signed_out" and calls == ["logout"]


async def test_logout_is_refused_for_api_providers(auth_client) -> None:  # type: ignore[no-untyped-def]
    assert (await auth_client.post("/models/providers/openai/logout")).status_code == 422


async def test_admin_shows_whose_account_is_connected(  # type: ignore[no-untyped-def]
    auth_client, app, monkeypatch
) -> None:
    _fake_cli(monkeypatch, app, signed_in=True, calls=[])
    await auth_client.put("/models/providers/claude-code", json={})
    providers = (await auth_client.get("/admin/overview")).json()["providers"]
    provider = next(p for p in providers if p["name"] == "claude-code")
    assert provider["signed_in"] is True
    assert provider["account"]["email"] == "me@example.com"


# ------------------------------------------- Elysium = instance SEPARÉE du terminal


def test_cli_session_env_points_at_elysium_private_folders(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from elysium_engine.providers.cli_common import cli_session_env, set_cli_home

    set_cli_home(tmp_path / "cli")
    try:
        env = cli_session_env()
        assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "cli" / "claude")
        assert env["CODEX_HOME"] == str(tmp_path / "cli" / "codex")
        assert (tmp_path / "cli" / "claude").is_dir() and (tmp_path / "cli" / "codex").is_dir()
    finally:
        set_cli_home(None)


def test_without_a_home_the_user_environment_is_not_touched() -> None:
    from elysium_engine.providers.cli_common import cli_session_env, set_cli_home

    set_cli_home(None)
    assert cli_session_env() == {}


def test_spawned_cli_really_receives_the_private_folders(  # type: ignore[no-untyped-def]
    tmp_path, manager: CliLoginManager
) -> None:
    from elysium_engine.providers.cli_common import set_cli_home

    set_cli_home(tmp_path / "cli")
    try:
        script = "import os; print(os.environ['CLAUDE_CONFIG_DIR']); print(os.environ['CODEX_HOME'])"
        session = manager.start("claude-code", [sys.executable, "-c", script])
        assert _wait(lambda: session.finished)
        out = session._output()
        assert str(tmp_path / "cli" / "claude") in out
        assert str(tmp_path / "cli" / "codex") in out
    finally:
        set_cli_home(None)


def test_create_app_keeps_cli_sessions_inside_the_app_data_dir(app, settings) -> None:  # type: ignore[no-untyped-def]
    from elysium_engine.providers.cli_common import cli_session_env, set_cli_home

    try:
        assert cli_session_env()["CLAUDE_CONFIG_DIR"] == str(settings.data_dir / "cli" / "claude")
    finally:
        set_cli_home(None)
