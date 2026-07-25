"""PM reply post-processing: checklist extraction and the decision event."""

from __future__ import annotations

from elysium_engine.agents.project_manager import (
    parse_checklist,
    pm_finalizer,
    strip_checklist,
)

REPLY = (
    "Great idea! Two quick questions:\n"
    "1. Who is this for?\n"
    "2. Should it work on phones?\n"
    '<checklist>{"target_users": null, "core_features": "book restaurants", '
    '"auth": null, "platforms": null, "data": null, "business_model": null, '
    '"integrations": null, "constraints": null}</checklist>'
)


def test_parse_checklist_extracts_json() -> None:
    checklist = parse_checklist(REPLY)
    assert checklist is not None
    assert checklist["core_features"] == "book restaurants"
    assert checklist["target_users"] is None


def test_parse_checklist_handles_missing_or_broken_block() -> None:
    assert parse_checklist("no block here") is None
    assert parse_checklist("<checklist>{broken</checklist>") is None


def test_strip_checklist_removes_machine_block() -> None:
    stripped = strip_checklist(REPLY)
    assert "<checklist>" not in stripped
    assert "Who is this for?" in stripped


def test_pm_finalizer_emits_understanding_decision() -> None:
    events = pm_finalizer(REPLY)
    assert len(events) == 1
    event_type, payload = events[0]
    assert event_type == "decision"
    assert payload["kind"] == "understanding_update"
    assert 0.0 < payload["coverage"] < 1.0
    assert payload["sufficient"] is False


def test_pm_finalizer_without_block_emits_nothing() -> None:
    assert pm_finalizer("plain reply") == []
