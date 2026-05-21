"""Evolution workbench routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from core.web.services.chat_review_service import (
    ChatReviewCandidateNotFoundError,
    ChatReviewCandidateStateError,
    ChatReviewDecisionValidationError,
    approve_chat_review_candidate,
    get_chat_review_queue,
    reject_chat_review_candidate,
    submit_chat_review_decision,
)
from core.web.services.evolution_service import (
    EvolutionProposalDeleteBlockedError,
    EvolutionProposalNotFoundError,
    EvolutionProposalValidationError,
    get_evolution_overview,
    get_proposal_detail,
    list_library_items,
    list_pending_library_items,
    list_runs,
    delete_proposal,
    bulk_delete_proposals,
)
from core.web.services.self_evolution_service import (
    SelfEvolutionHistoryDeleteError,
    delete_self_evolution_history_groups,
    get_self_evolution_overview,
    list_self_evolution_audit_events,
    list_self_evolution_transactions,
)
from core.web.services.self_evolution_control_service import (
    SelfEvolutionRunBusyError,
    SelfEvolutionRunNotFoundError,
    SelfEvolutionRunValidationError,
    get_active_self_evolution_run,
    get_latest_self_evolution_run,
    get_self_evolution_run_snapshot,
    handoff_self_evolution_run_to_session,
    request_pause_self_evolution_run,
    request_stop_self_evolution_run,
    rollback_self_evolution_run,
    resume_self_evolution_run,
    start_self_evolution_run,
    stream_self_evolution_run_events,
)
from core.web.services.supervised_control_service import (
    SupervisedRunDeleteError,
    SupervisedRunActionError,
    SupervisedRunBusyError,
    SupervisedRunNotFoundError,
    SupervisedRunStateError,
    SupervisedRunValidationError,
    delete_supervised_run_snapshot,
    execute_supervised_action,
    get_active_supervised_run,
    get_supervised_workbench,
    request_pause_supervised_run,
    request_resume_supervised_run,
    request_stop_supervised_run,
    start_supervised_run,
    stream_active_supervised_run_events,
)


router = APIRouter(tags=["evolution"])


class SupervisedRunStartPayload(BaseModel):
    sourceKind: str = ""
    datasetName: str = ""
    datasetLimit: int | None = None
    bundleName: str = ""
    keepWorktree: bool = False


class SupervisedRunActionPayload(BaseModel):
    action: str = ""


class ProposalBulkDeletePayload(BaseModel):
    sessionIds: list[str] = Field(default_factory=list)


class SelfEvolutionRunStartPayload(BaseModel):
    goal: str = ""


class SelfEvolutionHistoryDeletePayload(BaseModel):
    txnIds: list[str] = Field(default_factory=list)


class ChatReviewActionPayload(BaseModel):
    decision: str = ""
    reasonCode: str = ""
    errorType: str = ""
    correctPrinciple: str = ""
    idealBehavior: str = ""
    reviewerNote: str = ""


@router.get("/evolution/overview")
def evolution_overview() -> dict:
    return get_evolution_overview()


@router.get("/evolution/runs")
def evolution_runs() -> list[dict]:
    return list_runs()


@router.get("/evolution/library")
def evolution_library() -> dict:
    return {
        "items": list_library_items(),
        "pending": list_pending_library_items(),
    }


@router.get("/evolution/proposals/{session_id}")
def evolution_proposal_detail(session_id: str) -> dict:
    try:
        return get_proposal_detail(session_id)
    except EvolutionProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/evolution/proposals/{session_id}")
def evolution_delete_proposal(session_id: str) -> dict:
    try:
        return delete_proposal(session_id)
    except EvolutionProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvolutionProposalDeleteBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EvolutionProposalValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/evolution/proposals/delete")
def evolution_bulk_delete_proposals(payload: ProposalBulkDeletePayload) -> dict:
    return bulk_delete_proposals(payload.sessionIds)


@router.get("/evolution/workbench")
def evolution_workbench() -> dict:
    return get_supervised_workbench()


@router.get("/evolution/chat-review")
def evolution_chat_review() -> dict:
    return get_chat_review_queue()


@router.post("/evolution/chat-review/{candidate_id}/approve")
def evolution_chat_review_approve(candidate_id: str, payload: ChatReviewActionPayload) -> dict:
    try:
        return approve_chat_review_candidate(candidate_id, reviewer_note=payload.reviewerNote)
    except ChatReviewCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatReviewCandidateStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/evolution/chat-review/{candidate_id}/reject")
def evolution_chat_review_reject(candidate_id: str, payload: ChatReviewActionPayload) -> dict:
    try:
        return reject_chat_review_candidate(candidate_id, reviewer_note=payload.reviewerNote)
    except ChatReviewCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatReviewCandidateStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/evolution/chat-review/{candidate_id}/decision")
def evolution_chat_review_decision(candidate_id: str, payload: ChatReviewActionPayload) -> dict:
    try:
        return submit_chat_review_decision(
            candidate_id,
            decision=payload.decision,
            reviewer_note=payload.reviewerNote,
            reason_code=payload.reasonCode,
            error_type=payload.errorType,
            correct_principle=payload.correctPrinciple,
            ideal_behavior=payload.idealBehavior,
        )
    except ChatReviewCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatReviewCandidateStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatReviewDecisionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/evolution/active-run")
def evolution_active_run() -> dict | None:
    return get_active_supervised_run()


@router.get("/evolution/active-run/events")
def evolution_active_run_events() -> StreamingResponse:
    snapshot = get_active_supervised_run()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No active supervised run")
    return StreamingResponse(
        stream_active_supervised_run_events(initial_snapshot=snapshot),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/evolution/runs", status_code=status.HTTP_202_ACCEPTED)
def evolution_start_run(payload: SupervisedRunStartPayload) -> dict:
    try:
        return start_supervised_run(payload.model_dump())
    except SupervisedRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/evolution/runs/{run_id}/pause")
def evolution_pause_run(run_id: str) -> dict:
    try:
        return request_pause_supervised_run(run_id)
    except SupervisedRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/evolution/runs/{run_id}/resume")
def evolution_resume_run(run_id: str) -> dict:
    try:
        return request_resume_supervised_run(run_id)
    except SupervisedRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/evolution/runs/{run_id}/terminate")
def evolution_terminate_run(run_id: str) -> dict:
    try:
        return request_stop_supervised_run(run_id)
    except SupervisedRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/evolution/runs/{run_id}")
def evolution_delete_run(run_id: str) -> dict:
    try:
        return delete_supervised_run_snapshot(run_id)
    except SupervisedRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SupervisedRunDeleteError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/evolution/runs/{session_id}/actions")
def evolution_run_action(session_id: str, payload: SupervisedRunActionPayload) -> dict:
    try:
        return execute_supervised_action(session_id, payload.action)
    except SupervisedRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/evolution/self/overview")
def self_evolution_overview() -> dict:
    return get_self_evolution_overview()


@router.get("/evolution/self/transactions")
def self_evolution_transactions() -> list[dict]:
    return list_self_evolution_transactions()


@router.post("/evolution/self/history/delete")
def self_evolution_delete_history(payload: SelfEvolutionHistoryDeletePayload) -> dict:
    try:
        return delete_self_evolution_history_groups(payload.txnIds)
    except SelfEvolutionHistoryDeleteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/evolution/self/active-run")
def self_evolution_active_run() -> dict | None:
    return get_active_self_evolution_run()


@router.get("/evolution/self/latest-run")
def self_evolution_latest_run() -> dict | None:
    return get_latest_self_evolution_run()


@router.get("/evolution/self/runs/{run_id}/events")
def self_evolution_run_events(run_id: str) -> StreamingResponse:
    snapshot = get_self_evolution_run_snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Self-evolution run not found")
    return StreamingResponse(
        stream_self_evolution_run_events(run_id, initial_snapshot=snapshot),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/evolution/self/runs", status_code=status.HTTP_202_ACCEPTED)
def self_evolution_start_run(payload: SelfEvolutionRunStartPayload) -> dict:
    try:
        return start_self_evolution_run(payload.model_dump())
    except SelfEvolutionRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SelfEvolutionRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/evolution/self/runs/{run_id}/terminate")
def self_evolution_terminate_run(run_id: str) -> dict:
    try:
        return request_stop_self_evolution_run(run_id)
    except SelfEvolutionRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SelfEvolutionRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SelfEvolutionRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/evolution/self/runs/{run_id}/pause")
def self_evolution_pause_run(run_id: str) -> dict:
    try:
        return request_pause_self_evolution_run(run_id)
    except SelfEvolutionRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SelfEvolutionRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SelfEvolutionRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/evolution/self/runs/{run_id}/resume")
def self_evolution_resume_run(run_id: str) -> dict:
    try:
        return resume_self_evolution_run(run_id)
    except SelfEvolutionRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SelfEvolutionRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SelfEvolutionRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/evolution/self/runs/{run_id}/rollback")
def self_evolution_rollback_run(run_id: str) -> dict:
    try:
        return rollback_self_evolution_run(run_id)
    except SelfEvolutionRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SelfEvolutionRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SelfEvolutionRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/evolution/self/runs/{run_id}/handoff")
def self_evolution_handoff_run(run_id: str) -> dict:
    try:
        return handoff_self_evolution_run_to_session(run_id)
    except SelfEvolutionRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SelfEvolutionRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SelfEvolutionRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/evolution/self/audit")
def self_evolution_audit() -> list[dict]:
    return list_self_evolution_audit_events()
