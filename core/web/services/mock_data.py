"""Mock data used while the web workbench is being wired to live sources."""

from __future__ import annotations

import copy

from .i18n import get_web_language, text_for
from .workbench_contract_service import get_workbench_contract


def _session_data(lang: str) -> tuple[list[dict], dict[str, dict]]:
    sessions = [
        {
            "id": "chat-coding-shell",
            "title": text_for(lang, zh="Chat / Coding 壳构建", en="Chat / Coding shell buildout"),
            "status": "running",
            "taskSummary": text_for(
                lang,
                zh="搭起第一版网页工作台 shell 和静态路由",
                en="Stand up the first web shell and static route wiring",
            ),
            "lastActive": text_for(lang, zh="刚刚", en="just now"),
            "currentPhase": text_for(lang, zh="布局接线", en="wiring layout"),
        },
        {
            "id": "evolution-surface-review",
            "title": text_for(lang, zh="进化界面复盘", en="Evolution surface review"),
            "status": "waiting",
            "taskSummary": text_for(
                lang,
                zh="让 runs 和 library 的 framing 与新 IA 保持一致",
                en="Keep the runs and library framing aligned with the new IA",
            ),
            "lastActive": text_for(lang, zh="18 分钟前", en="18 min ago"),
            "currentPhase": text_for(lang, zh="等待中", en="waiting"),
        },
        {
            "id": "config-unification",
            "title": text_for(lang, zh="配置统一化预备", en="Config unification prep"),
            "status": "done",
            "taskSummary": text_for(
                lang,
                zh="在网页 shell 长出来时继续保持 config 单一事实源",
                en="Keep config as a single source while the web shell grows around it",
            ),
            "lastActive": text_for(lang, zh="2 小时前", en="2 hrs ago"),
            "currentPhase": text_for(lang, zh="已完成", en="done"),
        },
    ]

    details = {
        "chat-coding-shell": {
            "id": "chat-coding-shell",
            "title": sessions[0]["title"],
            "status": "running",
            "taskSummary": sessions[0]["taskSummary"],
            "lastActive": sessions[0]["lastActive"],
            "currentPhase": sessions[0]["currentPhase"],
            "defaultFileContext": "docs/plans/2026-05-18-vibelution-web-workbench-hi-fi-spec.md",
            "previewTabs": [
                "docs/plans/2026-05-18-vibelution-web-workbench-hi-fi-spec.md",
                "core/ui/workbench.py",
            ],
            "activePreviewPath": "docs/plans/2026-05-18-vibelution-web-workbench-hi-fi-spec.md",
            "changedFiles": [
                "core/web/app.py",
                "core/web/services/file_service.py",
                "web/src/routes/ChatCodingRoute.tsx",
            ],
            "messages": [
                {
                    "id": "m1",
                    "role": "user",
                    "content": text_for(
                        lang,
                        zh="开始实现第一阶段网页工作台。",
                        en="Start implementing the first web workbench phase.",
                    ),
                },
                {
                    "id": "m2",
                    "role": "assistant",
                    "content": text_for(
                        lang,
                        zh="我先铺 FastAPI adapter、React shell，以及只读文件预览链路。",
                        en="I am laying down the FastAPI adapter, the React shell, and a read-only file preview flow first.",
                    ),
                    "toolCalls": [
                        {"name": text_for(lang, zh="读取仓库状态", en="read repo state"), "status": "done"},
                        {"name": text_for(lang, zh="起草栈计划", en="draft stack plan"), "status": "done"},
                    ],
                },
                {
                    "id": "m3",
                    "role": "assistant",
                    "content": text_for(
                        lang,
                        zh="第一阶段先把 sessions 和 evolution 保持 mock，同时把文件树和文件预览接到真实仓库。",
                        en="The first phase keeps session and evolution data mocked, while file tree and file preview are wired to the real workspace.",
                    ),
                    "toolCalls": [
                        {
                            "name": text_for(lang, zh="构建文件树路由", en="build file tree route"),
                            "status": "running",
                        },
                        {
                            "name": text_for(lang, zh="搭前端外壳", en="scaffold frontend shell"),
                            "status": "queued",
                        },
                    ],
                },
            ],
        },
        "evolution-surface-review": {
            "id": "evolution-surface-review",
            "title": sessions[1]["title"],
            "status": "waiting",
            "taskSummary": sessions[1]["taskSummary"],
            "lastActive": sessions[1]["lastActive"],
            "currentPhase": sessions[1]["currentPhase"],
            "defaultFileContext": "docs/plans/2026-05-18-vibelution-web-workbench-visual-brief.md",
            "previewTabs": [
                "docs/plans/2026-05-18-vibelution-web-workbench-visual-brief.md",
            ],
            "activePreviewPath": "docs/plans/2026-05-18-vibelution-web-workbench-visual-brief.md",
            "changedFiles": [
                "docs/plans/2026-05-18-vibelution-web-workbench-visual-brief.md",
            ],
            "messages": [
                {
                    "id": "m1",
                    "role": "assistant",
                    "content": text_for(
                        lang,
                        zh="进化界面应该让 Overview 留在前面，再让 Runs 和 Library 承接细节。",
                        en="The evolution surface should keep Overview in front, then let Runs and Library carry the detail load.",
                    ),
                }
            ],
        },
        "config-unification": {
            "id": "config-unification",
            "title": sessions[2]["title"],
            "status": "done",
            "taskSummary": sessions[2]["taskSummary"],
            "lastActive": sessions[2]["lastActive"],
            "currentPhase": sessions[2]["currentPhase"],
            "defaultFileContext": "scripts/config_panel.py",
            "previewTabs": [
                "scripts/config_panel.py",
            ],
            "activePreviewPath": "scripts/config_panel.py",
            "changedFiles": [
                "scripts/config_panel.py",
            ],
            "messages": [
                {
                    "id": "m1",
                    "role": "assistant",
                    "content": text_for(
                        lang,
                        zh="Config 继续保持独立页面，并沿用 config.toml 驱动的单一事实源。",
                        en="Config stays a separate page and keeps one source of truth in config.toml-backed workflows.",
                    ),
                }
            ],
        },
    }
    return sessions, details


