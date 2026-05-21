"""Real supervised evolution payloads for the web workbench."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.evaluation import (
    list_dataset_status,
    load_dashboard_records,
    load_gym_promotion_lifecycle,
    load_workbench_state,
)

from .i18n import get_web_language, text_for
from .workbench_contract_service import get_workbench_contract


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LIST_RECORD_LIMIT = 24
DETAIL_RECORD_LIMIT = 400
BLOCKED_DELETE_STATUSES = {"active", "applied"}


class EvolutionProposalNotFoundError(Exception):
    """Raised when a supervised proposal record cannot be found."""


class EvolutionProposalDeleteBlockedError(Exception):
    """Raised when a supervised proposal is not deletable in its current state."""


class EvolutionProposalValidationError(Exception):
    """Raised when a supervised proposal references unsafe or invalid paths."""


def get_evolution_overview() -> dict[str, Any]:
    """Return overview payloads sourced from supervised evolution records."""

    lang = get_web_language()
    runs = list_runs()
    library_items = list_library_items()
    pending_items = list_pending_library_items()
    latest_run = runs[0] if runs else None
    workbench_state = _build_workbench_state()
    current_status = _build_current_status(latest_run, lang)
    recent_library = sorted(
        [
            {
                "id": item["id"],
                "title": item["title"],
                "source": item["proposalStatus"],
                "sourceRun": item["sourceRun"],
                "updatedAt": item["updatedAt"],
            }
            for item in (library_items + pending_items)
        ],
        key=lambda item: item["updatedAt"],
        reverse=True,
    )[:4]
    for item in recent_library:
        item.pop("updatedAt", None)

    return {
        "intakeMode": get_workbench_contract().get("intakeMode", "manual_review"),
        "currentStatus": current_status,
        "recentRuns": runs[:4],
        "recentLibrary": recent_library,
        "workbench": workbench_state,
    }


def list_runs() -> list[dict[str, Any]]:
    """Return supervised run summaries for the web surface."""

    records = _load_records(PROJECT_ROOT, limit=LIST_RECORD_LIMIT)
    return [_run_payload(record) for record in records]


def get_run(session_id: str, *, project_root: Path | None = None) -> dict[str, Any] | None:
    """Return one supervised run payload by session id when available."""

    root = (project_root or PROJECT_ROOT).resolve()
    target = str(session_id or "").strip()
    if not target:
        return None
    record = _find_record(target, root=root, limit=DETAIL_RECORD_LIMIT)
    return _run_payload(record) if record is not None else None


def list_library_items() -> list[dict[str, Any]]:
    """Return non-pending supervised proposal/library entries."""

    root = PROJECT_ROOT.resolve()
    lang = get_web_language()
    records = _load_records(root, limit=LIST_RECORD_LIMIT)
    items: list[dict[str, Any]] = []
    for record in records:
        if record.gym_proposal_status not in {"active", "superseded", "rolled_back"}:
            continue
        items.append(_library_item_payload(record, root=root, lang=lang))
    return items


def list_pending_library_items() -> list[dict[str, Any]]:
    """Return supervised proposal entries that still need manual follow-up."""

    root = PROJECT_ROOT.resolve()
    lang = get_web_language()
    records = _load_records(root, limit=LIST_RECORD_LIMIT)
    pending: list[dict[str, Any]] = []
    for record in records:
        status = record.gym_proposal_status
        if status in {"proposed", "applied"} or (record.decision == "PROMOTE" and status == "missing"):
            pending.append(_pending_item_payload(record, root=root, lang=lang))
    return pending


def get_proposal_detail(session_id: str, *, project_root: Path | None = None) -> dict[str, Any]:
    """Return a review-first proposal detail payload for one supervised run."""

    lang = get_web_language()
    root = (project_root or PROJECT_ROOT).resolve()
    record = _require_record(session_id, root=root)
    decision_path = _resolve_path(record.decision_path, root=root)
    lifecycle = load_gym_promotion_lifecycle(str(decision_path), project_root=root)
    supervised_payload = _load_json_object(record.decision_path, root=root)
    proposal_payload = _load_json_object(lifecycle.proposal_path, root=root)
    gym_decision_payload = _load_json_object(lifecycle.gym_decision_path, root=root)
    preview = _review_preview(record, root=root, lang=lang)
    target_label = _target_label(record, gym_decision_payload, proposal_payload)
    can_delete, delete_block_reason = _delete_state(lifecycle.status or record.gym_proposal_status, lang=lang)
    proposal = _proposal_payload(
        lifecycle=lifecycle,
        record=record,
        raw_gym_decision=gym_decision_payload,
        raw_proposal=proposal_payload,
        target_label=target_label,
    )
    review = _review_payload(
        record=record,
        proposal=proposal,
        lifecycle=lifecycle,
        preview=preview,
        can_delete=can_delete,
        delete_block_reason=delete_block_reason,
        lang=lang,
    )

    return {
        "sessionId": record.session_id,
        "sourceRun": record.session_id,
        "title": _proposal_title(record),
        "type": _library_type(record),
        "updatedAt": record.ended_at,
        "decision": record.decision,
        "proposalStatus": lifecycle.status or record.gym_proposal_status,
        "runtimeEffect": lifecycle.runtime_effect or record.gym_runtime_effect,
        "targetKey": lifecycle.target_key or record.gym_target_key or "",
        "targetLabel": target_label,
        "availableActions": list(lifecycle.available_actions or record.gym_available_actions),
        "canDelete": can_delete,
        "deleteBlockReason": delete_block_reason,
        "runSemantics": {
            "runStatus": _run_status(record),
            "runStatusLabel": _run_state_label(_run_status(record), lang=lang),
            "stage": record.bundle_name,
            "stageLabel": record.bundle_name or text_for(lang, zh="未命名运行", en="Unnamed run"),
            "diagnosis": record.reason,
            "nextAction": _next_action(record, lang=lang),
        },
        "outcomeSemantics": _outcome_semantics(
            decision=record.decision,
            proposal_status=lifecycle.status or record.gym_proposal_status,
            runtime_effect=lifecycle.runtime_effect or record.gym_runtime_effect,
            lang=lang,
        ),
        "actionStates": _proposal_action_states(
            available_actions=list(lifecycle.available_actions or record.gym_available_actions),
            proposal_status=lifecycle.status or record.gym_proposal_status,
            can_delete=can_delete,
            delete_block_reason=delete_block_reason,
            lang=lang,
        ),
        "review": review,
        "supervised": {
            "baselineScore": _score(record.baseline_success_rate),
            "candidateScore": _score(record.candidate_success_rate),
            "deltaScore": _score(record.candidate_success_rate) - _score(record.baseline_success_rate),
            "riskLevel": record.risk_level,
            "riskReasons": list(record.risk_reasons),
            "decisionReason": record.reason,
            "activeAdvisoryCount": record.advisory_active_count,
        },
        "proposal": proposal,
        "paths": {
            "supervisedDecisionPath": str(decision_path),
            "gymProposalPath": lifecycle.proposal_path or "",
            "gymDecisionPath": lifecycle.gym_decision_path or "",
            "traceIndexPath": lifecycle.trace_index_path or "",
            "lineageIndexPath": record.lineage_index_path or "",
        },
        "rawProposal": proposal_payload,
        "rawGymDecision": gym_decision_payload,
        "rawSupervisedDecision": supervised_payload,
    }


def delete_proposal(session_id: str, *, project_root: Path | None = None) -> dict[str, Any]:
    """Delete the supervised decision record and proposal file for one removable proposal."""

    lang = get_web_language()
    root = (project_root or PROJECT_ROOT).resolve()
    detail = get_proposal_detail(session_id, project_root=root)
    if not bool(detail.get("canDelete")):
        raise EvolutionProposalDeleteBlockedError(
            str(
                detail.get("deleteBlockReason")
                or text_for(
                    lang,
                    zh="当前提案状态不允许直接删除。",
                    en="This proposal cannot be deleted in its current state.",
                )
            )
        )

    deleted_paths: list[str] = []
    proposal_path = str(((detail.get("paths") or {}).get("gymProposalPath")) or "").strip()
    decision_path = str(((detail.get("paths") or {}).get("supervisedDecisionPath")) or "").strip()

    if proposal_path:
        _delete_file(proposal_path, root=root, deleted_paths=deleted_paths)
    _delete_file(decision_path, root=root, deleted_paths=deleted_paths, required=True)

    return {
        "sessionId": detail["sessionId"],
        "title": detail["title"],
        "deleted": True,
        "deletedPaths": deleted_paths,
        "summary": text_for(
            lang,
            zh=f"已删除监督记录 {detail['sessionId']} 的提案工作面条目，只保留审计证据。",
            en=f"Deleted the work-surface proposal for supervised record {detail['sessionId']} while keeping audit evidence.",
        ),
    }


def bulk_delete_proposals(session_ids: list[str], *, project_root: Path | None = None) -> dict[str, Any]:
    """Delete multiple removable proposals and report mixed results."""

    lang = get_web_language()
    root = (project_root or PROJECT_ROOT).resolve()
    normalized_ids = _normalize_session_ids(session_ids)
    results: list[dict[str, Any]] = []
    deleted_count = 0
    skipped_count = 0
    error_count = 0

    for session_id in normalized_ids:
        try:
            payload = delete_proposal(session_id, project_root=root)
        except EvolutionProposalNotFoundError as exc:
            skipped_count += 1
            results.append(
                {
                    "sessionId": session_id,
                    "status": "skipped",
                    "summary": str(exc),
                }
            )
            continue
        except EvolutionProposalDeleteBlockedError as exc:
            skipped_count += 1
            results.append(
                {
                    "sessionId": session_id,
                    "status": "skipped",
                    "summary": str(exc),
                }
            )
            continue
        except EvolutionProposalValidationError as exc:
            error_count += 1
            results.append(
                {
                    "sessionId": session_id,
                    "status": "error",
                    "summary": str(exc),
                }
            )
            continue

        deleted_count += 1
        results.append(
            {
                "sessionId": payload["sessionId"],
                "status": "deleted",
                "summary": payload["summary"],
                "deletedPaths": payload["deletedPaths"],
            }
        )

    return {
        "requestedCount": len(normalized_ids),
        "deletedCount": deleted_count,
        "skippedCount": skipped_count,
        "errorCount": error_count,
        "results": results,
        "summary": text_for(
            lang,
            zh=f"批量删除完成：删除 {deleted_count} 条，跳过 {skipped_count} 条，错误 {error_count} 条。",
            en=f"Bulk delete finished: deleted {deleted_count}, skipped {skipped_count}, errors {error_count}.",
        ),
    }


def _build_current_status(latest_run: dict[str, Any] | None, lang: str) -> dict[str, Any]:
    if latest_run is None:
        next_action = text_for(
            lang,
            zh="先运行一轮监督进化，建立第一条可回看的决策记录。",
            en="Run one supervised evolution pass to create the first auditable decision record.",
        )
        return {
            "state": "idle",
            "stage": text_for(lang, zh="暂无监督记录", en="no supervised records"),
            "lastResult": text_for(
                lang,
                zh="还没有监督进化记录。先运行一轮监督评测后，这里会显示结论、提案状态和建议动作。",
                en="No supervised evolution records yet. Run one supervised pass and this page will show the decision, proposal state, and next action.",
            ),
            "decision": "",
            "proposalStatus": "missing",
            "runtimeEffect": "not_applied",
            "riskLevel": "none",
            "latestRunId": "",
            "nextAction": next_action,
            "activeAdvisoryCount": 0,
            "runSemantics": {
                "runStatus": "idle",
                "runStatusLabel": _run_state_label("idle", lang=lang),
                "stage": "",
                "stageLabel": text_for(lang, zh="还没有运行现场", en="No run scene yet"),
                "diagnosis": "",
                "nextAction": next_action,
            },
            "outcomeSemantics": _outcome_semantics(
                decision="",
                proposal_status="missing",
                runtime_effect="not_applied",
                lang=lang,
            ),
            "actionStates": _proposal_action_states(
                available_actions=[],
                proposal_status="missing",
                can_delete=False,
                delete_block_reason=text_for(
                    lang,
                    zh="当前还没有监督记录，因此没有可删除的治理条目。",
                    en="There are no supervised records yet, so there is nothing deletable on the governance surface.",
                ),
                lang=lang,
            ),
        }
    return {
        "state": latest_run["status"],
        "stage": latest_run["bundleName"],
        "lastResult": latest_run["diagnosis"],
        "decision": latest_run["decision"],
        "proposalStatus": latest_run["proposalStatus"],
        "runtimeEffect": latest_run["runtimeEffect"],
        "riskLevel": latest_run["riskLevel"],
        "latestRunId": latest_run["id"],
        "nextAction": latest_run["nextAction"],
        "activeAdvisoryCount": latest_run["activeAdvisoryCount"],
        "runSemantics": latest_run["runSemantics"],
        "outcomeSemantics": latest_run["outcomeSemantics"],
        "actionStates": latest_run["actionStates"],
    }


def _build_workbench_state() -> dict[str, Any]:
    return get_workbench_state_payload(project_root=PROJECT_ROOT)


def get_workbench_state_payload(*, project_root: Path | None = None) -> dict[str, Any]:
    root = (project_root or PROJECT_ROOT).resolve()
    state = load_workbench_state(root)
    datasets = list_dataset_status(root)
    source = str(state.get("source") or "").strip().lower()
    if source not in {"bundle", "dataset"}:
        source = "unknown"
    runnable_datasets = sum(1 for item in datasets if item.get("available") and item.get("runnable"))
    blocked_datasets = len(datasets) - runnable_datasets
    return {
        "source": source,
        "bundleName": str(state.get("bundle_name") or "").strip(),
        "datasetName": str(state.get("dataset_name") or "").strip(),
        "datasetLimit": state.get("dataset_limit"),
        "keepWorktree": state.get("keep_worktree"),
        "availableDatasets": len(datasets),
        "runnableDatasets": runnable_datasets,
        "blockedDatasets": blocked_datasets,
    }


def _run_payload(record) -> dict[str, Any]:
    lang = get_web_language()
    can_delete, delete_block_reason = _delete_state(record.gym_proposal_status, lang=lang)
    baseline_score = _score(record.baseline_success_rate)
    candidate_score = _score(record.candidate_success_rate)
    delta_score = candidate_score - baseline_score
    run_status = _run_status(record)
    available_actions = list(record.gym_available_actions)
    return {
        "id": record.session_id,
        "score": candidate_score,
        "status": run_status,
        "summary": _run_summary(record, baseline_score, candidate_score),
        "diagnosis": record.reason,
        "decision": record.decision,
        "endedAt": record.ended_at,
        "bundleName": record.bundle_name,
        "baselineScore": baseline_score,
        "candidateScore": candidate_score,
        "deltaScore": delta_score,
        "riskLevel": record.risk_level,
        "riskReasons": list(record.risk_reasons),
        "proposalStatus": record.gym_proposal_status,
        "runtimeEffect": record.gym_runtime_effect,
        "agentConsumption": record.gym_agent_consumption,
        "availableActions": available_actions,
        "nextAction": _next_action(record, lang=lang),
        "sourceDecisionPath": record.decision_path,
        "sourceProposalPath": record.gym_proposal_path or "",
        "activeAdvisoryCount": record.advisory_active_count,
        "canDelete": can_delete,
        "deleteBlockReason": delete_block_reason,
        "runSemantics": {
            "runStatus": run_status,
            "runStatusLabel": _run_state_label(run_status, lang=lang),
            "stage": record.bundle_name,
            "stageLabel": record.bundle_name or text_for(lang, zh="未命名运行", en="Unnamed run"),
            "diagnosis": record.reason,
            "nextAction": _next_action(record, lang=lang),
        },
        "outcomeSemantics": _outcome_semantics(
            decision=record.decision,
            proposal_status=record.gym_proposal_status,
            runtime_effect=record.gym_runtime_effect,
            lang=lang,
        ),
        "actionStates": _proposal_action_states(
            available_actions=available_actions,
            proposal_status=record.gym_proposal_status,
            can_delete=can_delete,
            delete_block_reason=delete_block_reason,
            lang=lang,
        ),
    }


def _library_item_payload(record, *, root: Path, lang: str) -> dict[str, Any]:
    preview = _review_preview(record, root=root, lang=lang)
    can_delete, delete_block_reason = _delete_state(record.gym_proposal_status, lang=lang)
    available_actions = list(record.gym_available_actions)
    return {
        "id": record.session_id,
        "title": _proposal_title(record),
        "type": _library_type(record),
        "sourceRun": record.session_id,
        "ingestMode": "supervised_record",
        "proposalStatus": record.gym_proposal_status,
        "runtimeEffect": record.gym_runtime_effect,
        "decision": record.decision,
        "targetKey": record.gym_target_key or "",
        "targetLabel": preview["targetLabel"],
        "headline": preview["headline"],
        "changeSummary": preview["changeSummary"],
        "summary": record.reason,
        "availableActions": available_actions,
        "updatedAt": record.ended_at,
        "canDelete": can_delete,
        "deleteBlockReason": delete_block_reason,
        "outcomeSemantics": _outcome_semantics(
            decision=record.decision,
            proposal_status=record.gym_proposal_status,
            runtime_effect=record.gym_runtime_effect,
            lang=lang,
        ),
        "actionStates": _proposal_action_states(
            available_actions=available_actions,
            proposal_status=record.gym_proposal_status,
            can_delete=can_delete,
            delete_block_reason=delete_block_reason,
            lang=lang,
        ),
    }


def _pending_item_payload(record, *, root: Path, lang: str) -> dict[str, Any]:
    preview = _review_preview(record, root=root, lang=lang)
    can_delete, delete_block_reason = _delete_state(record.gym_proposal_status, lang=lang)
    available_actions = list(record.gym_available_actions)
    return {
        "id": record.session_id,
        "title": _proposal_title(record),
        "type": _library_type(record),
        "sourceRun": record.session_id,
        "reason": _next_action(record, lang=lang),
        "proposalStatus": record.gym_proposal_status,
        "runtimeEffect": record.gym_runtime_effect,
        "decision": record.decision,
        "targetKey": record.gym_target_key or "",
        "targetLabel": preview["targetLabel"],
        "headline": preview["headline"],
        "changeSummary": preview["changeSummary"],
        "summary": record.reason,
        "availableActions": available_actions,
        "updatedAt": record.ended_at,
        "canDelete": can_delete,
        "deleteBlockReason": delete_block_reason,
        "outcomeSemantics": _outcome_semantics(
            decision=record.decision,
            proposal_status=record.gym_proposal_status,
            runtime_effect=record.gym_runtime_effect,
            lang=lang,
        ),
        "actionStates": _proposal_action_states(
            available_actions=available_actions,
            proposal_status=record.gym_proposal_status,
            can_delete=can_delete,
            delete_block_reason=delete_block_reason,
            lang=lang,
        ),
    }


def _review_preview(record, *, root: Path, lang: str) -> dict[str, str]:
    gym_decision_payload = _load_json_object(record.gym_decision_path, root=root)
    proposal_payload = _load_json_object(record.gym_proposal_path, root=root)
    target_label = _target_label(record, gym_decision_payload, proposal_payload)
    improvement_type = _candidate_text(gym_decision_payload, "improvement_type")
    expected_effect = _candidate_text(gym_decision_payload, "expected_effect")
    type_label = _improvement_type_label(improvement_type, lang=lang)
    if target_label and improvement_type:
        headline = text_for(
            lang,
            zh=f"这次进化围绕 {target_label} 产出了一条 {type_label} 提案。",
            en=f"This evolution produced a {type_label} proposal for {target_label}.",
        )
    elif target_label:
        headline = text_for(
            lang,
            zh=f"这次进化围绕 {target_label} 产出了一条可审阅提案。",
            en=f"This evolution produced a reviewable proposal for {target_label}.",
        )
    else:
        headline = text_for(
            lang,
            zh="这次进化产出了一条可审阅提案。",
            en="This evolution produced a reviewable proposal.",
        )

    change_summary_parts: list[str] = []
    if improvement_type:
        change_summary_parts.append(type_label)
    if target_label:
        change_summary_parts.append(target_label)
    if expected_effect:
        change_summary_parts.append(_trim_text(expected_effect, limit=88))
    change_summary = " · ".join(part for part in change_summary_parts if part)
    if not change_summary:
        change_summary = _trim_text(record.reason, limit=88)

    return {
        "headline": headline,
        "changeSummary": change_summary,
        "targetLabel": target_label,
    }


def _proposal_payload(
    *,
    lifecycle,
    record,
    raw_gym_decision: dict[str, Any] | None,
    raw_proposal: dict[str, Any] | None,
    target_label: str,
) -> dict[str, Any]:
    candidate = _candidate_payload(raw_gym_decision)
    target = candidate.get("target") if isinstance(candidate.get("target"), dict) else None
    payload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else None
    return {
        "proposalId": lifecycle.proposal_id,
        "episodeId": lifecycle.episode_id,
        "candidateImprovementId": _text_or_none(candidate.get("improvement_id"))
        or _text_or_none((raw_proposal or {}).get("candidate_improvement_id")),
        "improvementType": _text_or_none(candidate.get("improvement_type")) or "",
        "expectedEffect": _text_or_none(candidate.get("expected_effect")) or "",
        "targetLabel": target_label,
        "target": target,
        "payload": payload,
        "targetKey": lifecycle.target_key or record.gym_target_key or "",
    }


def _review_payload(
    *,
    record,
    proposal: dict[str, Any],
    lifecycle,
    preview: dict[str, str],
    can_delete: bool,
    delete_block_reason: str,
    lang: str,
) -> dict[str, Any]:
    improvement_type = str(proposal.get("improvementType") or "").strip()
    expected_effect = str(proposal.get("expectedEffect") or "").strip()
    target_label = str(proposal.get("targetLabel") or "").strip()
    type_label = _improvement_type_label(improvement_type, lang=lang)
    baseline_score = _score(record.baseline_success_rate)
    candidate_score = _score(record.candidate_success_rate)

    what_changed: list[str] = []
    if improvement_type:
        what_changed.append(
            text_for(
                lang,
                zh=f"改进类型：{type_label}。",
                en=f"Improvement type: {type_label}.",
            )
        )
    if target_label:
        what_changed.append(
            text_for(
                lang,
                zh=f"作用目标：{target_label}。",
                en=f"Target: {target_label}.",
            )
        )
    if expected_effect:
        what_changed.append(
            text_for(
                lang,
                zh=f"预期效果：{expected_effect}",
                en=f"Expected effect: {expected_effect}",
            )
        )
    what_changed.append(
        text_for(
            lang,
            zh=f"监督比较结果：baseline {baseline_score}，candidate {candidate_score}，差值 {candidate_score - baseline_score}。",
            en=f"Supervised comparison: baseline {baseline_score}, candidate {candidate_score}, delta {candidate_score - baseline_score}.",
        )
    )

    why_created = [
        text_for(
            lang,
            zh=f"监督结论：{record.decision}。原因：{record.reason}",
            en=f"Supervised decision: {record.decision}. Reason: {record.reason}",
        )
    ]
    if record.risk_reasons:
        why_created.append(
            text_for(
                lang,
                zh=f"风险观察：{' / '.join(record.risk_reasons)}",
                en=f"Risk signals: {' / '.join(record.risk_reasons)}",
            )
        )

    current_state = [
        _proposal_status_explanation(lifecycle.status or record.gym_proposal_status, lang=lang),
        _runtime_effect_explanation(lifecycle.runtime_effect or record.gym_runtime_effect, lang=lang),
        text_for(
            lang,
            zh=(
                f"当前可执行动作：{', '.join(lifecycle.available_actions)}。"
                if lifecycle.available_actions
                else "当前没有后续 proposal 动作，只保留观察或审计。"
            ),
            en=(
                f"Available actions now: {', '.join(lifecycle.available_actions)}."
                if lifecycle.available_actions
                else "No further proposal actions are available right now; this is review or audit only."
            ),
        ),
    ]
    if lifecycle.note:
        current_state.append(lifecycle.note)

    evidence_notes = [
        text_for(
            lang,
            zh="删除工作面条目时，只会删掉监督 Decision Record 和 proposal 文件，不会删除 Gym decision、trace index、ledger 或 activation history。",
            en="Deleting a work-surface entry only removes the supervised decision record and proposal file. It does not remove the Gym decision, trace index, ledgers, or activation history.",
        )
    ]
    if lifecycle.trace_index_path:
        evidence_notes.append(
            text_for(
                lang,
                zh="这次提案仍然保留 trace index，可继续回看具体运行证据。",
                en="The trace index stays intact, so the concrete run evidence remains reviewable.",
            )
        )

    return {
        "headline": preview["headline"],
        "changeSummary": preview["changeSummary"],
        "whatChanged": what_changed,
        "whyCreated": why_created,
        "currentState": current_state,
        "nextAction": _next_action(record, lang=lang),
        "deleteImpact": text_for(
            lang,
            zh="删除后，这条记录会从运行列表和提案库消失，但审计证据仍然保留。",
            en="After deletion, this item disappears from the run list and proposal library while the audit evidence stays preserved.",
        ),
        "canDelete": can_delete,
        "deleteBlockReason": delete_block_reason,
        "evidenceNotes": evidence_notes,
    }


def _run_status(record) -> str:
    if record.decision in {"ROLLBACK", "REJECT"} or record.risk_level == "high":
        return "failed"
    if record.decision == "INCONCLUSIVE":
        return "waiting"
    if record.gym_proposal_status in {"proposed", "applied"}:
        return "waiting"
    return "success"


def _run_summary(record, baseline_score: int, candidate_score: int) -> str:
    return f"{record.decision} · baseline {baseline_score} / candidate {candidate_score}"


def _proposal_title(record) -> str:
    label = _extract_target_label(record)
    if label:
        return label
    if record.bundle_name and record.bundle_name != "-":
        return record.bundle_name
    return record.session_id


def _target_label(
    record,
    raw_gym_decision: dict[str, Any] | None,
    raw_proposal: dict[str, Any] | None,
) -> str:
    label = _extract_target_label(record)
    if label:
        return label
    candidate = _candidate_payload(raw_gym_decision)
    target = candidate.get("target") if isinstance(candidate.get("target"), dict) else None
    if isinstance(target, dict):
        for key in ("exercise_id", "target_label", "name", "kind", "harness_gap"):
            value = _text_or_none(target.get(key))
            if value:
                return value
        try:
            return json.dumps(target, ensure_ascii=False, sort_keys=True)
        except TypeError:
            pass
    proposal_target_key = _text_or_none((raw_proposal or {}).get("target_key"))
    return proposal_target_key or ""


def _extract_target_label(record) -> str:
    for item in list(record.advisory_entries or []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("target_label") or "").strip()
        if label:
            return label
    target_key = str(record.gym_target_key or "").strip()
    if not target_key:
        return ""
    if target_key.startswith("target:"):
        raw = target_key[len("target:") :]
        try:
            payload = json.loads(raw)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            for key in ("target_label", "exercise_id", "target_id", "name", "kind", "harness_gap"):
                label = str(payload.get(key) or "").strip()
                if label:
                    return label
    match = re.search(r'"exercise_id"\s*:\s*"([^"]+)"', target_key)
    if match:
        return match.group(1)
    return target_key[:80]


def _library_type(record) -> str:
    if record.gym_proposal_status == "active":
        return "active_advisory"
    if record.gym_proposal_status == "rolled_back":
        return "rolled_back_proposal"
    if record.gym_proposal_status == "superseded":
        return "superseded_proposal"
    return "supervised_record"


def _next_action(record, *, lang: str) -> str:
    if record.risk_level == "high":
        return text_for(
            lang,
            zh="先检查失败 gate 和监督决策，再决定是否继续推进。",
            en="Inspect the failed gate and supervised decision first, then decide whether to keep promoting this change.",
        )
    if record.gym_proposal_status == "proposed":
        return text_for(
            lang,
            zh="提案已产出，下一步可人工接纳。",
            en="The proposal has been created. The next governance step is to apply it manually.",
        )
    if record.gym_proposal_status == "applied":
        return text_for(
            lang,
            zh="提案已接纳，下一步可激活为建议基线，或直接回滚。",
            en="The proposal has been applied. It can now be activated as the advisory baseline or rolled back.",
        )
    if record.gym_proposal_status == "active":
        return text_for(
            lang,
            zh="当前已记住为建议基线，但运行时仍未自动生效。",
            en="This proposal is the remembered advisory baseline, but runtime behavior still has not been rewritten automatically.",
        )
    if record.gym_proposal_status == "rolled_back":
        return text_for(
            lang,
            zh="该提案已回滚，当前只保留审计证据。",
            en="This proposal has been rolled back and now remains only as audit evidence.",
        )
    if record.gym_proposal_status == "superseded":
        return text_for(
            lang,
            zh="该提案已被更新的建议基线替代。",
            en="This proposal has been superseded by a newer advisory baseline.",
        )
    if record.decision == "INCONCLUSIVE":
        return text_for(
            lang,
            zh="这轮监督评测没有形成可用对比证据，建议修正评测或复跑。",
            en="This supervised run did not produce usable comparison evidence. Fix the evaluation setup or rerun it.",
        )
    if record.decision == "PROMOTE":
        return text_for(
            lang,
            zh="监督结论支持晋升，但当前提案证据不完整，先检查 proposal 文件。",
            en="The supervised decision supports promotion, but the proposal evidence is incomplete. Inspect the proposal file first.",
        )
    return text_for(
        lang,
        zh="继续观察当前结论，必要时用相同配置复跑。",
        en="Keep observing the current conclusion, and rerun with the same configuration when needed.",
    )


def _score(value: float) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, round(numeric * 100)))


def _load_records(root: Path, *, limit: int) -> list[Any]:
    records, _ = load_dashboard_records(project_root=root, limit=limit)
    return records


def _find_record(session_id: str, *, root: Path, limit: int) -> Any | None:
    target = str(session_id or "").strip()
    if not target:
        return None
    for record in _load_records(root, limit=limit):
        if record.session_id == target:
            return record
    return None


def _require_record(session_id: str, *, root: Path) -> Any:
    record = _find_record(session_id, root=root, limit=DETAIL_RECORD_LIMIT)
    if record is None:
        raise EvolutionProposalNotFoundError("Supervised proposal not found.")
    return record


def _delete_state(status: str, *, lang: str) -> tuple[bool, str]:
    normalized = str(status or "").strip().lower() or "missing"
    if normalized in BLOCKED_DELETE_STATUSES:
        return (
            False,
            text_for(
                lang,
                zh=(
                    "当前提案仍处于生效链路中，不能直接删除。"
                    if normalized == "active"
                    else "当前提案已经接纳但还可能继续激活或回滚，不能直接删除。"
                ),
                en=(
                    "This proposal is still part of the active advisory chain and cannot be deleted directly."
                    if normalized == "active"
                    else "This proposal has already been applied and may still be activated or rolled back, so direct deletion is blocked."
                ),
            ),
        )
    return True, ""


def _run_state_label(status: str, *, lang: str) -> str:
    normalized = str(status or "").strip().lower() or "idle"
    mapping = {
        "idle": text_for(lang, zh="暂无运行", en="No run yet"),
        "waiting": text_for(lang, zh="等待治理动作", en="Waiting for governance action"),
        "success": text_for(lang, zh="运行已收口", en="Run closed successfully"),
        "failed": text_for(lang, zh="运行带风险收口", en="Run closed with risk"),
    }
    return mapping.get(normalized, normalized)


def _decision_label(decision: str, *, lang: str) -> str:
    normalized = str(decision or "").strip().upper()
    mapping = {
        "PROMOTE": text_for(lang, zh="建议晋升", en="Promote"),
        "HOLD": text_for(lang, zh="暂不晋升", en="Hold"),
        "ROLLBACK": text_for(lang, zh="建议回滚", en="Rollback"),
        "REJECT": text_for(lang, zh="拒绝候选", en="Reject"),
        "INCONCLUSIVE": text_for(lang, zh="评测无结论", en="Inconclusive"),
    }
    return mapping.get(normalized, normalized or text_for(lang, zh="暂无结论", en="No decision yet"))


def _proposal_status_label(status: str, *, lang: str) -> str:
    normalized = str(status or "").strip().lower() or "missing"
    mapping = {
        "proposed": text_for(lang, zh="待接纳提案", en="Proposal awaiting apply"),
        "applied": text_for(lang, zh="已接纳提案", en="Applied proposal"),
        "active": text_for(lang, zh="当前建议基线", en="Active advisory baseline"),
        "rolled_back": text_for(lang, zh="已回滚提案", en="Rolled-back proposal"),
        "superseded": text_for(lang, zh="已被替代", en="Superseded proposal"),
        "missing": text_for(lang, zh="提案缺失", en="Missing proposal"),
    }
    return mapping.get(normalized, normalized)


def _runtime_effect_label(effect: str, *, lang: str) -> str:
    normalized = str(effect or "").strip().lower() or "not_applied"
    mapping = {
        "not_applied": text_for(lang, zh="运行时尚未生效", en="Runtime not rewritten"),
        "applied_to_runtime": text_for(lang, zh="运行时已生效", en="Runtime rewritten"),
    }
    return mapping.get(normalized, normalized)


def _runtime_effect_is_applied(effect: str) -> bool:
    normalized = str(effect or "").strip().lower()
    return normalized not in {"", "not_applied", "unknown", "missing"}


def _outcome_semantics(
    *,
    decision: str,
    proposal_status: str,
    runtime_effect: str,
    lang: str,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "decisionLabel": _decision_label(decision, lang=lang),
        "proposalStatus": proposal_status,
        "proposalStatusLabel": _proposal_status_label(proposal_status, lang=lang),
        "runtimeEffect": runtime_effect,
        "runtimeEffectLabel": _runtime_effect_label(runtime_effect, lang=lang),
        "runtimeExplanation": _runtime_effect_explanation(runtime_effect, lang=lang),
        "isRuntimeApplied": _runtime_effect_is_applied(runtime_effect),
    }


def _proposal_action_states(
    *,
    available_actions: list[str],
    proposal_status: str,
    can_delete: bool,
    delete_block_reason: str,
    lang: str,
) -> dict[str, dict[str, Any]]:
    normalized_actions = {str(item or "").strip().lower() for item in available_actions}
    normalized_status = str(proposal_status or "").strip().lower() or "missing"

    def enabled_state() -> dict[str, Any]:
        return {"enabled": True, "reason": ""}

    def disabled_state(reason: str) -> dict[str, Any]:
        return {"enabled": False, "reason": reason}

    apply_state = (
        enabled_state()
        if "apply" in normalized_actions
        else disabled_state(
            text_for(
                lang,
                zh=(
                    "当前提案已经越过接纳阶段。"
                    if normalized_status in {"applied", "active", "rolled_back", "superseded"}
                    else "当前没有可接纳的提案动作。"
                ),
                en=(
                    "This proposal is already past the apply stage."
                    if normalized_status in {"applied", "active", "rolled_back", "superseded"}
                    else "No apply action is available for this proposal right now."
                ),
            )
        )
    )
    activate_state = (
        enabled_state()
        if "activate" in normalized_actions
        else disabled_state(
            text_for(
                lang,
                zh=(
                    "先接纳提案，才能把它激活为建议基线。"
                    if normalized_status == "proposed"
                    else "当前提案不处于可激活阶段。"
                ),
                en=(
                    "Apply the proposal first before activating it as the advisory baseline."
                    if normalized_status == "proposed"
                    else "This proposal is not currently in an activatable state."
                ),
            )
        )
    )
    rollback_state = (
        enabled_state()
        if "rollback" in normalized_actions
        else disabled_state(
            text_for(
                lang,
                zh=(
                    "先进入接纳或激活链路后，才会出现回滚动作。"
                    if normalized_status in {"proposed", "missing"}
                    else "当前没有可执行的回滚动作。"
                ),
                en=(
                    "Rollback becomes available only after the proposal enters the apply or activate chain."
                    if normalized_status in {"proposed", "missing"}
                    else "No rollback action is available right now."
                ),
            )
        )
    )
    delete_state = enabled_state() if can_delete else disabled_state(delete_block_reason)
    return {
        "apply": apply_state,
        "activate": activate_state,
        "rollback": rollback_state,
        "delete": delete_state,
    }


def _proposal_status_explanation(status: str, *, lang: str) -> str:
    normalized = str(status or "").strip().lower() or "missing"
    mapping = {
        "proposed": text_for(
            lang,
            zh="当前状态：已产出 proposal，还没有正式接纳。",
            en="Current state: a proposal has been created, but it has not been formally applied yet.",
        ),
        "applied": text_for(
            lang,
            zh="当前状态：proposal 已接纳进治理记录，但还没激活为建议基线。",
            en="Current state: the proposal has been applied to governance records, but it is not yet an active advisory baseline.",
        ),
        "active": text_for(
            lang,
            zh="当前状态：proposal 已成为当前建议基线。",
            en="Current state: the proposal is now the active advisory baseline.",
        ),
        "rolled_back": text_for(
            lang,
            zh="当前状态：proposal 已回滚，只保留审计证据。",
            en="Current state: the proposal has been rolled back and remains only as audit evidence.",
        ),
        "superseded": text_for(
            lang,
            zh="当前状态：proposal 已被更新的建议基线替代。",
            en="Current state: the proposal has been superseded by a newer advisory baseline.",
        ),
        "missing": text_for(
            lang,
            zh="当前状态：监督记录提到了 proposal，但 proposal 文件已经缺失。",
            en="Current state: the supervised record points to a proposal, but the proposal file is missing.",
        ),
    }
    return mapping.get(
        normalized,
        text_for(
            lang,
            zh=f"当前状态：{normalized}",
            en=f"Current state: {normalized}",
        ),
    )


def _runtime_effect_explanation(effect: str, *, lang: str) -> str:
    normalized = str(effect or "").strip().lower() or "not_applied"
    if normalized == "not_applied":
        return text_for(
            lang,
            zh="runtime_effect：当前还没有自动改写运行时，只是保留治理建议。",
            en="runtime_effect: the runtime has not been rewritten automatically; this is still governance-only advice.",
        )
    return text_for(
        lang,
        zh=f"runtime_effect：{normalized}",
        en=f"runtime_effect: {normalized}",
    )


def _candidate_payload(raw_gym_decision: dict[str, Any] | None) -> dict[str, Any]:
    candidate = (raw_gym_decision or {}).get("candidate_improvement")
    return candidate if isinstance(candidate, dict) else {}


def _candidate_text(raw_gym_decision: dict[str, Any] | None, key: str) -> str:
    candidate = _candidate_payload(raw_gym_decision)
    return str(candidate.get(key) or "").strip()


def _improvement_type_label(value: str, *, lang: str) -> str:
    normalized = str(value or "").strip().lower()
    mapping = {
        "verifier_patch": text_for(lang, zh="验证器补丁", en="verifier patch"),
        "policy_patch": text_for(lang, zh="策略补丁", en="policy patch"),
        "prompt_patch": text_for(lang, zh="提示词补丁", en="prompt patch"),
        "config_patch": text_for(lang, zh="配置补丁", en="config patch"),
    }
    return mapping.get(normalized, normalized or text_for(lang, zh="未标注类型", en="untyped change"))


def _load_json_object(path_value: str | Path | None, *, root: Path) -> dict[str, Any] | None:
    if not path_value:
        return None
    path = _resolve_path(path_value, root=root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_path(path_value: str | Path, *, root: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _delete_file(
    path_value: str | Path,
    *,
    root: Path,
    deleted_paths: list[str],
    required: bool = False,
) -> None:
    if not path_value:
        if required:
            raise EvolutionProposalValidationError("Required deletion path is empty.")
        return
    path = _resolve_path(path_value, root=root)
    if not _is_within_root(path, root=root):
        raise EvolutionProposalValidationError(f"Refusing to delete path outside project root: {path}")
    if not path.exists():
        if required:
            raise EvolutionProposalValidationError(f"Required file does not exist: {path}")
        return
    if path.is_dir():
        raise EvolutionProposalValidationError(f"Refusing to delete directory path: {path}")
    path.unlink()
    deleted_paths.append(str(path))


def _is_within_root(path: Path, *, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _normalize_session_ids(session_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in session_ids:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _trim_text(value: str, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
