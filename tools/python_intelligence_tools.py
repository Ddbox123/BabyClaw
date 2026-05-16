# -*- coding: utf-8 -*-
"""
Python 结构感知与静态检查工具。

目标：
- 用 Jedi 提供接近语言服务器的定义 / 引用 / 悬浮信息
- 用 Ruff 提供快速、只读的 Python lint 诊断
- 依赖缺失时结构化降级，而不是直接报异常
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_path(file_path: str) -> Path:
    path = Path(file_path)
    if path.is_absolute():
        return path
    return (_project_root() / path).resolve()


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _missing_dependency_message(dep: str, capability: str) -> str:
    payload = {
        "status": "unavailable",
        "capability": capability,
        "missing_dependency": dep,
        "message": f"当前环境未安装 {dep}，暂时无法执行 {capability}。",
        "suggested_action": f"在项目环境中安装 `{dep}` 后再重试。",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _safe_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(_project_root()).as_posix()
    except Exception:
        return path.as_posix()


def python_symbol_tool(
    file_path: str,
    line: int,
    column: int,
    action: str = "definition",
    max_results: int = 20,
) -> str:
    """
    Python 符号工具：definition / references / hover。

    Args:
        file_path: Python 文件路径
        line: 1-based 行号
        column: 0-based 列号（与 Jedi 保持一致）
        action: definition / references / hover
        max_results: 最大结果数

    Returns:
        JSON 字符串
    """
    if action not in {"definition", "references", "hover"}:
        return json.dumps(
            {
                "status": "error",
                "message": f"不支持的 action: {action}",
                "supported_actions": ["definition", "references", "hover"],
            },
            ensure_ascii=False,
            indent=2,
        )

    if not _module_available("jedi"):
        return _missing_dependency_message("jedi", f"python_symbol:{action}")

    path = _resolve_path(file_path)
    if not path.exists():
        return json.dumps(
            {"status": "error", "message": f"文件不存在: {file_path}"},
            ensure_ascii=False,
            indent=2,
        )

    try:
        import jedi  # type: ignore

        script = jedi.Script(path=str(path))
        if action == "definition":
            symbols = script.goto(line=line, column=column, follow_imports=True)
        elif action == "references":
            symbols = script.get_references(line=line, column=column, include_builtins=False)
        else:
            symbols = script.infer(line=line, column=column)

        results: List[Dict[str, Any]] = []
        for symbol in symbols[:max_results]:
            module_path = getattr(symbol, "module_path", None)
            rel_path = _safe_rel(Path(module_path)) if module_path else None
            item = {
                "name": getattr(symbol, "name", ""),
                "type": getattr(symbol, "type", ""),
                "description": getattr(symbol, "description", ""),
                "module_name": getattr(symbol, "module_name", ""),
                "path": rel_path,
                "line": getattr(symbol, "line", None),
                "column": getattr(symbol, "column", None),
            }
            if action == "hover":
                doc = ""
                try:
                    doc = symbol.docstring()
                except Exception:
                    doc = ""
                item["docstring"] = doc[:1200]
            results.append(item)

        return json.dumps(
            {
                "status": "ok",
                "action": action,
                "query": {
                    "file_path": _safe_rel(path),
                    "line": line,
                    "column": column,
                },
                "count": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "action": action,
                "message": f"Jedi 分析失败: {type(exc).__name__}: {exc}",
            },
            ensure_ascii=False,
            indent=2,
        )


def python_lint_tool(target: str = ".", max_issues: int = 100) -> str:
    """
    Python lint 检查（Ruff）。

    Args:
        target: 文件或目录
        max_issues: 最多返回多少条问题

    Returns:
        JSON 字符串
    """
    if not _module_available("ruff"):
        return _missing_dependency_message("ruff", "python_lint")

    resolved = _resolve_path(target)
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        str(resolved),
        "--output-format",
        "json",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=str(_project_root()),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "message": f"Ruff 执行失败: {type(exc).__name__}: {exc}",
                "command": command,
            },
            ensure_ascii=False,
            indent=2,
        )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    raw_items: List[Dict[str, Any]] = []
    if stdout:
        try:
            raw_items = json.loads(stdout)
        except json.JSONDecodeError:
            return json.dumps(
                {
                    "status": "error",
                    "message": "Ruff 输出不是合法 JSON",
                    "stdout": stdout[:2000],
                    "stderr": stderr[:1000],
                },
                ensure_ascii=False,
                indent=2,
            )

    issues = []
    for item in raw_items[:max_issues]:
        filename = item.get("filename", "")
        issues.append(
            {
                "path": _safe_rel(Path(filename)) if filename else filename,
                "code": item.get("code"),
                "message": item.get("message"),
                "line": (item.get("location") or {}).get("row"),
                "column": (item.get("location") or {}).get("column"),
                "end_line": (item.get("end_location") or {}).get("row"),
                "end_column": (item.get("end_location") or {}).get("column"),
            }
        )

    status = "ok" if result.returncode in (0, 1) else "error"
    return json.dumps(
        {
            "status": status,
            "tool": "ruff",
            "target": _safe_rel(resolved),
            "issue_count": len(raw_items),
            "returned_issue_count": len(issues),
            "issues": issues,
            "stderr": stderr[:1000] if stderr else "",
        },
        ensure_ascii=False,
        indent=2,
    )


__all__ = [
    "python_symbol_tool",
    "python_lint_tool",
]
