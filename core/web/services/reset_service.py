"""Reset menu summary helpers."""

from __future__ import annotations

from pathlib import Path

import reset as reset_script

from .i18n import get_web_language, text_for


RESET_CATEGORY_TRANSLATIONS = {
    "1": {
        "name": {"zh": "Agent 工作区", "en": "Agent workspace"},
        "description": {
            "zh": "记忆、技能、提示词、策略、进化历史、SQLite 数据库、对话 transcript",
            "en": "Memory, skills, prompts, strategies, evolution history, SQLite data, and chat transcripts",
        },
        "detail": {"zh": "workspace/ 整个目录", "en": "the full workspace/ directory"},
    },
    "2": {
        "name": {"zh": "会话日志 (log_info)", "en": "Session logs (log_info)"},
        "description": {"zh": "~107 个对话 JSONL 日志文件", "en": "~107 JSONL conversation log files"},
        "detail": {"zh": "log_info/ 整个目录", "en": "the full log_info/ directory"},
    },
    "3": {
        "name": {"zh": "运行日志 (logs)", "en": "Runtime logs (logs)"},
        "description": {"zh": "agent_realtime.log, restarter_realtime.log", "en": "agent_realtime.log and restarter_realtime.log"},
        "detail": {"zh": "logs/ 整个目录", "en": "the full logs/ directory"},
    },
    "4": {
        "name": {"zh": "旧备份", "en": "Old backups"},
        "description": {"zh": "10 个旧 agent 备份（zip + py）", "en": "10 older agent backups (zip + py)"},
        "detail": {"zh": "backups/ 整个目录", "en": "the full backups/ directory"},
    },
    "5": {
        "name": {"zh": "Python 字节码缓存", "en": "Python bytecode cache"},
        "description": {
            "zh": "所有 __pycache__/ 目录（约 125 个 .pyc 文件）",
            "en": "All __pycache__/ directories (about 125 .pyc files)",
        },
        "detail": {"zh": "递归查找并删除所有 __pycache__/", "en": "recursively find and remove all __pycache__/"},
    },
    "6": {
        "name": {"zh": "Pytest 缓存", "en": "Pytest cache"},
        "description": {"zh": "测试运行缓存", "en": "test run cache"},
        "detail": {"zh": ".pytest_cache/ 整个目录", "en": "the full .pytest_cache/ directory"},
    },
    "7": {
        "name": {"zh": "Claude 会话权限", "en": "Claude session permissions"},
        "description": {"zh": "累积的 56 条 Bash 权限许可", "en": "56 accumulated Bash permission grants"},
        "detail": {"zh": ".claude/settings.local.json", "en": ".claude/settings.local.json"},
    },
    "8": {
        "name": {"zh": "CodeArtsDoer 快照", "en": "CodeArtsDoer snapshots"},
        "description": {"zh": "规范驱动开发临时文件与原文件快照", "en": "spec-driven temporary files and source snapshots"},
        "detail": {"zh": ".codeartsdoer/ 整个目录", "en": "the full .codeartsdoer/ directory"},
    },
    "9": {
        "name": {"zh": "Arts 编辑器配置", "en": "Arts editor config"},
        "description": {"zh": "UI 编辑器模式配置", "en": "UI editor mode configuration"},
        "detail": {"zh": ".arts/ 整个目录", "en": "the full .arts/ directory"},
    },
}

RESET_PRESET_TRANSLATIONS = {
    "deep": {
        "zh": "深度清理 — Agent 完全失忆（清除全部 9 项）",
        "en": "Deep clean - full agent amnesia (clear all 9 categories)",
    },
    "standard": {
        "zh": "标准清理 — 保留开发工具配置（清除 1-7 项）",
        "en": "Standard clean - keep developer tool config (clear categories 1-7)",
    },
    "light": {
        "zh": "轻度清理 — 仅清记忆+日志（清除 1-4 项）",
        "en": "Light clean - memory and logs only (clear categories 1-4)",
    },
}


def get_reset_summary() -> dict:
    """Return the current reset menu inventory without executing destructive actions."""

    lang = get_web_language()
    categories = []
    for key, category in reset_script.CATEGORIES.items():
        path = category["path"]
        exists = _category_exists(path)
        translated = RESET_CATEGORY_TRANSLATIONS.get(key, {})
        categories.append(
            {
                "id": key,
                "name": translated.get("name", {}).get(lang, category["name"]),
                "description": translated.get("description", {}).get(lang, category["desc"]),
                "detail": translated.get("detail", {}).get(lang, category["detail"]),
                "exists": exists,
                "size": reset_script.size_fmt(path) if path else text_for(lang, zh="递归扫描", en="recursive scan"),
                "fileCount": _category_file_count(path),
            }
        )

    presets = [
        {
            "id": preset_id,
            "label": RESET_PRESET_TRANSLATIONS.get(preset_id, {}).get(lang, preset["label"]),
            "keys": sorted(preset["keys"], key=int),
        }
        for preset_id, preset in reset_script.PRESETS.items()
    ]

    return {
        "warning": text_for(
            lang,
            zh="第一阶段的 Reset 仍然保持确认门槛，并继续由 CLI 执行。网页这边先以可见性和盘点为主。",
            en="Reset actions remain confirm-gated and CLI-backed in phase 1. The web page is a visibility surface first.",
        ),
        "presets": presets,
        "categories": categories,
    }


def _category_exists(path: Path | None) -> bool:
    if path is None:
        return any(
            item.is_dir() and ".venv" not in item.parts for item in reset_script.ROOT.rglob("__pycache__")
        )
    return path.exists()


def _category_file_count(path: Path | None) -> int:
    if path is None:
        return sum(
            1 for item in reset_script.ROOT.rglob("__pycache__") if item.is_dir() and ".venv" not in item.parts
        )
    if not path.exists():
        return 0
    return reset_script.count_files(path)
