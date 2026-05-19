"""Real self-evolution payloads for the web workbench."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from config import get_config
from core.evaluation import (
    DEFAULT_SELF_EVOLUTION_GOAL,
    build_self_evolution_snapshot,
    list_recent_self_evolution_transaction_payloads,
    load_self_evolution_audit_records,
)

from .i18n import get_web_language, text_for
from .workbench_contract_service import get_workbench_contract


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class SelfEvolutionHistoryDeleteError(ValueError):
    """Raised when a requested self-evolution history deletion is invalid."""


def get_self_evolution_overview() -> dict[str, Any]:
    """Return current self-evolution evidence for the web surface."""

    contract = get_workbench_contract()
    enabled = _self_evolution_enabled(contract)
    lang = get_web_language()
    snapshot = (
        build_self_evolution_snapshot(project_root=PROJECT_ROOT, transaction_limit=6, recent_limit=4)
        if enabled
        else _empty_snapshot()
    )
    advisory = snapshot.get("advisory", {})
    worktree = snapshot.get("worktree", {})
    fitness = snapshot.get("fitness", {})
    recent_transactions = snapshot.get("recent_transactions", [])
    readiness = _build_readiness(lang, enabled=enabled, worktree=worktree, recent_transactions=recent_transactions)

    return {
        "enabled": enabled,
        "goal": str(snapshot.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL),
        "readiness": readiness,
        "sceneSemantics": _scene_semantics(readiness),
        "runSemantics": _overview_run_semantics(recent_transactions, lang=lang),
        "actionStates": {
            "start": _start_action_state(enabled=enabled, lang=lang),
        },
        "guardrails": _guardrails(lang),
        "metrics": _build_metrics(advisory, worktree, fitness, recent_transactions),
        "advisory": _advisory_payload(advisory),
        "gitStatus": _git_status_payload(snapshot.get("git_status", {}), lang),
        "recentChanges": _recent_changes_payload(snapshot.get("recent_changes", [])),
        "fitness": _fitness_payload(fitness),
        "worktree": _worktree_payload(worktree),
        "recentTransactions": _transaction_payloads(recent_transactions[:4]),
        "auditTail": _audit_payloads(load_self_evolution_audit_records(PROJECT_ROOT, limit=6)),
    }


def list_self_evolution_transactions() -> list[dict[str, Any]]:
    if not _self_evolution_enabled():
        return []
    return _transaction_payloads(
        list_recent_self_evolution_transaction_payloads(PROJECT_ROOT, limit=24)
    )


def list_self_evolution_audit_events() -> list[dict[str, Any]]:
    if not _self_evolution_enabled():
        return []
    return _audit_payloads(load_self_evolution_audit_records(PROJECT_ROOT, limit=24))


def delete_self_evolution_history_groups(txn_ids: list[str]) -> dict[str, Any]:
    if not _self_evolution_enabled():
        return {
            "requestedCount": 0,
            "deletedGroupCount": 0,
            "deletedAuditCount": 0,
            "summary": "",
            "deletedTxnIds": [],
            "blockedTxnIds": [],
        }

    normalized_ids: list[str] = []
    seen: set[str] = set()
    for item in txn_ids:
        txn_id = str(item or "").strip()
        if not txn_id or txn_id in seen:
            continue
        seen.add(txn_id)
        normalized_ids.append(txn_id)
    if not normalized_ids:
        raise SelfEvolutionHistoryDeleteError(
            text_for(
                get_web_language(),
                zh="请先选择至少一组可删除的历史记录。",
                en="Select at least one history group to delete.",
            )
        )

    transactions = {
        str(item.get("txn_id") or ""): item
        for item in list_recent_self_evolution_transaction_payloads(PROJECT_ROOT, limit=512)
        if isinstance(item, dict)
    }
    blocked_ids = [
        txn_id
        for txn_id in normalized_ids
        if bool((transactions.get(txn_id) or {}).get("is_open"))
    ]
    if blocked_ids:
        raise SelfEvolutionHistoryDeleteError(
            text_for(
                get_web_language(),
                zh=f"以下历史组仍属于当前现场，暂时不能删除: {', '.join(blocked_ids)}",
                en=f"These history groups still belong to the current scene and cannot be deleted yet: {', '.join(blocked_ids)}",
            )
        )

    deleted_group_count = _delete_transaction_groups(PROJECT_ROOT, normalized_ids)
    deleted_audit_count = _delete_audit_groups(PROJECT_ROOT, normalized_ids)
    deleted_txn_ids = [txn_id for txn_id in normalized_ids if txn_id not in blocked_ids]
    return {
        "requestedCount": len(normalized_ids),
        "deletedGroupCount": deleted_group_count,
        "deletedAuditCount": deleted_audit_count,
        "summary": text_for(
            get_web_language(),
            zh=f"已删除 {deleted_group_count} 组历史记录，并同步清理 {deleted_audit_count} 条关联审计。",
            en=f"Deleted {deleted_group_count} history groups and cleaned up {deleted_audit_count} linked audit events.",
        ),
        "deletedTxnIds": deleted_txn_ids,
        "blockedTxnIds": blocked_ids,
    }


def _empty_snapshot() -> dict[str, Any]:
    return {
        "goal": DEFAULT_SELF_EVOLUTION_GOAL,
        "advisory": {"active_count": 0, "entries": []},
        "git_status": {"summary": "git 状态暂不可用", "lines": ["git 状态暂不可用"]},
        "recent_changes": [],
        "fitness": {},
        "worktree": {
            "available": False,
            "error": "self_evolution_disabled",
            "snapshot_id": "",
            "created_at": "",
            "base_rev": "",
            "has_staged": False,
            "has_unstaged": False,
            "has_untracked": False,
            "is_dirty": False,
            "dirty_file_count": 0,
            "files": [],
        },
        "recent_transactions": [],
    }


def _self_evolution_enabled(contract: dict[str, Any] | None = None) -> bool:
    active_contract = contract or get_workbench_contract()
    return bool(active_contract.get("modeAvailability", {}).get("self_evolution"))


def _build_readiness(
    lang: str,
    *,
    enabled: bool,
    worktree: dict[str, Any],
    recent_transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    if not enabled:
        return {
            "state": "disabled",
            "title": text_for(lang, zh="当前未启用无监督进化", en="Self evolution is disabled"),
            "summary": text_for(
                lang,
                zh="配置里没有启用 self_evolution，因此前端不会把它当成可运行轨道。",
                en="The current config does not enable self_evolution, so the web surface keeps this track unavailable.",
            ),
            "nextAction": text_for(
                lang,
                zh="先在配置中启用 self_evolution，再回到这里查看真实现场或启动一轮。",
                en="Enable self_evolution in config first, then return here to inspect the live evidence or launch a pass.",
            ),
            "reasons": [],
        }

    reasons: list[str] = []
    state = "ready"
    latest = recent_transactions[0] if recent_transactions else None
    if not worktree.get("available", False):
        state = "caution"
        reasons.append(
            text_for(lang, zh="当前无法读取工作区快照。", en="The current worktree snapshot is unavailable.")
        )
    if worktree.get("is_dirty"):
        state = "caution"
        reasons.append(
            text_for(
                lang,
                zh="工作区里已经有未提交改动，这里是共享现场。",
                en="The worktree already has uncommitted changes, so this is a shared scene.",
            )
        )
    if latest and latest.get("status") in {"failed", "blocked"}:
        state = "caution"
        reasons.append(
            text_for(
                lang,
                zh="最近一条自进化事务没有成功收口。",
                en="The latest self-evolution transaction did not close successfully.",
            )
        )
    if latest and latest.get("is_open"):
        state = "caution"
        reasons.append(
            text_for(
                lang,
                zh="最近一条自进化事务还处于打开状态。",
                en="The latest self-evolution transaction is still open.",
            )
        )
    if not recent_transactions and state == "ready":
        state = "idle"

    if state == "caution":
        return {
            "state": state,
            "title": text_for(lang, zh="先看现场再继续", en="Inspect the scene before continuing"),
            "summary": reasons[0],
            "nextAction": text_for(
                lang,
                zh="先回看工作区快照和最近事务，再决定是否继续修改。",
                en="Review the worktree snapshot and recent transactions before deciding whether to keep changing code.",
            ),
            "reasons": reasons,
        }
    if state == "idle":
        return {
            "state": state,
            "title": text_for(lang, zh="还没有形成一轮自进化现场", en="No self-evolution pass has formed yet"),
            "summary": text_for(
                lang,
                zh="目前还没有最近事务记录，这里更像启动前的观察面。",
                en="There is no recent transaction history yet, so this surface is still more of a preflight view.",
            ),
            "nextAction": text_for(
                lang,
                zh="先建立第一条自进化事务，再回来看这条线的趋势。",
                en="Create the first self-evolution transaction, then return to inspect the trend on this track.",
            ),
            "reasons": [],
        }
    return {
        "state": state,
        "title": text_for(lang, zh="这条线目前可继续观察", en="This track is ready for continued observation"),
        "summary": text_for(
            lang,
            zh="当前没有明显的共享现场风险，可以结合事务历史和 fitness 继续判断下一步。",
            en="No obvious shared-scene risk is visible right now. Use the transaction history and fitness signals to judge the next move.",
        ),
        "nextAction": text_for(
            lang,
            zh="优先对照 advisory、事务历史和 fitness，再决定是否继续推进。",
            en="Compare advisory, transaction history, and fitness before deciding whether to continue.",
        ),
        "reasons": [],
    }


def _scene_semantics(readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        "sceneState": str(readiness.get("state") or "idle"),
        "sceneTitle": str(readiness.get("title") or ""),
        "sceneSummary": str(readiness.get("summary") or ""),
        "blockers": [str(item).strip() for item in list(readiness.get("reasons") or []) if str(item).strip()],
        "nextAction": str(readiness.get("nextAction") or ""),
    }


def _overview_run_semantics(recent_transactions: list[dict[str, Any]], *, lang: str) -> dict[str, Any]:
    latest = recent_transactions[0] if recent_transactions else None
    if not isinstance(latest, dict):
        return {
            "runStatus": "idle",
            "runStatusLabel": _status_label("idle", lang=lang),
            "phase": "idle",
            "phaseLabel": text_for(lang, zh="还没有形成最近一轮", en="No recent pass yet"),
            "rollbackState": "unavailable",
            "rollbackStateLabel": _rollback_state_label("unavailable", lang=lang),
            "rollbackSummary": text_for(
                lang,
                zh="回滚状态要等真实运行结束后，才会在本轮详情里出现。",
                en="Rollback state only appears in the live run detail after a real pass closes.",
            ),
        }

    status = str(latest.get("status") or "unknown")
    is_open = bool(latest.get("is_open"))
    if is_open:
        phase = "open_transaction"
        phase_label = text_for(lang, zh="最近事务还没有关账", en="The latest transaction is still open")
    elif status in {"failed", "blocked", "cancelled"}:
        phase = "recent_risk"
        phase_label = text_for(lang, zh="最近一轮带风险收口", en="The latest pass closed with risk")
    else:
        phase = "recent_closed"
        phase_label = text_for(lang, zh="最近一轮已经关账", en="The latest pass has closed")
    return {
        "runStatus": status,
        "runStatusLabel": _status_label(status, lang=lang),
        "phase": phase,
        "phaseLabel": phase_label,
        "rollbackState": "unavailable",
        "rollbackStateLabel": _rollback_state_label("unavailable", lang=lang),
        "rollbackSummary": text_for(
            lang,
            zh="当前总览只说明最近事务状态；可执行回滚要看具体运行的回滚清单。",
            en="This overview only summarizes the latest transaction; actionable rollback lives on the concrete run snapshot.",
        ),
    }


def _start_action_state(*, enabled: bool, lang: str) -> dict[str, Any]:
    if enabled:
        return {"enabled": True, "reason": ""}
    return {
        "enabled": False,
        "reason": text_for(
            lang,
            zh="当前配置没有启用 self_evolution，因此还不能从网页启动这一轮。",
            en="The current config does not enable self_evolution, so the web surface cannot launch this pass yet.",
        ),
    }


def _status_label(status: str, *, lang: str) -> str:
    normalized = str(status or "").strip().lower() or "idle"
    mapping = {
        "idle": text_for(lang, zh="暂无运行", en="No run yet"),
        "done": text_for(lang, zh="已完成", en="Completed"),
        "failed": text_for(lang, zh="已失败", en="Failed"),
        "blocked": text_for(lang, zh="受阻", en="Blocked"),
        "cancelled": text_for(lang, zh="已取消", en="Cancelled"),
        "open": text_for(lang, zh="未关账", en="Still open"),
    }
    return mapping.get(normalized, normalized)


def _rollback_state_label(status: str, *, lang: str) -> str:
    normalized = str(status or "").strip().lower() or "unavailable"
    mapping = {
        "available": text_for(lang, zh="可安全回滚", en="Safe rollback ready"),
        "blocked": text_for(lang, zh="回滚冲突待处理", en="Rollback blocked by conflict"),
        "rolled_back": text_for(lang, zh="已完成回滚", en="Rolled back"),
        "unavailable": text_for(lang, zh="暂不可回滚", en="Rollback unavailable"),
    }
    return mapping.get(normalized, normalized)


def _guardrails(lang: str) -> list[str]:
    return [
        text_for(
            lang,
            zh="active advisory baseline 只作为观察参照，不代表已经自动改写运行时。",
            en="The active advisory baseline is observational context only. It does not mean runtime behavior has already been rewritten.",
        ),
        text_for(
            lang,
            zh="如果工作区里已有未提交改动，要先把它理解成共享现场，而不是默认可以直接接着改。",
            en="If the worktree already has uncommitted changes, treat it as a shared scene instead of assuming it is safe to keep mutating immediately.",
        ),
        text_for(
            lang,
            zh="网页入口现在可以启动一轮有界自进化，但仍要遵守共享现场与验证护栏。",
            en="The web surface can now launch one bounded self-evolution pass, but shared-scene and validation guardrails still apply.",
        ),
    ]


def _build_metrics(
    advisory: dict[str, Any],
    worktree: dict[str, Any],
    fitness: dict[str, Any],
    recent_transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    fitness_transactions = fitness.get("transactions") if isinstance(fitness.get("transactions"), dict) else {}
    fitness_validation = fitness.get("validation") if isinstance(fitness.get("validation"), dict) else {}
    return {
        "activeAdvisories": int(advisory.get("active_count") or 0),
        "dirtyFiles": int(worktree.get("dirty_file_count") or 0),
        "recentTransactions": len(recent_transactions),
        "successRate": fitness_transactions.get("success_rate"),
        "validationPassRate": fitness_validation.get("pass_rate"),
    }


def _advisory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    return {
        "activeCount": int(payload.get("active_count") or 0),
        "entries": [
            {
                "targetKey": str(item.get("target_key") or ""),
                "targetLabel": str(item.get("target_label") or ""),
                "proposalId": str(item.get("proposal_id") or ""),
                "episodeId": str(item.get("episode_id") or ""),
                "candidateImprovementId": str(item.get("candidate_improvement_id") or ""),
                "activatedAt": str(item.get("activated_at") or ""),
                "runtimeEffect": str(item.get("runtime_effect") or "not_applied"),
                "agentConsumption": str(item.get("agent_consumption") or "advisory"),
                "proposalPath": str(item.get("proposal_path") or ""),
                "decisionPath": str(item.get("decision_path") or ""),
                "traceIndexPath": str(item.get("trace_index_path") or ""),
            }
            for item in entries
            if isinstance(item, dict)
        ],
    }


def _git_status_payload(payload: dict[str, Any], lang: str) -> dict[str, Any]:
    raw_summary = str(payload.get("summary") or "")
    lines = payload.get("lines") if isinstance(payload.get("lines"), list) else []
    parsed = _parse_git_status_summary(raw_summary)
    compact_lines = _compact_git_status_lines(parsed, lang)
    fallback_lines = [str(line).strip() for line in lines if str(line).strip()]
    resolved_lines = compact_lines or fallback_lines
    summary = resolved_lines[0] if resolved_lines else raw_summary.strip()
    return {
        "summary": summary,
        "lines": resolved_lines,
    }


def _parse_git_status_summary(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw.startswith("{"):
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _compact_git_status_lines(payload: dict[str, Any], lang: str) -> list[str]:
    if not payload:
        return []

    lines: list[str] = []
    dirty_summary = str(payload.get("dirty_summary") or "").strip()
    if dirty_summary:
        lines.append(dirty_summary)

    last_validation_summary = str(payload.get("last_validation_summary") or "").strip()
    if last_validation_summary:
        lines.append(
            text_for(
                lang,
                zh=f"最近验证: {last_validation_summary}",
                en=f"Last validation: {last_validation_summary}",
            )
        )

    recent_changes = payload.get("recent_changes") if isinstance(payload.get("recent_changes"), list) else []
    for item in recent_changes[:3]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        subject = str(item.get("subject") or "").strip()
        change_type = str(item.get("change_type") or "").strip()
        change_summary = subject or change_type
        if change_summary:
            lines.append(f"{path} · {change_summary}")
        else:
            lines.append(path)
    return lines


def _recent_changes_payload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "path": str(item.get("path") or ""),
                "changeType": str(item.get("change_type") or ""),
                "summary": str(item.get("summary") or ""),
            }
        )
    return result


def _delete_transaction_groups(project_root: Path, txn_ids: list[str]) -> int:
    db_path = project_root / "workspace" / "agent_brain.db"
    if not db_path.exists():
        return 0

    placeholders = ", ".join("?" for _ in txn_ids)
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute(
                f"DELETE FROM EvolutionTransaction WHERE txn_id IN ({placeholders})",
                tuple(txn_ids),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
    except sqlite3.Error as exc:
        raise SelfEvolutionHistoryDeleteError(
            text_for(
                get_web_language(),
                zh=f"删除自进化事务失败：{exc}",
                en=f"Failed to delete self-evolution transactions: {exc}",
            )
        ) from exc


def _delete_audit_groups(project_root: Path, txn_ids: list[str]) -> int:
    audit_path = _audit_log_path(project_root)
    if not audit_path.exists():
        return 0

    kept_lines: list[str] = []
    deleted_count = 0
    for raw_line in audit_path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        payload = _parse_json_line(text)
        if isinstance(payload, dict) and str(payload.get("txn_id") or "").strip() in txn_ids:
            deleted_count += 1
            continue
        kept_lines.append(text)

    next_text = ("\n".join(kept_lines) + "\n") if kept_lines else ""
    audit_path.write_text(next_text, encoding="utf-8")
    return deleted_count


def _audit_log_path(project_root: Path) -> Path:
    raw = Path(str(get_config().evolution.audit_log_path or "workspace/evolution/audit.jsonl"))
    if raw.is_absolute():
        return raw
    return project_root / raw


def _parse_json_line(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _fitness_payload(payload: dict[str, Any]) -> dict[str, Any]:
    transactions = payload.get("transactions") if isinstance(payload.get("transactions"), dict) else {}
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    mutations = payload.get("mutations") if isinstance(payload.get("mutations"), dict) else {}
    recent = transactions.get("recent") if isinstance(transactions.get("recent"), list) else []
    return {
        "transactions": {
            "opened": transactions.get("opened", 0),
            "closed": transactions.get("closed", 0),
            "successful": transactions.get("successful", 0),
            "failed": transactions.get("failed", 0),
            "successRate": transactions.get("success_rate"),
            "recent": [
                {
                    "txnId": str(item.get("txn_id") or ""),
                    "status": str(item.get("status") or ""),
                    "validationPassed": item.get("validation_passed", 0),
                    "validationFailed": item.get("validation_failed", 0),
                    "mutationsRecorded": item.get("mutations_recorded", 0),
                }
                for item in recent
                if isinstance(item, dict)
            ],
        },
        "validation": {
            "passed": validation.get("passed", 0),
            "failed": validation.get("failed", 0),
            "passRate": validation.get("pass_rate"),
        },
        "mutations": {
            "recorded": mutations.get("recorded", 0),
            "successful": mutations.get("successful", 0),
            "failed": mutations.get("failed", 0),
            "blocked": mutations.get("blocked", 0),
        },
    }


def _worktree_payload(payload: dict[str, Any]) -> dict[str, Any]:
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    return {
        "available": bool(payload.get("available")),
        "error": str(payload.get("error") or ""),
        "snapshotId": str(payload.get("snapshot_id") or ""),
        "createdAt": str(payload.get("created_at") or ""),
        "baseRev": str(payload.get("base_rev") or ""),
        "hasStaged": bool(payload.get("has_staged")),
        "hasUnstaged": bool(payload.get("has_unstaged")),
        "hasUntracked": bool(payload.get("has_untracked")),
        "isDirty": bool(payload.get("is_dirty")),
        "dirtyFileCount": int(payload.get("dirty_file_count") or 0),
        "files": [
            {
                "path": str(item.get("path") or ""),
                "status": str(item.get("status") or ""),
                "staged": bool(item.get("staged")),
                "unstaged": bool(item.get("unstaged")),
                "untracked": bool(item.get("untracked")),
                "deleted": bool(item.get("deleted")),
            }
            for item in files
            if isinstance(item, dict)
        ],
    }


def _transaction_payloads(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "txnId": str(item.get("txn_id") or ""),
                "openedAt": str(item.get("opened_at") or ""),
                "closedAt": str(item.get("closed_at") or ""),
                "baseRev": str(item.get("base_rev") or ""),
                "baseRevShort": str(item.get("base_rev_short") or ""),
                "status": str(item.get("status") or "unknown"),
                "summary": str(item.get("summary") or ""),
                "isOpen": bool(item.get("is_open")),
            }
        )
    return result


def _audit_payloads(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        target_paths = item.get("target_paths") if isinstance(item.get("target_paths"), list) else []
        result.append(
            {
                "timestamp": str(item.get("timestamp") or ""),
                "event": str(item.get("event") or ""),
                "txnId": str(item.get("txn_id") or ""),
                "status": str(item.get("status") or ""),
                "kind": str(item.get("kind") or ""),
                "message": str(item.get("message") or ""),
                "toolName": str(item.get("tool_name") or ""),
                "baseRev": str(item.get("base_rev") or ""),
                "passed": item.get("passed"),
                "targetPaths": [str(path) for path in target_paths if str(path).strip()],
                "summary": str(item.get("summary") or ""),
            }
        )
    return result
