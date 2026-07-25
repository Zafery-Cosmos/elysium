"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    version: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=200)


class ConversationOut(BaseModel):
    id: str
    project_id: str
    title: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    content: str = Field(min_length=1)


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    agent_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageAccepted(BaseModel):
    id: str
    conversation_id: str
    status: str = "accepted"


class ModelOut(BaseModel):
    id: str
    context_window: int
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    tier: str


class ProviderOut(BaseModel):
    name: str
    kind: str
    base_url: str
    default_model: str
    is_local: bool
    configured: bool
    reachable: bool | None = None  # None unless probed (?probe=1)
    models: list[ModelOut]


class ModelsOut(BaseModel):
    providers: list[ProviderOut]


class ProviderConfigIn(BaseModel):
    base_url: str | None = None
    default_model: str | None = None
    is_local: bool | None = None
    # Write-only: stored in the OS keychain, never persisted to DB or echoed.
    api_key: str | None = None


class AgentOut(BaseModel):
    id: str | None = None
    name: str
    role: str
    model_ref: str
    allowed_tools: list[str]
    permissions: list[str]


class EventOut(BaseModel):
    id: int
    type: str
    agent: str | None
    payload: dict[str, Any]
