"""Importing a pasted sign-in token (Claude `setup-token` / Codex auth.json)."""

from __future__ import annotations

import json
import os
import sys

import pytest

from elysium_engine.providers import cli_common
from elysium_engine.providers.cli_token import (
    CLAUDE_TOKEN_KEY,
    TokenImportError,
    env_for,
    parse_claude_token,
    parse_codex_auth,
)

TOKEN = "sk-ant-oat01-" + "Ab3_dEfGh-" * 8
AUTH = {"OPENAI_API_KEY": None, "tokens": {"access_token": "acc", "refresh_token": "ref", "id_token": "i"}}


# ----------------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    "pasted",
    [TOKEN, f"  {TOKEN}\n", f"export CLAUDE_CODE_OAUTH_TOKEN={TOKEN}", f'CLAUDE_CODE_OAUTH_TOKEN="{TOKEN}"'],
)
def test_claude_token_is_extracted_from_common_paste_shapes(pasted: str) -> None:
    assert parse_claude_token(pasted) == TOKEN


@pytest.mark.parametrize("bad", ["", "hello", "sk-ant-short", "sk-ant-" + "a" * 50 + " extra words", "x" * 100_000])
def test_garbage_is_not_a_claude_token(bad: str) -> None:
    with pytest.raises(TokenImportError):
        parse_claude_token(bad)


def test_codex_auth_json_must_have_chatgpt_tokens() -> None:
    assert parse_codex_auth(json.dumps(AUTH))["tokens"]["access_token"] == "acc"
    for bad in ("", "not json", "[]", json.dumps({"tokens": {}}), json.dumps({"tokens": {"access_token": "a"}}),
                json.dumps({"OPENAI_API_KEY": "sk-x"})):
        with pytest.raises(TokenImportError):
            parse_codex_auth(bad)


# ------------------------------------------------- the token goes to `claude` only


