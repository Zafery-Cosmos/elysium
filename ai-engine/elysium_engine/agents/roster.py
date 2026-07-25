"""The fixed V1 agent roster with least-privilege permission profiles.

The roster and its default permission profiles mirror ``AI_SYSTEM.md`` §1.
Profiles are *defaults*: the effective policy is always enforced by the Rust
permission broker (ADR-003), and the user can tighten/loosen a role via
``PATCH /agents/{role}/permissions``.  Every project is seeded with these
eight agents on creation.
"""

from __future__ import annotations

from elysium_engine.agents.base import Agent
from elysium_engine.agents.project_manager import build_project_manager

# ``filesystem`` is none | read | read_write; ``shell`` gates command
# execution, ``network`` gates outbound calls. The PM is defined by
# ``build_project_manager`` (its prompt has three chat-mode variants); the
# other roles carry a short role prompt — the code-generation prompts proper
# land with the orchestrator phase.

_ARCHITECT = Agent(
    name="architect",
    role="Architect",
    model_ref="auto",
    system_prompt=(
        "You are the Architect of an AI development team. You propose system "
        "designs, tech-stack options and module boundaries. You never write "
        "application code or run commands; you produce decisions and diagrams "
        "as data for the Project Manager to arbitrate."
    ),
    allowed_tools=("fs_read", "memory", "web_search"),
    permissions=("fs_read", "memory_read", "memory_write"),
    filesystem="read",
    shell=False,
    network=False,
)

_FRONTEND = Agent(
    name="frontend",
    role="Frontend",
    model_ref="auto",
    system_prompt=(
        "You are the Frontend developer. You implement UI components, styling "
        "and client state. Your file writes are diff-gated and confined to the "
        "frontend paths of the project."
    ),
    allowed_tools=("fs_read", "fs_write", "package_scripts"),
    permissions=("fs_read", "fs_write"),
    filesystem="read_write",
    shell=False,
    network=False,
)

_BACKEND = Agent(
    name="backend",
    role="Backend",
    model_ref="auto",
    system_prompt=(
        "You are the Backend developer. You implement APIs, business logic and "
        "services. Your file writes are diff-gated; tests run in a sandbox."
    ),
    allowed_tools=("fs_read", "fs_write", "test_runner"),
    permissions=("fs_read", "fs_write"),
    filesystem="read_write",
    shell=False,
    network=False,
)

_DATABASE = Agent(
    name="database",
    role="Database",
    model_ref="auto",
    system_prompt=(
        "You are the Database engineer. You design schemas, write migrations "
        "and queries. Writes are confined to the migrations directory; the "
        "migration runner is approval-gated."
    ),
    allowed_tools=("fs_read", "fs_write", "migration_runner"),
    permissions=("fs_read", "fs_write"),
    filesystem="read_write",
    shell=False,
    network=False,
)

_DEVOPS = Agent(
    name="devops",
    role="DevOps",
    model_ref="auto",
    system_prompt=(
        "You are the DevOps engineer. You handle build config, CI, Docker "
        "files and environment setup. Elevated actions (commands) are always "
        "confirmed by the user before running."
    ),
    allowed_tools=("fs_read", "fs_write", "command_proposals"),
    permissions=("fs_read", "fs_write", "shell", "network"),
    filesystem="read_write",
    shell=True,
    network=True,
)

_SECURITY = Agent(
    name="security",
    role="Security",
    model_ref="auto",
    system_prompt=(
        "You are the Security reviewer. You review diffs and dependencies, "
        "flag secrets and injection risks, and vet MCP/tool additions. A "
        "reviewer must never modify what it reviews: you are read-only."
    ),
    allowed_tools=("fs_read", "dependency_metadata", "audit_log_read"),
    permissions=("fs_read", "audit_log_read"),
    filesystem="read",
    shell=False,
    network=False,
)

_QA = Agent(
    name="qa",
    role="QA",
    model_ref="auto",
    system_prompt=(
        "You are the QA engineer. You write test plans and test code and run "
        "tests in a sandbox, then report failures. Writes are confined to test "
        "directories; execution is sandbox-only."
    ),
    allowed_tools=("fs_read", "fs_write", "test_execution"),
    permissions=("fs_read", "fs_write", "shell"),
    filesystem="read_write",
    shell=True,
    network=False,
)


def default_roster() -> list[Agent]:
    """The eight V1 agents seeded on every new project (PM first)."""
    return [
        build_project_manager(),
        _ARCHITECT,
        _FRONTEND,
        _BACKEND,
        _DATABASE,
        _DEVOPS,
        _SECURITY,
        _QA,
    ]
