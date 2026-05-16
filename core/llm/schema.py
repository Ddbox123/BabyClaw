# -*- coding: utf-8 -*-
"""Tool schema normalization for provider payloads."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict


_TOOL_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")
_SUPPORTED_JSON_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "description",
    "enum",
    "items",
    "additionalProperties",
    "default",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
}


def normalize_tool_name(name: str) -> str:
    normalized = _TOOL_NAME_PATTERN.sub("_", str(name or "").strip())
    normalized = normalized.strip("_")
    return normalized[:64] or "tool"


def sanitize_json_schema(schema: Any) -> Dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}, "required": []}
    cleaned = _sanitize_schema_node(copy.deepcopy(schema))
    if not isinstance(cleaned, dict):
        return {"type": "object", "properties": {}, "required": []}
    cleaned.setdefault("type", "object")
    cleaned.setdefault("properties", {})
    cleaned.setdefault("required", [])
    return cleaned


def sanitize_tool_schema(tool_schema: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(tool_schema, dict):
        tool_schema = {}
    function = dict(tool_schema.get("function") or {})
    function["name"] = normalize_tool_name(function.get("name") or tool_schema.get("name") or "")
    function["description"] = str(function.get("description") or "")[:1024]
    function["parameters"] = sanitize_json_schema(function.get("parameters") or {})
    return {"type": "function", "function": function}


def _sanitize_schema_node(value: Any) -> Any:
    if isinstance(value, list):
        return [_sanitize_schema_node(item) for item in value]
    if not isinstance(value, dict):
        return value

    cleaned: Dict[str, Any] = {}
    for key, item in value.items():
        if key in {"title", "$defs", "definitions", "$schema", "examples", "deprecated"}:
            continue
        if key not in _SUPPORTED_JSON_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(item, dict):
            cleaned[key] = {
                str(prop_name): _sanitize_schema_node(prop_schema)
                for prop_name, prop_schema in item.items()
                if isinstance(prop_schema, dict)
            }
            continue
        cleaned[key] = _sanitize_schema_node(item)
    return cleaned


__all__ = [
    "normalize_tool_name",
    "sanitize_json_schema",
    "sanitize_tool_schema",
]
