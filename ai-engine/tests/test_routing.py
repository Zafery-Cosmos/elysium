"""select_model: tier preference, fallback chain, context and budget handling."""

from __future__ import annotations

import pytest

from elysium_engine.routing import ModelOption, NoModelAvailableError, select_model

FAST = ModelOption("acme", "mini", "fast", 128_000, 0.1, 0.4)
BALANCED = ModelOption("acme", "medium", "balanced", 200_000, 3.0, 15.0)
POWERFUL = ModelOption("acme", "large", "powerful", 200_000, 15.0, 75.0)
LOCAL_FAST = ModelOption("ollama", "llama3.1:8b", "fast", 131_072, 0.0, 0.0)
SMALL_CONTEXT = ModelOption("acme", "tiny", "fast", 8_000, 0.05, 0.1)

ALL = [FAST, BALANCED, POWERFUL, LOCAL_FAST, SMALL_CONTEXT]


def test_simple_task_routes_to_cheapest_fast_model() -> None:
    assert select_model("simple", 1_000, None, ALL) == LOCAL_FAST


def test_architecture_task_routes_to_powerful_model() -> None:
    assert select_model("architecture", 1_000, None, ALL) == POWERFUL


def test_general_task_prefers_balanced() -> None:
    assert select_model("general", 1_000, None, ALL) == BALANCED


def test_fallback_chain_when_preferred_tier_unavailable() -> None:
    # No powerful model available -> architecture falls back to balanced...
    assert select_model("architecture", 1_000, None, [FAST, BALANCED]) == BALANCED
    # ...and to fast when balanced is gone too.
    assert select_model("architecture", 1_000, None, [FAST]) == FAST


def test_context_requirement_filters_small_models() -> None:
    choice = select_model("simple", 50_000, None, ALL)
    assert choice.context_window >= 50_000
    assert choice != SMALL_CONTEXT


def test_context_overflow_degrades_to_largest_window() -> None:
    # Nothing fits 1M tokens: pick among the largest windows, deterministically.
    choice = select_model("architecture", 1_000_000, None, ALL)
    assert choice.context_window == 200_000


def test_budget_excludes_expensive_models() -> None:
    choice = select_model("architecture", 1_000, 10.0, ALL)
    assert choice != POWERFUL  # blended cost 30.0 > 10.0
    assert choice == BALANCED  # blended cost 6.0


def test_budget_impossible_falls_back_to_cheapest() -> None:
    choice = select_model("architecture", 1_000, 0.000001, [BALANCED, POWERFUL])
    assert choice == BALANCED


def test_no_options_raises() -> None:
    with pytest.raises(NoModelAvailableError):
        select_model("simple", 100, None, [])


def test_deterministic_tie_break() -> None:
    a = ModelOption("aaa", "model", "fast", 100_000, 1.0, 1.0)
    b = ModelOption("bbb", "model", "fast", 100_000, 1.0, 1.0)
    assert select_model("simple", 100, None, [b, a]) == a
    assert select_model("simple", 100, None, [a, b]) == a
