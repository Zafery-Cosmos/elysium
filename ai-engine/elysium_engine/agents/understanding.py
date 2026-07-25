"""Requirements-coverage heuristic behind the "Compréhension %" indicator.

IMPORTANT: :func:`coverage` is a **heuristic** — a weighted fraction of filled
requirements-checklist items — and NOT a model-derived probability (ADR-005).
It answers "how much of the standard requirements checklist has the user
covered so far?", nothing more.  The UI must present it as understanding
progress, never as confidence that the resulting software will be correct.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

# Standard requirements checklist the PM agent maintains, with weights
# reflecting how much each item shapes the project.
CHECKLIST_WEIGHTS: Final[Mapping[str, float]] = {
    "target_users": 2.0,
    "core_features": 3.0,
    "auth": 1.0,
    "platforms": 1.5,
    "data": 1.5,
    "business_model": 1.0,
    "integrations": 0.5,
    "constraints": 0.5,
}

# Extra items the model volunteers still count, at neutral weight.
DEFAULT_WEIGHT: Final[float] = 1.0

# Above this coverage the PM stops asking questions and moves to the spec.
SUFFICIENT_COVERAGE: Final[float] = 0.8


def is_filled(value: object) -> bool:
    """A checklist item counts once it holds a real answer."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() not in {"null", "unknown", "?"}
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def coverage(checklist: Mapping[str, object]) -> float:
    """Weighted fraction of filled checklist items, in [0.0, 1.0].

    The denominator always includes every standard item (missing keys count
    as unfilled) plus any extra keys present in ``checklist``.
    """
    keys = set(CHECKLIST_WEIGHTS) | set(checklist)
    total = sum(CHECKLIST_WEIGHTS.get(key, DEFAULT_WEIGHT) for key in keys)
    if total == 0:
        return 0.0
    filled = sum(
        CHECKLIST_WEIGHTS.get(key, DEFAULT_WEIGHT)
        for key in keys
        if is_filled(checklist.get(key))
    )
    return filled / total


def is_sufficient(checklist: Mapping[str, object]) -> bool:
    """True when the PM should stop asking questions and summarize."""
    return coverage(checklist) >= SUFFICIENT_COVERAGE
