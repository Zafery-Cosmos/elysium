"""Repository layer — the only place business code touches the ORM (ADR-001)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from elysium_engine.db.models import (
    AgentRecord,
    AppSettingsRecord,
    Conversation,
    Event,
    McpServer,
    Memory,
    Message,
    Project,
    ProviderRecord,
    Task,
)

APP_SETTINGS_ROW_ID = 1


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def list(self, include_archived: bool = False) -> Sequence[Project]:
        stmt = select(Project).order_by(Project.created_at)
        if not include_archived:
            stmt = stmt.where(Project.status != "archived")
        return self._s.scalars(stmt).all()

    def get(self, project_id: str) -> Project | None:
        return self._s.get(Project, project_id)

    def create(self, name: str, description: str = "") -> Project:
        project = Project(name=name, description=description)
        self._s.add(project)
        self._s.commit()
        return project

    def update(
        self,
        project: Project,
        *,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> Project:
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if status is not None:
            project.status = status
        self._s.commit()
        return project

    def archive(self, project: Project) -> None:
        # DELETE archives rather than destroys: user actions stay reversible.
        project.status = "archived"
        self._s.commit()


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def list_for_project(self, project_id: str) -> Sequence[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.project_id == project_id)
            .order_by(Conversation.created_at)
        )
        return self._s.scalars(stmt).all()

    def get(self, conversation_id: str) -> Conversation | None:
        return self._s.get(Conversation, conversation_id)

    def create(self, project_id: str, title: str = "New conversation") -> Conversation:
        conversation = Conversation(project_id=project_id, title=title)
        self._s.add(conversation)
        self._s.commit()
        return conversation


class MessageRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def list_for_conversation(self, conversation_id: str) -> Sequence[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        return self._s.scalars(stmt).all()

    def add(
        self,
        conversation_id: str,
        role: str,
        content: str,
        agent_name: str | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            agent_name=agent_name,
        )
        self._s.add(message)
        self._s.commit()
        return message


class EventRepository:
    """Append-only: no update or delete methods, by design (ADR-005)."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def append(
        self,
        conversation_id: str,
        type_: str,
        payload: dict[str, Any],
        agent_name: str | None = None,
    ) -> Event:
        event = Event(
            conversation_id=conversation_id,
            type=type_,
            payload=payload,
            agent_name=agent_name,
        )
        self._s.add(event)
        self._s.commit()
        return event

    def list_for_conversation(self, conversation_id: str, after_id: int = 0) -> Sequence[Event]:
        stmt = (
            select(Event)
            .where(Event.conversation_id == conversation_id, Event.id > after_id)
            .order_by(Event.id)
        )
        return self._s.scalars(stmt).all()


class AgentRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def list_for_project(self, project_id: str) -> Sequence[AgentRecord]:
        stmt = (
            select(AgentRecord)
            .where(AgentRecord.project_id == project_id)
            .order_by(AgentRecord.created_at)
        )
        return self._s.scalars(stmt).all()

    def get_by_role(self, project_id: str, role: str) -> AgentRecord | None:
        return self._s.scalars(
            select(AgentRecord).where(
                AgentRecord.project_id == project_id, AgentRecord.role == role
            )
        ).first()

    def get_by_role_or_name(self, project_id: str, ident: str) -> AgentRecord | None:
        """Resolve an agent by its ``role`` (built-ins) or ``name`` slug (custom)."""
        return self._s.scalars(
            select(AgentRecord).where(
                AgentRecord.project_id == project_id,
                (AgentRecord.role == ident) | (AgentRecord.name == ident),
            )
        ).first()

    def role_identifiers(self, project_id: str) -> set[str]:
        """Every addressable owner for a task: each agent's ``role`` and ``name``.

        Used to validate a task's ``agent_role`` against the project roster
        (built-in roles + custom agent names).
        """
        identifiers: set[str] = set()
        for record in self.list_for_project(project_id):
            identifiers.add(record.role)
            identifiers.add(record.name)
        return identifiers

    def create(
        self,
        project_id: str,
        *,
        name: str,
        role: str,
        model_ref: str,
        system_prompt: str,
        allowed_tools: list[str],
        permissions: list[str],
        filesystem: str = "none",
        shell: bool = False,
        network: bool = False,
        enabled: bool = True,
        custom: bool = False,
    ) -> AgentRecord:
        record = AgentRecord(
            project_id=project_id,
            name=name,
            role=role,
            model_ref=model_ref,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            permissions=permissions,
            filesystem=filesystem,
            shell=shell,
            network=network,
            enabled=enabled,
            custom=custom,
        )
        self._s.add(record)
        self._s.commit()
        return record

    def update_permissions(
        self,
        record: AgentRecord,
        *,
        filesystem: str | None = None,
        shell: bool | None = None,
        network: bool | None = None,
        allowed_tools: list[str] | None = None,
        enabled: bool | None = None,
    ) -> AgentRecord:
        if filesystem is not None:
            record.filesystem = filesystem
        if shell is not None:
            record.shell = shell
        if network is not None:
            record.network = network
        if allowed_tools is not None:
            record.allowed_tools = allowed_tools
        if enabled is not None:
            record.enabled = enabled
        self._s.commit()
        return record

    def delete(self, record: AgentRecord) -> None:
        self._s.delete(record)
        self._s.commit()


class TaskRepository:
    """Persisted task-graph CRUD (ADR-005).

    Ordering is Kanban-friendly: ``(status, order_index, created_at)`` so a
    board can render each column in stable order.
    """

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, task_id: str) -> Task | None:
        return self._s.get(Task, task_id)

    def list_by_project(self, project_id: str) -> Sequence[Task]:
        stmt = (
            select(Task)
            .where(Task.project_id == project_id)
            .order_by(Task.status, Task.order_index, Task.created_at)
        )
        return self._s.scalars(stmt).all()

    # Backwards-compatible alias.
    list_for_project = list_by_project

    def list_by_conversation(self, conversation_id: str) -> Sequence[Task]:
        stmt = (
            select(Task)
            .where(Task.conversation_id == conversation_id)
            .order_by(Task.status, Task.order_index, Task.created_at)
        )
        return self._s.scalars(stmt).all()

    def _next_order_index(self, project_id: str) -> int:
        stmt = select(Task.order_index).where(Task.project_id == project_id)
        existing = list(self._s.scalars(stmt).all())
        return (max(existing) + 1) if existing else 0

    def create(
        self,
        project_id: str,
        title: str,
        agent_role: str,
        *,
        description: str = "",
        status: str = "todo",
        conversation_id: str | None = None,
        depends_on: list[str] | None = None,
        order_index: int | None = None,
    ) -> Task:
        task = Task(
            project_id=project_id,
            conversation_id=conversation_id,
            title=title,
            description=description,
            agent_role=agent_role,
            status=status,
            depends_on=list(depends_on) if depends_on is not None else [],
            order_index=(
                order_index if order_index is not None else self._next_order_index(project_id)
            ),
        )
        self._s.add(task)
        self._s.commit()
        return task

    def update(
        self,
        task: Task,
        *,
        title: str | None = None,
        description: str | None = None,
        agent_role: str | None = None,
        status: str | None = None,
        order_index: int | None = None,
        result_summary: str | None = None,
        depends_on: list[str] | None = None,
    ) -> Task:
        if title is not None:
            task.title = title
        if description is not None:
            task.description = description
        if agent_role is not None:
            task.agent_role = agent_role
        if status is not None:
            task.status = status
        if order_index is not None:
            task.order_index = order_index
        if result_summary is not None:
            task.result_summary = result_summary
        if depends_on is not None:
            task.depends_on = list(depends_on)
        self._s.commit()
        return task

    def delete(self, task: Task) -> None:
        self._s.delete(task)
        self._s.commit()

    def reorder(self, project_id: str, ordered_ids_per_status: dict[str, list[str]]) -> None:
        """Apply a Kanban board layout: {status: [task_id, ...ordered]}.

        Each listed task (scoped to ``project_id``) gets its ``status`` and a
        fresh ``order_index`` from its position in the column.  Unlisted tasks
        are left untouched.
        """
        for new_status, ids in ordered_ids_per_status.items():
            for index, task_id in enumerate(ids):
                task = self._s.get(Task, task_id)
                if task is None or task.project_id != project_id:
                    continue
                task.status = new_status
                task.order_index = index
        self._s.commit()


class MemoryRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def list_for_project(self, project_id: str, kind: str | None = None) -> Sequence[Memory]:
        stmt = select(Memory).where(Memory.project_id == project_id).order_by(Memory.created_at)
        if kind is not None:
            stmt = stmt.where(Memory.kind == kind)
        return self._s.scalars(stmt).all()

    def add(
        self,
        project_id: str,
        kind: str,
        content: str,
        embedding: bytes | None = None,
    ) -> Memory:
        memory = Memory(project_id=project_id, kind=kind, content=content, embedding=embedding)
        self._s.add(memory)
        self._s.commit()
        return memory


class McpServerRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def list(self) -> Sequence[McpServer]:
        return self._s.scalars(select(McpServer).order_by(McpServer.created_at)).all()

    def get(self, server_id: str) -> McpServer | None:
        return self._s.get(McpServer, server_id)

    def get_by_catalog_id(self, catalog_id: str) -> McpServer | None:
        return self._s.scalars(
            select(McpServer).where(McpServer.catalog_id == catalog_id)
        ).first()

    def create(
        self,
        *,
        name: str,
        url_or_command: str,
        transport: str,
        description: str = "",
        catalog_id: str | None = None,
    ) -> McpServer:
        server = McpServer(
            catalog_id=catalog_id,
            name=name,
            description=description,
            url_or_command=url_or_command,
            transport=transport,
        )
        self._s.add(server)
        self._s.commit()
        return server

    def set_enabled(self, server: McpServer, enabled: bool) -> McpServer:
        server.enabled = enabled
        self._s.commit()
        return server

    def update(
        self,
        server: McpServer,
        *,
        enabled: bool | None = None,
        name: str | None = None,
        url_or_command: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> McpServer:
        if enabled is not None:
            server.enabled = enabled
        if name is not None:
            server.name = name
        if url_or_command is not None:
            server.url_or_command = url_or_command
        if config is not None:
            server.config = config
        self._s.commit()
        return server

    def delete(self, server: McpServer) -> None:
        self._s.delete(server)
        self._s.commit()


class ProviderRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def list(self) -> Sequence[ProviderRecord]:
        return self._s.scalars(select(ProviderRecord).order_by(ProviderRecord.name)).all()

    def get_by_name(self, name: str) -> ProviderRecord | None:
        return self._s.scalars(select(ProviderRecord).where(ProviderRecord.name == name)).first()

    def upsert(
        self,
        name: str,
        *,
        base_url: str,
        default_model: str,
        is_local: bool,
    ) -> ProviderRecord:
        record = self.get_by_name(name)
        if record is None:
            record = ProviderRecord(
                name=name, base_url=base_url, default_model=default_model, is_local=is_local
            )
            self._s.add(record)
        else:
            record.base_url = base_url
            record.default_model = default_model
            record.is_local = is_local
        self._s.commit()
        return record


class AppSettingsRepository:
    """Single-row user-preferences store (id fixed to 1)."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get_data(self) -> dict[str, Any]:
        """Raw persisted JSON ({} when nothing has been saved yet)."""
        record = self._s.get(AppSettingsRecord, APP_SETTINGS_ROW_ID)
        return dict(record.data) if record is not None else {}

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        record = self._s.get(AppSettingsRecord, APP_SETTINGS_ROW_ID)
        if record is None:
            record = AppSettingsRecord(id=APP_SETTINGS_ROW_ID, data=data)
            self._s.add(record)
        else:
            record.data = data
        self._s.commit()
        return dict(record.data)
