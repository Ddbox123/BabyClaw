"""Log tree, preview, and guarded cleanup helpers."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAX_TREE_DEPTH = 6
MAX_TEXT_CHARS = 200_000

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
    ".log": "text",
    ".md": "markdown",
    ".py": "python",
    ".text": "text",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
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
            }
    raise ValueError(f"Unknown log root: {root_id}")


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
    return relative == "runtime_scenes"


def _assert_allowed_runtime_log_path(root_id: str, relative_path: str) -> None:
    if root_id != "runtime_logs":
        return
    normalized = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
    if normalized == "runtime_scenes" or normalized.startswith("runtime_scenes/"):
        raise ValueError("Runtime scene bundles must be managed from the runtime scenes surface")