def _evolution_overview(lang: str) -> dict:
    contract = get_workbench_contract()
    return {
        "intakeMode": contract["intakeMode"],
        "currentStatus": {
            "state": "idle",
            "stage": text_for(lang, zh="准备下一轮运行", en="ready_for_next_run"),
            "lastResult": text_for(
                lang,
                zh="最新一版进化规格已经落进 docs，目前等待 UI 实现继续推进。",
                en="Latest evolution spec pass landed in docs and awaits UI implementation.",
            ),
        },
        "recentRuns": [
            {
                "id": "run-143",
                "score": 81,
                "status": "success",
                "summary": text_for(lang, zh="统一工作台 IA 已锁定", en="Unified workbench IA locked"),
            },
            {
                "id": "run-142",
                "score": 43,
                "status": "failed",
                "summary": text_for(
                    lang,
                    zh="Config 和 history 语义仍然纠缠",
                    en="Config and history semantics were still tangled",
                ),
            },
            {
                "id": "run-141",
                "score": 77,
                "status": "success",
                "summary": text_for(lang, zh="Evolution 总览方向已厘清", en="Evolution overview direction clarified"),
            },
        ],
        "recentLibrary": [
            {
                "id": "lib-11",
                "title": text_for(lang, zh="Codex 风格直接写入工作流", en="Codex-style direct-write workflow"),
                "source": "manual-approved",
            },
            {
                "id": "lib-12",
                "title": text_for(lang, zh="只读文件预览界面", en="Preview-only file reading surface"),
                "source": "manual-approved",
            },
        ],
    }


def _runs(lang: str) -> list[dict]:
    return [
        {
            "id": "run-143",
            "score": 81,
            "status": "success",
            "summary": text_for(lang, zh="统一工作台 IA 已锁定", en="Unified workbench IA locked"),
            "diagnosis": text_for(
                lang,
                zh="当第一阶段去掉文件编辑，只保留阅读与预览后，整个 shell 很快收敛了。",
                en="The shell converged once file editing was removed from the first phase.",
            ),
        },
        {
            "id": "run-142",
            "score": 43,
            "status": "failed",
            "summary": text_for(
                lang,
                zh="Config 和 history 语义仍然纠缠",
                en="Config and history semantics were still tangled",
            ),
            "diagnosis": text_for(
                lang,
                zh="当时的设计仍把 history 当成顶层概念，而不是 evolution 记录层。",
                en="The design still treated history as a top-level concept instead of an evolution record layer.",
            ),
        },
        {
            "id": "run-141",
            "score": 77,
            "status": "success",
            "summary": text_for(lang, zh="Evolution 总览方向已厘清", en="Evolution overview direction clarified"),
            "diagnosis": text_for(
                lang,
                zh="混合式 overview 比强迫用户先进 runs 或 library 更自然。",
                en="A mixed overview worked better than forcing users into runs or library first.",
            ),
        },
    ]


def _library_items(lang: str) -> list[dict]:
    return [
        {
            "id": "lib-11",
            "title": text_for(lang, zh="Codex 风格直接写入工作流", en="Codex-style direct-write workflow"),
            "type": text_for(lang, zh="工作流模式", en="workflow pattern"),
            "sourceRun": "run-143",
            "ingestMode": "manual-approved",
        },
        {
            "id": "lib-12",
            "title": text_for(lang, zh="只读文件预览界面", en="Preview-only file reading surface"),
            "type": text_for(lang, zh="界面决策", en="surface decision"),
            "sourceRun": "run-143",
            "ingestMode": "manual-approved",
        },
    ]


def _pending_library_items(lang: str) -> list[dict]:
    return [
        {
            "id": "cand-3",
            "title": text_for(lang, zh="Warm Workshop 调色 token 集", en="Warm Workshop palette token set"),
            "sourceRun": "run-144",
            "reason": text_for(
                lang,
                zh="这组设计 token 很适合作为第一版静态 shell 的视觉基线。",
                en="Promising design token baseline for the first static shell build.",
            ),
        }
    ]


def list_sessions() -> list[dict]:
    lang = get_web_language()
    sessions, _ = _session_data(lang)
    return copy.deepcopy(sessions)


def get_session_detail(session_id: str) -> dict | None:
    lang = get_web_language()
    _, details = _session_data(lang)
    detail = details.get(session_id)
    return copy.deepcopy(detail) if detail else None


def get_evolution_overview() -> dict:
    return copy.deepcopy(_evolution_overview(get_web_language()))


def list_runs() -> list[dict]:
    return copy.deepcopy(_runs(get_web_language()))


def list_library_items() -> list[dict]:
    return copy.deepcopy(_library_items(get_web_language()))


def list_pending_library_items() -> list[dict]:
    return copy.deepcopy(_pending_library_items(get_web_language()))
