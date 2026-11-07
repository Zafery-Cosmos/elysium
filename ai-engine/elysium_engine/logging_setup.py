"""Apply ``developer.log_level`` to the engine's own loggers."""

from __future__ import annotations

import logging

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def apply_log_level(level: str) -> None:
    """Set the ``elysium_engine`` logger level (stderr, captured by the app)."""
    logger = logging.getLogger("elysium_engine")
    if not any(getattr(h, "_elysium", False) for h in logger.handlers):
        handler = logging.StreamHandler()  # stderr
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._elysium = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(_LEVELS.get(level, logging.WARNING))
