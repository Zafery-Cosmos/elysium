"""Persisted AppSettings: full round-trip, nested deep-merge, validation, reset."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from elysium_engine.app_settings import AppSettings, deep_merge, default_settings

GROUPS = ("general", "ai", "prompt_caching", "agents", "memory", "developer", "privacy")


def test_defaults_cover_every_group() -> None:
    data = default_settings().model_dump()
    assert set(data) == set(GROUPS)
    # A few sane defaults per the spec.
    assert data["general"]["language"] == "fr"
    assert data["general"]["theme"] == "light"
    assert data["ai"]["default_effort"] == "medium"
    assert data["ai"]["streaming"] is True
    assert data["ai"]["max_response_tokens"] == 8192
    assert data["prompt_caching"]["enabled"] is True
    assert data["privacy"]["redact_secrets_before_send"] is True
    assert data["privacy"]["telemetry"] is False


async def test_get_returns_full_nested_document(auth_client: AsyncClient) -> None:
    body = (await auth_client.get("/settings")).json()
    assert set(body) == set(GROUPS)
    assert body == default_settings().model_dump()


async def test_patch_round_trip_persists(auth_client: AsyncClient) -> None:
    patch = {"general": {"theme": "dark"}, "ai": {"max_response_tokens": 4096}}
    patched = (await auth_client.patch("/settings", json=patch)).json()
    assert patched["general"]["theme"] == "dark"
    assert patched["ai"]["max_response_tokens"] == 4096
    # Re-read: the change survived.
    reread = (await auth_client.get("/settings")).json()
    assert reread["general"]["theme"] == "dark"
    assert reread["ai"]["max_response_tokens"] == 4096


async def test_patch_nested_deep_merge_leaves_siblings_intact(
    auth_client: AsyncClient,
) -> None:
    # Patch a single field inside one group.
    await auth_client.patch("/settings", json={"ai": {"streaming": False}})
    body = (await auth_client.get("/settings")).json()
    assert body["ai"]["streaming"] is False
    # Sibling fields in the same group keep their defaults.
    assert body["ai"]["default_effort"] == "medium"
    assert body["ai"]["max_response_tokens"] == 8192
    assert body["ai"]["auto_routing"] is True
    # Other groups are entirely untouched.
    assert body["general"] == default_settings().model_dump()["general"]
    assert body["privacy"] == default_settings().model_dump()["privacy"]


async def test_patch_rejects_bad_enum(auth_client: AsyncClient) -> None:
    assert (
        await auth_client.patch("/settings", json={"general": {"theme": "neon"}})
    ).status_code == 422
    assert (
        await auth_client.patch("/settings", json={"developer": {"log_level": "trace"}})
    ).status_code == 422
    assert (
        await auth_client.patch(
            "/settings", json={"agents": {"require_human_approval_for": ["nope"]}}
        )
    ).status_code == 422


async def test_patch_rejects_unknown_field(auth_client: AsyncClient) -> None:
    assert (
        await auth_client.patch("/settings", json={"ai": {"made_up": 1}})
    ).status_code == 422


async def test_reset_restores_defaults(auth_client: AsyncClient) -> None:
    await auth_client.patch(
        "/settings", json={"general": {"theme": "dark"}, "privacy": {"telemetry": True}}
    )
    reset = (await auth_client.post("/settings/reset")).json()
    assert reset == default_settings().model_dump()
    assert (await auth_client.get("/settings")).json() == default_settings().model_dump()


def test_deep_merge_preserves_none_as_a_real_value() -> None:
    base = default_settings().model_dump()
    merged = deep_merge(base, {"ai": {"cost_guard_eur": None}})
    assert merged["ai"]["cost_guard_eur"] is None
    # Still validates as a full document.
    AppSettings.model_validate(merged)


# --------------------------------------------- expert_budgets (per-provider caps)


def test_expert_budgets_defaults_to_empty_dict() -> None:
    assert default_settings().ai.expert_budgets == {}


async def test_expert_budgets_round_trip(auth_client: AsyncClient) -> None:
    patch = {"ai": {"expert_budgets": {"openai": 5.0, "deepseek": 2.0, "anthropic": None}}}
    patched = (await auth_client.patch("/settings", json=patch)).json()
    assert patched["ai"]["expert_budgets"] == {
        "openai": 5.0,
        "deepseek": 2.0,
        "anthropic": None,
    }
    reread = (await auth_client.get("/settings")).json()
    assert reread["ai"]["expert_budgets"] == {
        "openai": 5.0,
        "deepseek": 2.0,
        "anthropic": None,
    }


async def test_expert_budgets_partial_patch_leaves_other_providers_intact(
    auth_client: AsyncClient,
) -> None:
    await auth_client.patch(
        "/settings",
        json={"ai": {"expert_budgets": {"openai": 5.0, "deepseek": 2.0}}},
    )
    # Patch only one provider's cap.
    patched = (
        await auth_client.patch(
            "/settings", json={"ai": {"expert_budgets": {"openai": 10.0}}}
        )
    ).json()
    assert patched["ai"]["expert_budgets"] == {"openai": 10.0, "deepseek": 2.0}


async def test_expert_budgets_null_means_unlimited(auth_client: AsyncClient) -> None:
    patched = (
        await auth_client.patch(
            "/settings", json={"ai": {"expert_budgets": {"openai": None}}}
        )
    ).json()
    assert patched["ai"]["expert_budgets"]["openai"] is None


def test_expert_budgets_rejects_negative_cap() -> None:
    with pytest.raises(ValidationError):
        AppSettings.model_validate(
            deep_merge(
                default_settings().model_dump(),
                {"ai": {"expert_budgets": {"openai": -1.0}}},
            )
        )
