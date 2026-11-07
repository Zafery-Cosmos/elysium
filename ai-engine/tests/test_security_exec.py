"""Security of CLI execution and of folder scanning."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from elysium_engine import importer
from elysium_engine.parent_watch import pid_alive
from elysium_engine.providers import cli_common
from elysium_engine.providers.base import ProviderError


async def _drain(argv: list[str], **kw) -> list[str]:  # type: ignore[no-untyped-def]
    return [line async for line in cli_common.stream_lines(argv, "", Path.cwd(), label="t", **kw)]


# ------------------------------------------------------------------ environment


def test_child_environment_is_an_allow_list(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for name, value in {
        "ANTHROPIC_API_KEY": "sk-ant-secret",
        "OPENAI_API_KEY": "sk-secret",
        "GITHUB_TOKEN": "ghp_secret",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "DATABASE_URL": "postgres://u:p@h/db",
        "ELYSIUM_TOKEN": "engine-session-token",
        "HTTPS_PROXY": "http://proxy:3128",
    }.items():
        monkeypatch.setenv(name, value)
    env = cli_common._clean_env()
    leaked = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "DATABASE_URL", "ELYSIUM_TOKEN"}
    assert leaked.isdisjoint({k.upper() for k in env})
    assert env["HTTPS_PROXY"] == "http://proxy:3128"  # what the network needs still passes
    assert "PATH" in {k.upper() for k in env}


async def test_the_running_child_really_has_no_secrets(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setenv("ELYSIUM_TOKEN", "engine-session-token")
    code = "import os; print(sorted(k for k in os.environ if 'TOKEN' in k or 'KEY' in k))"
    assert await _drain([sys.executable, "-c", code]) == ["[]"]


# ------------------------------------------------------------------ output limits


async def test_runaway_output_is_stopped(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli_common, "MAX_OUTPUT_BYTES", 5_000)
    code = "import sys\nfor i in range(100000):\n    print('x' * 100); sys.stdout.flush()"
    with pytest.raises(ProviderError, match="output exceeded"):
        await _drain([sys.executable, "-c", code], timeout_s=30)


async def test_stderr_is_bounded_and_secrets_are_redacted() -> None:
    secret = "sk-ant-api03-" + "A1b2C3d4E5" * 5
    code = (
        "import sys\n"
        f"sys.stderr.write('x' * 300000 + ' key={secret}')\n"
        "sys.exit(1)"
    )
    with pytest.raises(ProviderError) as exc:
        await _drain([sys.executable, "-c", code])
    message = str(exc.value)
    assert secret not in message and len(message) < 1000


async def test_hanging_cli_times_out_and_is_killed() -> None:
    code = "import time; print('started', flush=True); time.sleep(60)"
    started = time.monotonic()
    with pytest.raises(ProviderError, match="timed out"):
        await _drain([sys.executable, "-c", code], timeout_s=1.5)
    assert time.monotonic() - started < 15


async def test_cancelling_a_call_kills_the_whole_process_tree() -> None:
    parent = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(120)\n"
    )
    stream = cli_common.stream_lines([sys.executable, "-c", parent], "", Path.cwd(), label="t")
    child_pid = int(await stream.__anext__())
    assert pid_alive(child_pid)
    await stream.aclose()  # the consumer walks away (cancelled request)
    for _ in range(50):
        if not pid_alive(child_pid):
            break
        time.sleep(0.1)
    assert not pid_alive(child_pid)  # the grandchild did not survive


# --------------------------------------------------------------- folder scanning


def test_scan_refuses_system_and_root_folders(tmp_path: Path) -> None:
    for bad in (Path(tmp_path.anchor), Path(os.environ.get("WINDIR", "/etc")), Path.home()):
        with pytest.raises(importer.ImportError_):
            importer.scan_folder(bad)
    with pytest.raises(importer.ImportError_):
        importer.scan_folder("relative/folder")


def test_scan_does_not_follow_symlinks_out_of_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("print(1)\n")
    outside = tmp_path / "secret.txt"
    outside.write_text("do not index me\n" * 100)
    (tmp_path / "readme-target.md").write_text("# outside readme")
    try:
        os.symlink(outside, project / "leak.txt")
        os.symlink(tmp_path / "readme-target.md", project / "README.md")
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    summary = importer.scan_folder(project)
    assert [f.path for f in summary.tree] == ["main.py"]  # the symlinked file is not listed
    assert summary.readme_excerpt is None  # nor is a README that points outside
    assert summary.stats.skipped_files >= 1
