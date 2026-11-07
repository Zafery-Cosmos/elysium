"""SQLAlchemy 2.0 ORM models.

Works on SQLite (default) and PostgreSQL (ADR-001).  Embeddings are stored as
BLOB with brute-force cosine search on SQLite; pgvector is the Postgres path.
Provider API keys are NEVER stored here — they live in the OS keychain.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    agents: Mapped[list["AgentRecord"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class AgentRecord(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(100))
    model_ref: Mapped[str] = mapped_column(String(200), default="auto")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Least-privilege permission profile (AI_SYSTEM.md §1). ``filesystem`` is
    # none | read | read_write; ``shell``/``network`` gate command execution
    # and outbound calls. Effective policy is still enforced by the Rust broker.
    filesystem: Mapped[str] = mapped_column(String(20), default="none")
    shell: Mapped[bool] = mapped_column(Boolean, default=False)
    network: Mapped[bool] = mapped_column(Boolean, default=False)
    # ``enabled`` gates whether the agent participates in a run; ``custom`` is
    # True for user-created agents (deletable) and False for the 8 built-ins.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    custom: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="agents")


class Task(Base):
    """Node of the persisted task graph the PM agent maintains (ADR-005).

    Nodes carry the owning ``agent_role`` (a built-in role or a custom agent
    name), a Kanban ``status`` and ``order_index`` (position within a column),
    and ``depends_on`` (a JSON list of task ids — the graph edges).  The
    orchestrator loop (a later phase) activates a task only once all its
    dependencies are ``done``.  ``result_summary`` is filled by the owning
    agent when it completes the task.
    """

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    # Nullable: tasks may be seeded by a plan turn (linked to the conversation)
    # or created directly on the board (no conversation).
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    # Which roster role/agent owns the task (validated against the project roster).
    agent_role: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(
        String(20), default="todo"
    )  # todo | in_progress | done | blocked
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    # Dependency edges: task ids this task waits on (same project).
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50))  # decision | fact | preference | summary
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    """Append-only agent event log (ADR-005).

    The integer primary key doubles as a strict ordering / SSE ``id`` for
    replay.  Rows are never updated or deleted.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UsageRecord(Base):
    """One model call: who answered, how many tokens, how long, did it fail.

    Feeds the admin dashboard. Plain string ids (no foreign keys): usage history
    must survive deleting the conversation or project it came from.
    """

    __tablename__ = "usage"
    # A real (named) unique index, so it can also be added to an existing table.
    __table_args__ = (Index("ix_usage_request_id", "request_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    provider: Mapped[str] = mapped_column(String(100), index=True)
    model: Mapped[str] = mapped_column(String(200))
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # API-equivalent cost reported by CLI providers; None when unknown.
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="ok")  # ok | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # --- accounting (migration 0010) -------------------------------------
    # Idempotency key: writing the same call twice never double-counts.
    request_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # How the call is paid: api (per token) | subscription (CLI plan) | local.
    billing: Mapped[str] = mapped_column(String(12), default="api")
    # reported (vendor figure) | estimated (catalog rates x tokens) | none (unknown).
    cost_kind: Mapped[str] = mapped_column(String(10), default="none")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # EUR figure converted with the rate in force at call time (fx_rate), so the
    # history never changes when the rate does.
    cost_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    fx_rate: Mapped[float | None] = mapped_column(Float, nullable=True)


class FxRate(Base):
    """USD->EUR rate history: every change adds a row, nothing is overwritten."""

    __tablename__ = "fx_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    base: Mapped[str] = mapped_column(String(3), default="USD")
    quote: Mapped[str] = mapped_column(String(3), default="EUR")
    rate: Mapped[float] = mapped_column(Float)
    # user | ecb (fetched on request) | default (built-in, not live).
    source: Mapped[str] = mapped_column(String(60), default="default")
    as_of: Mapped[str] = mapped_column(String(10))  # ISO date the rate is valid for
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class QuotaReading(Base):
    """Latest subscription-quota reading per (provider, window), persisted."""

    __tablename__ = "quota_readings"

    provider: Mapped[str] = mapped_column(String(100), primary_key=True)
    window: Mapped[str] = mapped_column(String(40), primary_key=True)
    utilization: Mapped[float] = mapped_column(Float)
    resets_at: Mapped[float | None] = mapped_column(Float, nullable=True)  # epoch seconds
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PreviewRecord(Base):
    """Last known live-preview state of a project (one row per project).

    Rows are reconciled at engine start: a process recorded here is never
    assumed to be alive (see ``preview.manager.PreviewManager.reconcile``).
    """

    __tablename__ = "preview_sessions"

    project_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    root_path: Mapped[str] = mapped_column(Text)
    subdir: Mapped[str | None] = mapped_column(String(300), nullable=True)
    framework: Mapped[str | None] = mapped_column(String(30), nullable=True)
    trusted: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(20), default="stopped")
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ProviderRecord(Base):
    """Provider configuration — API keys deliberately have no column here."""

    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    base_url: Mapped[str] = mapped_column(String(500))
    default_model: Mapped[str] = mapped_column(String(200), default="")
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class McpServer(Base):
    """Installed MCP server (v0: persisted configuration only).

    ``catalog_id`` links back to the curated marketplace entry
    (``elysium_engine.mcp.catalog``); it is NULL for custom servers the user
    registered manually.  The runtime MCP client lands in a later phase.
    """

    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    catalog_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    url_or_command: Mapped[str] = mapped_column(Text)
    transport: Mapped[str] = mapped_column(String(20))  # stdio | http
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Non-secret configuration values keyed by ``config_schema`` field key.
    # ``type: "secret"`` fields are stored in the OS keychain, NEVER here.
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AppSettingsRecord(Base):
    """Single-row (id fixed to 1) key/value JSON store of user preferences.

    The validated shape lives in :mod:`elysium_engine.app_settings`; this row
    only persists the JSON document + a mtime.
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
