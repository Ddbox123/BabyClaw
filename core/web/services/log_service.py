"""Log tree, preview, and guarded cleanup helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.web.services.log_diagnostics import analyze_log_content


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAX_TREE_DEPTH = 6
MAX_TEXT_CHARS = 200_000
MAX_ROOT_SUMMARY_ITEMS = 20_000

LOG_ROOTS = (
    {"id": "runtime_scenes", "path": "logs/runtime_scenes"},
    {"id": "runtime_logs", "path": "logs"},
    {"id": "workspace_logs", "path": "workspace/logs"},
    {"id": "conversation_logs", "path": "log_info"},
)

LANGUAGE_BY_SUFFIX = {
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".jsonl": "json",
    ".log": "text",
    ".md": "markdown",
    ".ps1": "powershell",
    ".py": "python",
    ".text": "text",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}

ROOT_GUIDES = {
    "runtime_scenes": {
        "userGuide": "优先按一次运行查看统一时间线，再打开关联原始日志。",
        "agentGuide": "先读 runtime scene timeline；需要上下文时再追 rawRefs 指向的原始日志。",
    },
    "runtime_logs": {
        "userGuide": "适合检查当前后端、launcher 和运行器即时输出。",
        "agentGuide": "排查启动、关闭、端口、后台服务问题时优先读取这里；不要在此根下直接处理 runtime_scenes。",
    },
    "workspace_logs": {
        "userGuide": "适合回看工作区内生成的转录、轮次和辅助运行记录。",
        "agentGuide": "用于追踪工作流产物、转录和工具辅助脚本输出，通常作为 conversation log 的补充证据。",
    },
    "conversation_logs": {
        "userGuide": "适合回看 agent 会话、工具调用、子 agent 输出和轮次结论。",
        "agentGuide": "排查 agent 漂移、重复工具、停止/继续、委派和验证行为时优先读取 conversation_*.jsonl 与 debug_*.log。",
    },
}


def list_log_roots() -> list[dict]:
    """List available log roots for the web workbench."""

    roots: list[dict] = []
    for root in LOG_ROOTS:
        root_path = _resolve_log_root(root["id"])
        roots.append(
            {
                "id": root["id"],
                "path": root["path"],
                "exists": root_path.exists() and root_path.is_dir(),
                "summary": _summarize_log_root(root["id"], root_path),
            }
        )
    return roots


def build_log_tree(root_id: str) -> dict:
    """Build a trimmed tree for a single log root."""

    root_meta = _root_meta(root_id)
    root_path = _resolve_log_root(root_id)
    if not root_path.exists() or not root_path.is_dir():
        return {
            "root": root_meta,
            "nodes": [],
        }

    nodes: list[dict] = []
    for child in sorted(root_path.iterdir(), key=_sort_key):
        if _should_skip_child(root_id, child, root_path):
            continue
        node = _build_node(child, root_path=root_path, depth=0)
        if node is not None:
            nodes.append(node)
    return {
        "root": root_meta,
        "nodes": nodes,
    }


def read_log_file(root_id: str, relative_path: str) -> dict:
    """Read a log file preview for the selected root."""

    root_meta = _root_meta(root_id)
    _assert_allowed_runtime_log_path(root_id, relative_path)
    file_path = _resolve_log_path(root_id, relative_path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {relative_path}")
    raw = file_path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("Binary files are not supported in the preview yet")
    content = raw.decode("utf-8", errors="replace")
    truncated = len(content) > MAX_TEXT_CHARS
    if truncated:
        content = content[:MAX_TEXT_CHARS] + "\n\n... preview truncated ..."
    return {
        "rootId": root_meta["id"],
        "rootPath": root_meta["path"],
        "relativePath": relative_path,
        "path": f"{root_meta['path']}/{relative_path}".replace("//", "/"),
        "language": LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
        "content": content,
        "truncated": truncated,
        "diagnostics": _analyze_log_content(root_meta["id"], relative_path, content),
    }


def clear_log_file(root_id: str, relative_path: str) -> dict:
    """Empty one log file while keeping it in place."""

    _assert_allowed_runtime_log_path(root_id, relative_path)
    file_path = _resolve_log_path(root_id, relative_path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {relative_path}")
    file_path.write_bytes(b"")
    return read_log_file(root_id, relative_path)


def delete_log_files(root_id: str, relative_paths: list[str]) -> dict:
    """Delete a selected list of files from one allowed log root."""

    root_meta = _root_meta(root_id)
    normalized_paths = _normalize_relative_paths(relative_paths)
    if not normalized_paths:
        raise ValueError("Select at least one log file to delete")

    deleted_paths: list[str] = []
    missing_paths: list[str] = []
    for relative_path in normalized_paths:
        _assert_allowed_runtime_log_path(root_id, relative_path)
        file_path = _resolve_log_path(root_id, relative_path)
        if not file_path.exists():
            missing_paths.append(relative_path)
            continue
        if not file_path.is_file():
            raise ValueError("Only log files can be deleted")
        file_path.unlink()
        deleted_paths.append(relative_path)

    return {
        "rootId": root_meta["id"],
        "rootPath": root_meta["path"],
        "deletedPaths": deleted_paths,
        "missingPaths": missing_paths,
        "deletedCount": len(deleted_paths),
    }


def _build_node(path: Path, *, root_path: Path, depth: int) -> dict | None:
    relative_path = path.relative_to(root_path).as_posix()
    if path.is_dir():
        if depth >= MAX_TREE_DEPTH:
            return {
                "name": path.name,
                "path": relative_path,
                "type": "directory",
                "children": [],
            }
        children = []
        for child in sorted(path.iterdir(), key=_sort_key):
            node = _build_node(child, root_path=root_path, depth=depth + 1)
            if node is not None:
                children.append(node)
        return {
            "name": path.name,
            "path": relative_path,
            "type": "directory",
            "children": children,
        }

    return {
        "name": path.name,
        "path": relative_path,
        "type": "file",
    }


def _root_meta(root_id: str) -> dict:
    for root in LOG_ROOTS:
        if root["id"] == root_id:
            root_path = _resolve_log_root(root_id)
            return {
                "id": root["id"],
                "path": root["path"],
                "exists": root_path.exists() and root_path.is_dir(),
                "summary": _summarize_log_root(root_id, root_path),
            }
    raise ValueError(f"Unknown log root: {root_id}")


def _summarize_log_root(root_id: str, root_path: Path) -> dict:
    guide = ROOT_GUIDES.get(root_id, {})
    if not root_path.exists() or not root_path.is_dir():
        return {
            "health": "missing",
            "fileCount": 0,
            "directoryCount": 0,
            "sizeBytes": 0,
            "lastModifiedAt": "",
            "latestPath": "",
            "userGuide": guide.get("userGuide", ""),
            "agentGuide": guide.get("agentGuide", ""),
        }

    file_count = 0
    directory_count = 0
    size_bytes = 0
    latest_path = ""
    latest_mtime = 0.0
    scanned = 0
    for child in _iter_log_children(root_id, root_path):
        if scanned >= MAX_ROOT_SUMMARY_ITEMS:
            break
        scanned += 1
        try:
            stat = child.stat()
        except OSError:
            continue
        if child.is_dir():
            directory_count += 1
            continue
        if not child.is_file():
            continue
        file_count += 1
        size_bytes += int(stat.st_size)
        if stat.st_mtime >= latest_mtime:
            latest_mtime = stat.st_mtime
            latest_path = child.relative_to(root_path).as_posix()

    return {
        "health": "empty" if file_count == 0 and directory_count == 0 else "active",
        "fileCount": file_count,
        "directoryCount": directory_count,
        "sizeBytes": size_bytes,
        "lastModifiedAt": _format_mtime(latest_mtime),
        "latestPath": latest_path,
        "userGuide": guide.get("userGuide", ""),
        "agentGuide": guide.get("agentGuide", ""),
    }


def _analyze_log_content(root_id: str, relative_path: str, content: str) -> dict[str, Any]:
    return analyze_log_content(
        anchor=f"{root_id}/{relative_path}",
        content=content,
        normal_summary="未发现明显错误或警告，可先把它作为正常路径或补充证据。",
        empty_summary="当前日志为空，暂时不能作为诊断证据。",
        error_summary_prefix="发现 ",
        warning_summary_prefix="发现 ",
        error_next_step="打开错误筛选，围绕第 {line} 行向前找触发动作、向后找失败结果。",
        warning_next_step="打开警告筛选，确认第 {line} 行附近是否出现重试、超时或被阻断动作。",
        structured_next_step="按结构化事件类型查看会话阶段，再与相邻 debug/runtime 日志交叉验证。",
        fallback_next_step="如当前问题仍未解释，切到相邻日志分组查找同一时间段的运行现场或会话记录。",
    )


def _iter_log_children(root_id: str, root_path: Path):
    stack = sorted(root_path.iterdir(), key=_sort_key, reverse=True)
    while stack:
        child = stack.pop()
        if _should_skip_child(root_id, child, root_path):
            continue
        yield child
        if child.is_dir():
            try:
                stack.extend(sorted(child.iterdir(), key=_sort_key, reverse=True))
            except OSError:
                continue


def _format_mtime(value: float) -> str:
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def _resolve_log_root(root_id: str) -> Path:
    for root in LOG_ROOTS:
        if root["id"] == root_id:
            return (PROJECT_ROOT / root["path"]).resolve()
    raise ValueError(f"Unknown log root: {root_id}")


def _resolve_log_path(root_id: str, relative_path: str) -> Path:
    root_path = _resolve_log_root(root_id)
    candidate = (root_path / relative_path).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("Path must stay inside the selected log root") from exc
    return candidate


def _normalize_relative_paths(items: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    for raw in items:
        value = str(raw or "").strip().replace("\\", "/")
        if not value or value in normalized:
            continue
        normalized.append(value)
    return normalized


def _sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, path.name.lower())


def _should_skip_child(root_id: str, child: Path, root_path: Path) -> bool:
    if root_id != "runtime_logs":
        return False
    try:
        relative = child.relative_to(root_path).as_posix()
    except ValueError:
        return False
    return relative == "runtime_scenes" or relative.startswith("runtime_scenes/")


def _assert_allowed_runtime_log_path(root_id: str, relative_path: str) -> None:
    if root_id != "runtime_logs":
        return
    normalized = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
    if normalized == "runtime_scenes" or normalized.startswith("runtime_scenes/"):
        raise ValueError("Runtime scene bundles must be managed from the runtime scenes surface")
