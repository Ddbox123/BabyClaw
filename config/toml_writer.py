"""
受控 TOML 序列化器。

仅服务当前项目公开配置结构，不追求通用 TOML dump 能力。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _format_string_list(values: List[str], indent: int = 0) -> str:
    if not values:
        return "[]"
    pad = " " * indent
    inner = ",\n".join(f'{pad}    {_format_scalar(item)}' for item in values)
    return "[\n" + inner + f"\n{pad}]"


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _format_key(key: Any) -> str:
    text = str(key)
    if _BARE_KEY_RE.fullmatch(text):
        return text
    return _format_scalar(text)


def _format_table_name(parts: List[str]) -> str:
    return ".".join(_format_key(part) for part in parts)


def _write_table(lines: List[str], table_path: List[str], data: Dict[str, Any], indent: int = 0) -> None:
    lines.append(f"[{_format_table_name(table_path)}]")

    scalar_items = []
    nested_tables = []
    array_tables = []

    for key, value in data.items():
        if _is_scalar(value) or _is_string_list(value):
            scalar_items.append((key, value))
        elif isinstance(value, dict):
            nested_tables.append((key, value))
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            array_tables.append((key, value))
        elif isinstance(value, list):
            scalar_items.append((key, [str(item) for item in value]))
        else:
            scalar_items.append((key, str(value)))

    for key, value in scalar_items:
        if _is_string_list(value):
            lines.append(f"{_format_key(key)} = {_format_string_list(value, indent=indent)}")
        else:
            lines.append(f"{_format_key(key)} = {_format_scalar(value)}")

    for key, value in nested_tables:
        lines.append("")
        _write_table(lines, [*table_path, str(key)], value, indent=indent)

    for key, items in array_tables:
        for item in items:
            lines.append("")
            lines.append(f"[[{_format_table_name([*table_path, str(key)])}]]")
            item_scalars = []
            item_nested = []
            for item_key, item_value in item.items():
                if _is_scalar(item_value) or _is_string_list(item_value):
                    item_scalars.append((item_key, item_value))
                elif isinstance(item_value, dict):
                    item_nested.append((item_key, item_value))
                else:
                    item_scalars.append((item_key, str(item_value)))

            for item_key, item_value in item_scalars:
                if _is_string_list(item_value):
                    lines.append(f"{_format_key(item_key)} = {_format_string_list(item_value, indent=indent)}")
                else:
                    lines.append(f"{_format_key(item_key)} = {_format_scalar(item_value)}")

            for item_key, item_value in item_nested:
                lines.append("")
                _write_table(lines, [*table_path, str(key), str(item_key)], item_value, indent=indent)


def dumps_public_config(data: Dict[str, Any], header_lines: Iterable[str] | None = None) -> str:
    """将公开配置结构写为稳定 TOML 文本。"""
    lines: List[str] = []
    if header_lines:
        lines.extend(header_lines)
        if lines and lines[-1] != "":
            lines.append("")

    for index, (section_name, section_value) in enumerate(data.items()):
        if index > 0:
            lines.append("")
        if isinstance(section_value, dict):
            _write_table(lines, [str(section_name)], section_value)
        else:
            lines.append(f"{_format_key(section_name)} = {_format_scalar(section_value)}")

    return "\n".join(lines).rstrip() + "\n"