def test_only_the_claude_process_receives_the_token(app) -> None:  # type: ignore[no-untyped-def]
    app.state.secret_store.set(CLAUDE_TOKEN_KEY, TOKEN)
    assert env_for("claude") == {"CLAUDE_CODE_OAUTH_TOKEN": TOKEN}
    assert env_for(r"C:\Users\me\AppData\Roaming\npm\claude.cmd") == {"CLAUDE_CODE_OAUTH_TOKEN": TOKEN}
    assert env_for("codex") == {} and env_for(sys.executable) == {}
    assert cli_common._clean_env("claude")["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in cli_common._clean_env("codex")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in cli_common._clean_env()


# ------------------------------------------------------------------------- routes


@pytest.fixture
def cli_ok(app, monkeypatch):  # type: ignore[no-untyped-def]
    """Fake CLIs: installed, verification outcome and sign-in state are controllable."""
    reg = app.state.registry
    monkeypatch.setattr("elysium_engine.providers.registry.find_binary", lambda _n: "x")
    state = {"verify": (True, None), "signed_in": True}

    async def verify(token):  # type: ignore[no-untyped-def]
        return state["verify"]

    async def cli_state(name):  # type: ignore[no-untyped-def]
        return (True, None, {"method": "oauth_token", "email": "me@example.com"}) if state["signed_in"] else (False, "Not signed in", None)

    monkeypatch.setattr(reg, "verify_claude_token", verify)
    monkeypatch.setattr(reg, "cli_state", cli_state)
    return state


async def test_claude_token_is_verified_stored_in_the_keychain_and_never_echoed(auth_client, app, cli_ok) -> None:  # type: ignore[no-untyped-def]
    response = await auth_client.post("/models/providers/claude-code/token", json={"token": f"export CLAUDE_CODE_OAUTH_TOKEN={TOKEN}"})
    body = response.json()
    assert body["state"] == "signed_in" and body["account"]["email"] == "me@example.com"
    assert TOKEN not in response.text  # the token is never returned
    assert app.state.secret_store.get(CLAUDE_TOKEN_KEY) == TOKEN
    providers = (await auth_client.get("/models")).json()
    assert any(p["name"] == "claude-code" for p in (providers["providers"] if isinstance(providers, dict) else providers))


async def test_rejected_claude_token_is_not_kept(auth_client, app, cli_ok) -> None:  # type: ignore[no-untyped-def]
    cli_ok["verify"] = (False, "Invalid bearer token")
    body = (await auth_client.post("/models/providers/claude-code/token", json={"token": TOKEN})).json()
    assert body["state"] == "failed" and "rejected" in body["detail"]
    assert app.state.secret_store.get(CLAUDE_TOKEN_KEY) is None


async def test_failed_signin_after_import_restores_the_previous_token(auth_client, app, cli_ok) -> None:  # type: ignore[no-untyped-def]
    app.state.secret_store.set(CLAUDE_TOKEN_KEY, "sk-ant-previous-" + "x" * 40)
    cli_ok["signed_in"] = False
    body = (await auth_client.post("/models/providers/claude-code/token", json={"token": TOKEN})).json()
    assert body["state"] == "failed"
    assert app.state.secret_store.get(CLAUDE_TOKEN_KEY) == "sk-ant-previous-" + "x" * 40


async def test_bad_paste_is_a_clear_422(auth_client, cli_ok) -> None:  # type: ignore[no-untyped-def]
    for name, text in (("claude-code", "hello"), ("codex", "{}")):
        response = await auth_client.post(f"/models/providers/{name}/token", json={"token": text})
        assert response.status_code == 422 and "detail" in response.json()


async def test_api_providers_have_no_token_import(auth_client) -> None:  # type: ignore[no-untyped-def]
    assert (await auth_client.post("/models/providers/openai/token", json={"token": "x"})).status_code == 422


async def test_codex_auth_is_installed_in_the_private_home_only(auth_client, app, settings, cli_ok) -> None:  # type: ignore[no-untyped-def]
    response = await auth_client.post("/models/providers/codex/token", json={"token": json.dumps(AUTH)})
    assert response.json()["state"] == "signed_in"
    target = settings.data_dir / "cli" / "codex" / "auth.json"
    assert json.loads(target.read_text())["tokens"]["refresh_token"] == "ref"
    assert "refresh" not in response.text.replace("refresh_token", "")  # no token echoed
    if os.name != "nt":
        assert oct(target.stat().st_mode)[-3:] == "600"  # owner only
    assert not target.with_name("auth.json.bak").exists()


async def test_failed_codex_import_puts_the_old_login_back(auth_client, app, settings, cli_ok) -> None:  # type: ignore[no-untyped-def]
    target = settings.data_dir / "cli" / "codex" / "auth.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"tokens": {"access_token": "OLD", "refresh_token": "OLD"}}))
    cli_ok["signed_in"] = False
    body = (await auth_client.post("/models/providers/codex/token", json={"token": json.dumps(AUTH)})).json()
    assert body["state"] == "failed"
    assert json.loads(target.read_text())["tokens"]["access_token"] == "OLD"  # restored
    assert not target.with_name("auth.json.bak").exists()


async def test_not_installed_cli_is_reported(auth_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("elysium_engine.providers.registry.find_binary", lambda _n: None)
    body = (await auth_client.post("/models/providers/claude-code/token", json={"token": TOKEN})).json()
    assert body["state"] == "not_installed"


async def test_signing_out_removes_the_imported_token(auth_client, app, cli_ok, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    await auth_client.post("/models/providers/claude-code/token", json={"token": TOKEN})
    assert app.state.secret_store.get(CLAUDE_TOKEN_KEY) == TOKEN
    monkeypatch.setattr("elysium_engine.providers.cli_common.run_blocking", lambda argv, *a, **k: (0, ""))
    monkeypatch.setattr("elysium_engine.providers.claude_code.logout_argv", lambda: ["claude", "auth", "logout"])
    assert (await auth_client.post("/models/providers/claude-code/logout")).json()["state"] == "signed_out"
    assert app.state.secret_store.get(CLAUDE_TOKEN_KEY) is None
