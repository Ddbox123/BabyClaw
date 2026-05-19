"""Workspace file tree and preview helpers."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXCLUDED_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "workspace",
    "log_info",
    "backups",
}
MAX_TREE_DEPTH = 4
MAX_TEXT_CHARS = 200_000

LANGUAGE_BY_SUFFIX = {
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".mjs": "javascript",
    ".py": "python",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".yml": "yaml",
    ".yaml": "yaml",
}


def build_file_tree() -> list[dict]:
    """Build a trimmed project tree for the right-hand files panel."""

    nodes: list[dict] = []
    for child in sorted(PROJECT_ROOT.iterdir(), key=_sort_key):
        node = _build_node(child, depth=0)
        if node is not None:
            nodes.append(node)
    return nodes


def read_text_file(relative_path: str) -> dict:
    """Read a project file for the preview surface."""

    file_path = _resolve_project_path(relative_path)
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
        "path": relative_path,
        "language": LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
        "content": content,
        "truncated": truncated,
    }


def _build_node(path: Path, depth: int) -> dict | None:
    if path.name in EXCLUDED_DIR_NAMES:
        return None

    relative_path = path.relative_to(PROJECT_ROOT).as_posix()
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
            node = _build_node(child, depth + 1)
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


def _resolve_project_path(relative_path: str) -> Path:
    candidate = (PROJECT_ROOT / relative_path).resolve()
    project_root = PROJECT_ROOT.resolve()
    try:
        candidate.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("Path must stay inside the project root") from exc
    return candidate


def _sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, path.name.lower())
