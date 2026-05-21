"""Mental model feature flags shared across runtime and web surfaces."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from config.public_config import load_public_config

_MENTAL_MODEL_ENABLED_OVERRIDE: ContextVar[bool | None] = ContextVar(
    "mental_model_enabled_override",
    default=None,
)


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def is_mental_model_enabled(public_config: dict[str, Any] | None = None) -> bool:
    """Return whether the mental-model layer should be active."""

    override = _MENTAL_MODEL_ENABLED_OVERRIDE.get()
    if override is not None:
        return bool(override)

    config = public_config
    if config is None:
        try:
            config = load_public_config()
        except Exception:
            config = {}

    if not isinstance(config, dict):
        return True

    section = config.get("mental_model")
    if isinstance(section, dict) and "enabled" in section:
        return _coerce_bool(section.get("enabled"), default=True)

    agent_section = config.get("agent")
    if isinstance(agent_section, dict):
        nested = agent_section.get("mental_model")
        if isinstance(nested, dict) and "enabled" in nested:
            return _coerce_bool(nested.get("enabled"), default=True)

    return True


@contextmanager
def mental_model_enabled_override(enabled: bool | None):
    """Temporarily override the mental-model flag for the current execution context."""

    if enabled is None:
        yield
        return

    token = _MENTAL_MODEL_ENABLED_OVERRIDE.set(bool(enabled))
    try:
        yield
    finally:
        _MENTAL_MODEL_ENABLED_OVERRIDE.reset(token)
