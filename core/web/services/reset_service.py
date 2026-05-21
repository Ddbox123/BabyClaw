"""Guarded reset inventory, preview, and execution helpers."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from core.ui.chat_state import build_chat_state, chat_state_path, save_chat_state

from .i18n import get_web_language, text_for


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAX_PREVIEW_PATHS = 120
MAX_SUMMARY_SCAN_ITEMS = 80_000
RUNNING_SCENE_STATUSES = {"running", "starting", "queued", "stopping"}


@dataclass(frozen=True)
class ResetItemDefinition:
    id: str
    name_zh: str
    name_en: str
    description_zh: str
    description_en: str
    detail_zh: str
    detail_en: str
    risk: str
    default_selected: bool
    rebuild_hint_zh: str = ""
    rebuild_hint_en: str = ""
    collector: Callable[[], list["ResetCandidate"]] | None = None
    executor: Callable[["ResetCandidate"], "ResetActionResult"] | None = None


@dataclass(frozen=True)
class ResetCandidate:
    path: Path
    kind: str
    action: str = "delete"
    note_zh: str = ""
    note_en: str = ""
    protected: bool = False
    missing: bool = False


@dataclass(frozen=True)
class ResetActionResult:
    status: str
    path: Path
    kind: str
    action: str
    message: str = ""


def get_reset_summary() -> dict:
    """Return the current reset inventory without executing destructive actions."""

    lang = get_web_language()
    items = [_summarize_item(definition, lang) for definition in _reset_items()]
    protected = [
        {
            "id": "config",
            "label": text_for(lang, zh="配置与模型档案", en="Config and model profiles"),
            "paths": ["config.toml", "config/"],
            "reason": text_for(lang, zh="配置不是垃圾内容，不提供重置勾选。", en="Config is not cleanup residue."),
        },
        {
            "id": "memory",
            "label": text_for(lang, zh="长期记忆与动态提示词", en="Long-term memory and dynamic prompts"),
            "paths": ["workspace/agent_brain.db", "workspace/memory/", "workspace/prompts/"],
            "reason": text_for(lang, zh="按需求固定保护。", en="Protected by reset policy."),
        },
        {
            "id": "evolution",
            "label": text_for(lang, zh="监督进化、自进化与 Gym 证据", en="Evolution and Gym evidence"),
            "paths": ["workspace/supervised_evolution/", "workspace/evolution/", "workspace/gym/"],
            "reason": text_for(lang, zh="训练、建议基线和审计证据不能由 Reset 清理。", en="Training, advisory, and audit evidence are preserved."),
        },
        {
            "id": "project-memory",
            "label": text_for(lang, zh="项目记忆", en="Project memory"),
            "paths": [".docs/project-memory/"],
            "reason": text_for(lang, zh="项目记忆是开发定义完成的一部分。", en="Project memory is part of the development record."),
        },
        {
            "id": "active-runtime",
            "label": text_for(lang, zh="当前运行现场与活跃浏览器 profile", en="Active runtime scene and browser profile"),
            "paths": ["logs/runtime_scenes/<current>", ".runtime/launcher/state.json", ".runtime/launcher/edge-app-profile/"],
            "reason": text_for(lang, zh="运行中内容只跳过，不强删。", en="Live runtime state is skipped, not force-deleted."),
        },
    ]
    return {
        "warning": text_for(
            lang,
            zh="Reset 现在只允许从后端白名单中自选清理项。长期记忆、动态提示词、监督进化、自进化和 Gym 证据固定保护。",
            en="Reset now only accepts user-selected backend allow-list items. Long-term memory, prompts, supervised/self evolution, and Gym evidence are fixed protected zones.",
        ),
        "mode": "custom",
        "items": items,
        "protected": protected,
        "categories": items,
        "presets": [],
    }


def preview_reset(item_ids: list[str] | tuple[str, ...]) -> dict:
    """Return a deletion preview for the selected allow-list item ids."""

    lang = get_web_language()
    definitions = _definitions_for_ids(item_ids)
    previews = [_preview_item(definition, lang) for definition in definitions]
    totals = _total_from_item_results(previews)
    warnings = _collect_rebuild_hints(definitions, lang)
    return {
        "selectedItemIds": [definition.id for definition in definitions],
        "items": previews,
        "totals": totals,
        "warnings": warnings,
        "rebuildHints": warnings,
        "summary": _preview_summary(totals, lang),
    }


def execute_reset(item_ids: list[str] | tuple[str, ...], *, confirmed: bool) -> dict:
    """Execute cleanup for the selected allow-list item ids."""

    if not confirmed:
        raise ValueError("Reset execution requires an explicit confirmation flag")

    lang = get_web_language()
    definitions = _definitions_for_ids(item_ids)
    results = [_execute_item(definition, lang) for definition in definitions]
    totals = _total_from_item_results(results)
    rebuild_hints = _collect_rebuild_hints(definitions, lang)
    return {
        "selectedItemIds": [definition.id for definition in definitions],
        "items": results,
        "totals": totals,
        "warnings": rebuild_hints,
        "rebuildHints": rebuild_hints,
        "summary": _execute_summary(totals, lang),
    }


def _reset_items() -> tuple[ResetItemDefinition, ...]:
    return (
        ResetItemDefinition(
            id="chat_history",
            name_zh="聊天历史",
            name_en="Chat history",
            description_zh="清空 workspace/chat/chat_state.json，并写回一个空默认会话。",
            description_en="Clear workspace/chat/chat_state.json and recreate one empty default session.",
            detail_zh="workspace/chat/chat_state.json",
            detail_en="workspace/chat/chat_state.json",
            risk="medium",
            default_selected=False,
            collector=_collect_chat_history,
            executor=_execute_chat_history,
        ),
        ResetItemDefinition(
            id="conversation_logs",
            name_zh="会话日志",
            name_en="Conversation logs",
            description_zh="删除 log_info/ 下的 conversation_*.jsonl 与 debug_*.log 等会话诊断文件。",
            description_en="Delete conversation_*.jsonl, debug_*.log, and related session diagnostics under log_info/.",
            detail_zh="log_info/ 中的会话与 debug 日志",
            detail_en="conversation and debug logs in log_info/",
            risk="medium",
            default_selected=False,
            collector=_collect_conversation_logs,
        ),
        ResetItemDefinition(
            id="runtime_logs",
            name_zh="普通运行日志",
            name_en="Runtime logs",
            description_zh="删除 logs/ 下除 runtime_scenes/ 以外的普通日志文件。",
            description_en="Delete ordinary files under logs/ while excluding logs/runtime_scenes/.",
            detail_zh="logs/ 非 runtime_scenes 内容",
            detail_en="logs/ excluding runtime_scenes/",
            risk="low",
            default_selected=False,
            collector=_collect_runtime_logs,
        ),
        ResetItemDefinition(
            id="stopped_runtime_scenes",
            name_zh="已停止运行现场",
            name_en="Stopped runtime scenes",
            description_zh="删除 logs/runtime_scenes/ 中状态不是 running/starting/queued/stopping 的运行现场。",
            description_en="Delete runtime scene bundles whose status is not running, starting, queued, or stopping.",
            detail_zh="logs/runtime_scenes/ 已停止现场；当前运行现场跳过",
            detail_en="stopped logs/runtime_scenes/ bundles; current scene is skipped",
            risk="medium",
            default_selected=False,
            collector=_collect_stopped_runtime_scenes,
        ),
        ResetItemDefinition(
            id="runtime_manager_results",
            name_zh="runtime-manager 历史结果",
            name_en="Runtime-manager results",
            description_zh="删除 .runtime/runtime-manager/results/ 中的旧命令残留。",
            description_en="Delete old command result residue under .runtime/runtime-manager/results/.",
            detail_zh=".runtime/runtime-manager/results/",
            detail_en=".runtime/runtime-manager/results/",
            risk="low",
            default_selected=False,
            collector=_collect_runtime_manager_results,
        ),
        ResetItemDefinition(
            id="browser_profiles",
            name_zh="旧浏览器/测试 profile",
            name_en="Old browser/test profiles",
            description_zh="删除 .runtime/ 下旧 profile 目录，保护当前 launcher 使用的浏览器 profile。",
            description_en="Delete old profile directories under .runtime/ while protecting the active launcher browser profile.",
            detail_zh=".runtime/*profile*，当前 browserProfileDir 跳过",
            detail_en=".runtime/*profile* with current browserProfileDir skipped",
            risk="medium",
            default_selected=False,
            collector=_collect_browser_profiles,
        ),
        ResetItemDefinition(
            id="python_test_caches",
            name_zh="Python/测试缓存",
            name_en="Python/test caches",
            description_zh="删除 __pycache__/、.pytest_cache/、.ruff_cache/，跳过 .venv 和 node_modules。",
            description_en="Delete __pycache__/, .pytest_cache/, and .ruff_cache/ while skipping .venv and node_modules.",
            detail_zh="递归缓存目录",
            detail_en="recursive cache directories",
            risk="low",
            default_selected=False,
            collector=_collect_python_test_caches,
        ),
        ResetItemDefinition(
            id="temp_artifacts",
            name_zh="临时截图/HTML",
            name_en="Temporary screenshots/HTML",
            description_zh="删除 workspace/tmp-* 与 .runtime 根下明确临时的 png/html/log/txt 文件。",
            description_en="Delete workspace/tmp-* and clearly temporary png/html/log/txt files at the .runtime root.",
            detail_zh="workspace/tmp-*、.runtime/*.png|*.html|*.log|*.txt",
            detail_en="workspace/tmp-* and .runtime/*.png|*.html|*.log|*.txt",
            risk="low",
            default_selected=False,
            collector=_collect_temp_artifacts,
        ),
        ResetItemDefinition(
            id="web_dist",
            name_zh="可重建前端产物",
            name_en="Rebuildable frontend output",
            description_zh="删除 web/dist/。单后端静态托管模式需要重新 npm run build 后才能打开前端。",
            description_en="Delete web/dist/. Single-backend static hosting needs npm run build before the frontend opens again.",
            detail_zh="web/dist/",
            detail_en="web/dist/",
            risk="medium",
            default_selected=False,
            rebuild_hint_zh="删除 web/dist/ 后，单后端静态托管模式需要在 web/ 重新执行 npm run build。",
            rebuild_hint_en="After deleting web/dist/, run npm run build in web/ before using single-backend static hosting.",
            collector=_collect_web_dist,
        ),
    )


def _summarize_item(definition: ResetItemDefinition, lang: str) -> dict:
    candidates = definition.collector() if definition.collector else []
    deletable = [candidate for candidate in candidates if _candidate_is_deletable(candidate)]
    protected = [candidate for candidate in candidates if candidate.protected]
    missing = [candidate for candidate in candidates if candidate.missing]
    size_bytes = _sum_existing_size(deletable)
    file_count = _sum_file_count(deletable)
    exists = bool(deletable)
    return {
        "id": definition.id,
        "name": _localized(definition, "name", lang),
        "description": _localized(definition, "description", lang),
        "detail": _localized(definition, "detail", lang),
        "risk": definition.risk,
        "defaultSelected": definition.default_selected,
        "exists": exists,
        "sizeBytes": size_bytes,
        "size": _format_size(size_bytes) if exists else text_for(lang, zh="无可清理内容", en="nothing to clean"),
        "fileCount": file_count,
        "candidateCount": len(deletable),
        "protectedCount": len(protected),
        "missingCount": len(missing),
        "rebuildHint": _localized_rebuild_hint(definition, lang),
    }


def _preview_item(definition: ResetItemDefinition, lang: str) -> dict:
    candidates = definition.collector() if definition.collector else []
    delete_candidates = [candidate for candidate in candidates if _candidate_is_deletable(candidate)]
    protected = [candidate for candidate in candidates if candidate.protected]
    skipped = [candidate for candidate in candidates if candidate.missing]
    summary = {
        "deleteCount": len(delete_candidates),
        "deleteFileCount": _sum_file_count(delete_candidates),
        "deleteSizeBytes": _sum_existing_size(delete_candidates),
        "skippedCount": len(skipped),
        "protectedCount": len(protected),
        "failedCount": 0,
    }
    return {
        "id": definition.id,
        "name": _localized(definition, "name", lang),
        "risk": definition.risk,
        "deleteCandidates": [_candidate_payload(candidate, lang) for candidate in delete_candidates[:MAX_PREVIEW_PATHS]],
        "skipped": [_candidate_payload(candidate, lang) for candidate in skipped[:MAX_PREVIEW_PATHS]],
        "protected": [_candidate_payload(candidate, lang) for candidate in protected[:MAX_PREVIEW_PATHS]],
        "failed": [],
        "warnings": [_localized_rebuild_hint(definition, lang)] if _localized_rebuild_hint(definition, lang) else [],
        "truncated": len(delete_candidates) > MAX_PREVIEW_PATHS,
        "summary": summary,
    }


def _execute_item(definition: ResetItemDefinition, lang: str) -> dict:
    candidates = definition.collector() if definition.collector else []
    deleted: list[ResetActionResult] = []
    failed: list[ResetActionResult] = []
    skipped: list[ResetActionResult] = []
    protected: list[ResetCandidate] = []

    for candidate in candidates:
        if candidate.protected:
            protected.append(candidate)
            continue
        if candidate.missing and candidate.action != "reset":
            skipped.append(
                ResetActionResult(
                    status="skipped",
                    path=candidate.path,
                    kind=candidate.kind,
                    action=candidate.action,
                    message=_candidate_note(candidate, lang) or text_for(lang, zh="不存在，已跳过。", en="Missing; skipped."),
                )
            )
            continue
        executor = definition.executor or _execute_delete_candidate
        result = executor(candidate)
        if result.status == "deleted":
            deleted.append(result)
        elif result.status == "skipped":
            skipped.append(result)
        else:
            failed.append(result)

    summary = {
        "deletedCount": len(deleted),
        "deletedFileCount": _sum_result_file_count(deleted),
        "deletedSizeBytes": 0,
        "skippedCount": len(skipped),
        "protectedCount": len(protected),
        "failedCount": len(failed),
    }
    return {
        "id": definition.id,
        "name": _localized(definition, "name", lang),
        "risk": definition.risk,
        "deleted": [_result_payload(result) for result in deleted[:MAX_PREVIEW_PATHS]],
        "skipped": [_result_payload(result) for result in skipped[:MAX_PREVIEW_PATHS]],
        "protected": [_candidate_payload(candidate, lang) for candidate in protected[:MAX_PREVIEW_PATHS]],
        "failed": [_result_payload(result) for result in failed[:MAX_PREVIEW_PATHS]],
        "warnings": [_localized_rebuild_hint(definition, lang)] if _localized_rebuild_hint(definition, lang) else [],
        "truncated": len(deleted) > MAX_PREVIEW_PATHS,
        "summary": summary,
    }


def _collect_chat_history() -> list[ResetCandidate]:
    path = chat_state_path(PROJECT_ROOT)
    return [_candidate_for_path(path, kind="file", action="reset", missing=not path.exists())]


def _execute_chat_history(candidate: ResetCandidate) -> ResetActionResult:
    try:
        save_chat_state(PROJECT_ROOT, build_chat_state([]))
    except OSError as exc:
        return ResetActionResult(
            status="failed",
            path=candidate.path,
            kind=candidate.kind,
            action="reset",
            message=str(exc),
        )
    return ResetActionResult(
        status="deleted",
        path=candidate.path,
        kind=candidate.kind,
        action="reset",
        message="reset to empty chat state",
    )


def _collect_conversation_logs() -> list[ResetCandidate]:
    root = PROJECT_ROOT / "log_info"
    if not root.exists():
        return [_candidate_for_path(root, kind="directory", missing=True)]
    candidates: list[ResetCandidate] = []
    for path in _walk_project_paths(root):
        if path.is_file() and _is_conversation_log_file(path):
            candidates.append(_candidate_for_path(path, kind="file"))
    return _dedupe_candidates(candidates)


def _collect_runtime_logs() -> list[ResetCandidate]:
    root = PROJECT_ROOT / "logs"
    if not root.exists():
        return [_candidate_for_path(root, kind="directory", missing=True)]
    candidates: list[ResetCandidate] = []
    runtime_scenes_root = (root / "runtime_scenes").resolve()
    for path in _walk_project_paths(root, skip_roots=[runtime_scenes_root]):
        try:
            path.resolve().relative_to(runtime_scenes_root)
            continue
        except ValueError:
            pass
        if path.is_file():
            candidates.append(_candidate_for_path(path, kind="file"))
    return _dedupe_candidates(candidates)


def _collect_stopped_runtime_scenes() -> list[ResetCandidate]:
    root = PROJECT_ROOT / "logs" / "runtime_scenes"
    if not root.exists():
        return [_candidate_for_path(root, kind="directory", missing=True)]
    active_scene_dir = _current_runtime_scene_dir()
    candidates: list[ResetCandidate] = []
    for scene_dir in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if not scene_dir.is_dir():
            continue
        status = _runtime_scene_status(scene_dir)
        if active_scene_dir is not None and _same_path(scene_dir, active_scene_dir):
            candidates.append(
                _candidate_for_path(
                    scene_dir,
                    kind="directory",
                    protected=True,
                    note_zh="当前 launcher 正在使用的运行现场。",
                    note_en="Active launcher runtime scene.",
                )
            )
            continue
        if status in RUNNING_SCENE_STATUSES:
            candidates.append(
                _candidate_for_path(
                    scene_dir,
                    kind="directory",
                    protected=True,
                    note_zh=f"运行现场状态为 {status}，已保护。",
                    note_en=f"Runtime scene status is {status}; protected.",
                )
            )
            continue
        candidates.append(_candidate_for_path(scene_dir, kind="directory"))
    return _dedupe_candidates(candidates)


def _collect_runtime_manager_results() -> list[ResetCandidate]:
    path = PROJECT_ROOT / ".runtime" / "runtime-manager" / "results"
    return [_candidate_for_path(path, kind="directory", missing=not path.exists())]


def _collect_browser_profiles() -> list[ResetCandidate]:
    runtime_root = PROJECT_ROOT / ".runtime"
    if not runtime_root.exists():
        return [_candidate_for_path(runtime_root, kind="directory", missing=True)]
    current_profile = _current_browser_profile_dir()
    candidates: list[ResetCandidate] = []
    if current_profile is not None:
        candidates.append(
            _candidate_for_path(
                current_profile,
                kind="directory",
                protected=True,
                note_zh="当前 launcher 正在使用的浏览器 profile。",
                note_en="Active launcher browser profile.",
            )
        )
    for path in _walk_project_paths(runtime_root, skip_roots=[current_profile] if current_profile is not None else []):
        if not path.is_dir():
            continue
        lowered = path.name.lower()
        if "profile" not in lowered:
            continue
        if current_profile is not None and (_same_path(path, current_profile) or _is_relative_to(path, current_profile)):
            continue
        candidates.append(_candidate_for_path(path, kind="directory"))
    return _collapse_nested_candidates(_dedupe_candidates(candidates))


def _collect_python_test_caches() -> list[ResetCandidate]:
    names = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    candidates: list[ResetCandidate] = []
    current_profile = _current_browser_profile_dir()
    skip_roots = [current_profile] if current_profile is not None else []
    for path in _walk_project_paths(PROJECT_ROOT, skip_roots=skip_roots):
        if not path.is_dir() or path.name not in names:
            continue
        if _has_ignored_part(path):
            continue
        candidates.append(_candidate_for_path(path, kind="directory"))
    return _collapse_nested_candidates(_dedupe_candidates(candidates))


def _collect_temp_artifacts() -> list[ResetCandidate]:
    candidates: list[ResetCandidate] = []
    workspace = PROJECT_ROOT / "workspace"
    if workspace.exists():
        for path in workspace.glob("tmp-*"):
            if path.exists():
                candidates.append(_candidate_for_path(path, kind="directory" if path.is_dir() else "file"))
    runtime_root = PROJECT_ROOT / ".runtime"
    if runtime_root.exists():
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.html", "*.htm", "*.log", "*.txt"):
            for path in runtime_root.glob(pattern):
                if path.is_file():
                    candidates.append(_candidate_for_path(path, kind="file"))
    return _dedupe_candidates(candidates)


def _collect_web_dist() -> list[ResetCandidate]:
    path = PROJECT_ROOT / "web" / "dist"
    return [_candidate_for_path(path, kind="directory", missing=not path.exists())]


def _execute_delete_candidate(candidate: ResetCandidate) -> ResetActionResult:
    try:
        if not candidate.path.exists():
            return ResetActionResult("skipped", candidate.path, candidate.kind, candidate.action, "missing")
        if candidate.path.is_file() or candidate.path.is_symlink():
            candidate.path.unlink()
        elif candidate.path.is_dir():
            shutil.rmtree(candidate.path)
        else:
            return ResetActionResult("skipped", candidate.path, candidate.kind, candidate.action, "unsupported path type")
    except Exception as exc:
        return ResetActionResult("failed", candidate.path, candidate.kind, candidate.action, str(exc))
    return ResetActionResult("deleted", candidate.path, candidate.kind, candidate.action)


def _definitions_for_ids(item_ids: list[str] | tuple[str, ...]) -> list[ResetItemDefinition]:
    normalized: list[str] = []
    for raw in item_ids:
        item_id = str(raw or "").strip()
        if item_id and item_id not in normalized:
            normalized.append(item_id)
    if not normalized:
        raise ValueError("Select at least one reset item")
    by_id = {definition.id: definition for definition in _reset_items()}
    unknown = [item_id for item_id in normalized if item_id not in by_id]
    if unknown:
        raise ValueError(f"Unknown reset item id: {', '.join(unknown)}")
    return [by_id[item_id] for item_id in normalized]


def _candidate_for_path(
    path: Path,
    *,
    kind: str,
    action: str = "delete",
    note_zh: str = "",
    note_en: str = "",
    protected: bool = False,
    missing: bool = False,
) -> ResetCandidate:
    resolved = _resolve_project_path(path)
    return ResetCandidate(
        path=resolved,
        kind=kind,
        action=action,
        note_zh=note_zh,
        note_en=note_en,
        protected=protected,
        missing=missing or not resolved.exists(),
    )


def _resolve_project_path(path: Path) -> Path:
    candidate = path.resolve()
    root = PROJECT_ROOT.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Reset paths must stay inside the project root") from exc
    return candidate


def _candidate_is_deletable(candidate: ResetCandidate) -> bool:
    return not candidate.protected and (candidate.path.exists() or candidate.action == "reset")


def _candidate_payload(candidate: ResetCandidate, lang: str) -> dict:
    size_bytes = 0 if candidate.protected else _path_size(candidate.path) if candidate.path.exists() else 0
    file_count = 0 if candidate.protected else _path_file_count(candidate.path) if candidate.path.exists() else 0
    return {
        "path": _relative_path(candidate.path),
        "kind": candidate.kind,
        "action": candidate.action,
        "sizeBytes": size_bytes,
        "fileCount": file_count,
        "message": _candidate_note(candidate, lang),
    }


def _result_payload(result: ResetActionResult) -> dict:
    return {
        "path": _relative_path(result.path),
        "kind": result.kind,
        "action": result.action,
        "status": result.status,
        "message": result.message,
    }


def _candidate_note(candidate: ResetCandidate, lang: str) -> str:
    return text_for(lang, zh=candidate.note_zh, en=candidate.note_en) if candidate.note_zh or candidate.note_en else ""


def _localized(definition: ResetItemDefinition, field: str, lang: str) -> str:
    zh = getattr(definition, f"{field}_zh")
    en = getattr(definition, f"{field}_en")
    return text_for(lang, zh=zh, en=en)


def _localized_rebuild_hint(definition: ResetItemDefinition, lang: str) -> str:
    if not definition.rebuild_hint_zh and not definition.rebuild_hint_en:
        return ""
    return text_for(lang, zh=definition.rebuild_hint_zh, en=definition.rebuild_hint_en)


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _sum_existing_size(candidates: Iterable[ResetCandidate]) -> int:
    return sum(_path_size(candidate.path) for candidate in candidates if candidate.path.exists())


def _sum_file_count(candidates: Iterable[ResetCandidate]) -> int:
    return sum(_path_file_count(candidate.path) for candidate in candidates if candidate.path.exists())


def _sum_result_file_count(results: Iterable[ResetActionResult]) -> int:
    return sum(1 for _ in results)


def _path_file_count(path: Path) -> int:
    try:
        if path.is_file():
            return 1
        if path.is_dir():
            count = 0
            scanned = 0
            for child in path.rglob("*"):
                scanned += 1
                if scanned > MAX_SUMMARY_SCAN_ITEMS:
                    break
                if child.is_file():
                    count += 1
            return count
    except OSError:
        return 0
    return 0


def _path_size(path: Path) -> int:
    try:
        if path.is_file():
            return int(path.stat().st_size)
        if path.is_dir():
            total = 0
            scanned = 0
            for child in path.rglob("*"):
                scanned += 1
                if scanned > MAX_SUMMARY_SCAN_ITEMS:
                    break
                try:
                    if child.is_file():
                        total += int(child.stat().st_size)
                except OSError:
                    continue
            return total
    except OSError:
        return 0
    return 0


def _format_size(size_bytes: int) -> str:
    value = float(max(0, int(size_bytes or 0)))
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size_bytes)} B"


def _total_from_item_results(items: list[dict]) -> dict:
    totals = {
        "deleteCount": 0,
        "deleteFileCount": 0,
        "deleteSizeBytes": 0,
        "deletedCount": 0,
        "deletedFileCount": 0,
        "deletedSizeBytes": 0,
        "skippedCount": 0,
        "protectedCount": 0,
        "failedCount": 0,
    }
    for item in items:
        summary = item.get("summary") if isinstance(item, dict) else {}
        if not isinstance(summary, dict):
            continue
        for key in totals:
            totals[key] += int(summary.get(key) or 0)
    return totals


def _preview_summary(totals: dict, lang: str) -> str:
    return text_for(
        lang,
        zh=(
            f"预览到 {totals.get('deleteCount', 0)} 个待处理目标，"
            f"约 {_format_size(totals.get('deleteSizeBytes', 0))}，"
            f"{totals.get('protectedCount', 0)} 个受保护目标会跳过。"
        ),
        en=(
            f"Preview found {totals.get('deleteCount', 0)} target(s), "
            f"about {_format_size(totals.get('deleteSizeBytes', 0))}, "
            f"with {totals.get('protectedCount', 0)} protected target(s) skipped."
        ),
    )


def _execute_summary(totals: dict, lang: str) -> str:
    return text_for(
        lang,
        zh=(
            f"清理完成：{totals.get('deletedCount', 0)} 个目标已处理，"
            f"{totals.get('skippedCount', 0)} 个跳过，"
            f"{totals.get('failedCount', 0)} 个失败。"
        ),
        en=(
            f"Cleanup complete: {totals.get('deletedCount', 0)} target(s) handled, "
            f"{totals.get('skippedCount', 0)} skipped, "
            f"{totals.get('failedCount', 0)} failed."
        ),
    )


def _collect_rebuild_hints(definitions: list[ResetItemDefinition], lang: str) -> list[str]:
    hints: list[str] = []
    for definition in definitions:
        hint = _localized_rebuild_hint(definition, lang)
        if hint and hint not in hints:
            hints.append(hint)
    return hints


def _is_conversation_log_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        name.startswith("conversation_")
        or name.startswith("debug_")
        or name.startswith("transcript")
        or name.endswith(".jsonl")
        or name.endswith(".log")
    )


def _runtime_scene_status(scene_dir: Path) -> str:
    try:
        manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    if not isinstance(manifest, dict):
        return "unknown"
    return str(manifest.get("status") or "unknown").strip().lower() or "unknown"


def _launcher_state() -> dict[str, Any]:
    path = PROJECT_ROOT / ".runtime" / "launcher" / "state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _current_runtime_scene_dir() -> Path | None:
    raw = str(_launcher_state().get("runtimeSceneDir") or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).resolve()
    except OSError:
        return None
    root = (PROJECT_ROOT / "logs" / "runtime_scenes").resolve()
    if not _is_relative_to(path, root):
        return None
    return path if path.exists() else None


def _current_browser_profile_dir() -> Path | None:
    raw = str(_launcher_state().get("browserProfileDir") or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).resolve()
    except OSError:
        return None
    runtime_root = (PROJECT_ROOT / ".runtime").resolve()
    if not _is_relative_to(path, runtime_root):
        return None
    return path if path.exists() else None


def _walk_project_paths(root: Path, *, skip_roots: list[Path] | None = None):
    resolved_root = _resolve_project_path(root)
    resolved_skips = [path.resolve() for path in list(skip_roots or []) if path is not None]
    for current, dirnames, filenames in os.walk(resolved_root, topdown=True):
        current_path = Path(current).resolve()
        if _has_ignored_part(current_path) or any(_same_or_child(current_path, skip) for skip in resolved_skips):
            dirnames[:] = []
            continue
        kept_dirs: list[str] = []
        for dirname in dirnames:
            child = (current_path / dirname).resolve()
            if _has_ignored_part(child) or any(_same_or_child(child, skip) for skip in resolved_skips):
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for dirname in kept_dirs:
            yield current_path / dirname
        for filename in filenames:
            yield current_path / filename


def _has_ignored_part(path: Path) -> bool:
    ignored = {".venv", "node_modules", ".git"}
    return any(part in ignored for part in path.parts)


def _dedupe_candidates(candidates: Iterable[ResetCandidate]) -> list[ResetCandidate]:
    seen: set[str] = set()
    result: list[ResetCandidate] = []
    for candidate in candidates:
        key = str(candidate.path).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _collapse_nested_candidates(candidates: list[ResetCandidate]) -> list[ResetCandidate]:
    collapsed: list[ResetCandidate] = []
    for candidate in sorted(candidates, key=lambda item: len(item.path.parts)):
        if candidate.protected:
            collapsed.append(candidate)
            continue
        if any(
            not existing.protected and _is_relative_to(candidate.path, existing.path)
            for existing in collapsed
        ):
            continue
        collapsed.append(candidate)
    return collapsed


def _same_path(left: Path, right: Path) -> bool:
    return str(left.resolve()).lower() == str(right.resolve()).lower()


def _same_or_child(path: Path, parent: Path) -> bool:
    return _same_path(path, parent) or _is_relative_to(path, parent)


def _is_relative_to(path: Path | None, parent: Path | None) -> bool:
    if path is None or parent is None:
        return False
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
