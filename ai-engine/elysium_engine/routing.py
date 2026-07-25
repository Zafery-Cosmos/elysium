"""Deterministic model routing (ADR-004).

``select_model`` is a *pure* function over
``(task class, estimated context size, cost budget, available options)`` and
returns the provider+model Elysium should use:

- simple tasks route to fast/cheap models,
- architecture-level tasks route to the most capable models,
- unavailable providers are handled by the tier fallback chain — if the
  preferred tier has no available option, the next tier is tried, and so on.

No I/O, no globals: the caller supplies the currently *available* options
(configured providers only), which makes this fully unit-testable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

TaskClass = Literal["simple", "general", "code", "architecture"]
Tier = Literal["fast", "balanced", "powerful"]


@dataclass(frozen=True, slots=True)
class ModelOption:
    """One routable provider+model with the metadata routing needs."""

    provider: str
    model: str
    tier: Tier
    context_window: int
    input_cost: float  # USD per million input tokens (0.0 for local models)
    output_cost: float  # USD per million output tokens


class NoModelAvailableError(RuntimeError):
    """Raised when no provider at all is configured/available."""


# Fallback chains: first tier is the ideal fit for the task class, the rest
# are tried in order when the preferred tier has no available option.
_TIER_PREFERENCE: dict[TaskClass, tuple[Tier, ...]] = {
    "simple": ("fast", "balanced", "powerful"),
    "general": ("balanced", "fast", "powerful"),
    "code": ("balanced", "powerful", "fast"),
    "architecture": ("powerful", "balanced", "fast"),
}


def blended_cost(option: ModelOption) -> float:
    """USD per Mtok, weighted 3:1 input:output (agent traffic is input-heavy)."""
    return (3.0 * option.input_cost + option.output_cost) / 4.0


def select_model(
    task_class: TaskClass,
    est_context_tokens: int,
    budget: float | None,
    available: Sequence[ModelOption],
) -> ModelOption:
    """Pick the best available model for a task. Deterministic.

    ``budget`` is a soft ceiling on :func:`blended_cost` (USD/Mtok); ``None``
    means unconstrained.  Degradation order when constraints cannot all be
    met: over-budget beats no-model, and the largest available context window
    is used when nothing fits ``est_context_tokens``.
    """
    if not available:
        raise NoModelAvailableError(
            "No model provider is configured. Add one via PUT /models/providers/{name}."
        )

    fits = [o for o in available if o.context_window >= est_context_tokens]
    if not fits:
        best_window = max(o.context_window for o in available)
        fits = [o for o in available if o.context_window == best_window]

    in_budget = [o for o in fits if budget is None or blended_cost(o) <= budget]
    pool = in_budget if in_budget else [min(fits, key=_sort_key)]

    for tier in _TIER_PREFERENCE[task_class]:
        tier_pool = [o for o in pool if o.tier == tier]
        if tier_pool:
            return min(tier_pool, key=_sort_key)
    # Option with a tier outside the known set: still deterministic.
    return min(pool, key=_sort_key)


def _sort_key(option: ModelOption) -> tuple[float, str, str]:
    return (blended_cost(option), option.provider, option.model)
