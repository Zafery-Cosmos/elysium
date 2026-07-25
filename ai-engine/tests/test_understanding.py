"""coverage() heuristic: weighted fraction of filled checklist items."""

from __future__ import annotations

import pytest

from elysium_engine.agents.understanding import (
    CHECKLIST_WEIGHTS,
    coverage,
    is_filled,
    is_sufficient,
)

TOTAL_WEIGHT = sum(CHECKLIST_WEIGHTS.values())


def test_empty_checklist_is_zero() -> None:
    assert coverage({}) == 0.0


def test_all_filled_is_one() -> None:
    checklist = {key: "answered" for key in CHECKLIST_WEIGHTS}
    assert coverage(checklist) == pytest.approx(1.0)


def test_partial_coverage_is_weighted() -> None:
    assert coverage({"core_features": "booking + reviews"}) == pytest.approx(
        CHECKLIST_WEIGHTS["core_features"] / TOTAL_WEIGHT
    )
    assert coverage({"integrations": "stripe"}) == pytest.approx(
        CHECKLIST_WEIGHTS["integrations"] / TOTAL_WEIGHT
    )


def test_null_and_placeholder_values_do_not_count() -> None:
    checklist = {
        "target_users": None,
        "core_features": "",
        "auth": "   ",
        "platforms": "unknown",
        "data": [],
        "business_model": False,
    }
    assert coverage(checklist) == 0.0


def test_extra_keys_count_with_default_weight() -> None:
    assert coverage({"branding": "green, friendly"}) == pytest.approx(
        1.0 / (TOTAL_WEIGHT + 1.0)
    )


def test_is_filled_various_types() -> None:
    assert is_filled("web and mobile")
    assert is_filled(["a", "b"])
    assert is_filled(42)
    assert is_filled(True)
    assert not is_filled(None)
    assert not is_filled("null")
    assert not is_filled({})


def test_is_sufficient_threshold() -> None:
    keys = list(CHECKLIST_WEIGHTS)
    assert not is_sufficient({})
    assert is_sufficient({key: "yes" for key in keys})
    # target_users + core_features alone (5.0/11.0) is not enough.
    assert not is_sufficient({"target_users": "families", "core_features": "booking"})
