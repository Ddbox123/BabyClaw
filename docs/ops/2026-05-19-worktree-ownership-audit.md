# 2026-05-19 Worktree Ownership Audit

## Summary

This audit captures the minimum safe ownership boundaries reported by the three active
development lines so Vibelution can reduce repo risk without stepping into shared
source surgery.

## Line A: Unsupervised Chat / Workbench

Primary ownership:

- `core/web/routes/sessions.py`
- `core/web/routes/files.py`
- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `web/src/routes/ChatCodingRoute.tsx`
- `web/src/components/conversation/`
- `web/src/store/chatWorkbenchStore.ts`
- `web/src/api/types.ts`
- `web/src/i18n/dictionary.ts`
- `tests/test_web_app.py`

Minimum commit boundary:

- `core/web/services/session_service.py`
- `web/src/routes/ChatCodingRoute.tsx`
- `web/src/i18n/dictionary.ts`
- `tests/test_web_app.py`

Current repo-risk signal:

- state persistence, file-context replay, and test coverage are one chain
- do not split these files across unrelated cleanup commits

## Line B: Supervised Evolution

Primary ownership:

- `core/web/routes/evolution.py`
- `core/web/services/chat_review_service.py`
- `core/evaluation/chat_dataset_capture.py`
- `core/evaluation/chat_review_queue.py`
- `web/src/routes/EvolutionRoute.tsx`
- `web/src/routes/SupervisedReviewRoute.tsx`
- `web/src/routes/SupervisedWorkspaceTabs.tsx`
- `web/src/app/router.tsx`
- `web/src/api/types.ts`
- `web/src/i18n/dictionary.ts`
- `web/src/i18n/useAppI18n.ts`

Temporary freeze extension:

- `core/web/app.py`
- `tests/test_web_app.py`

Current repo-risk signal:

- the Windows asyncio disconnect-noise patch is edited but not yet validated
- `core/web/app.py` and `tests/test_web_app.py` must remain frozen until the line
  validates or explicitly backs the patch out

## Line C: Frontend Conversation Surface

Primary ownership:

- `core/web/services/session_service.py`
- `core/ui/chat_state.py`
- `core/web/services/runtime_service.py`
- `core/orchestration/response_surface.py`
- `core/mental_model_flags.py`
- `agent.py`
- `web/src/components/conversation/*`
- `web/src/api/types.ts`
- `web/src/i18n/dictionary.ts`
- `tests/test_web_app.py`
- `AGENTS.md`

Minimum commit boundary:

- `agent.py`
- `core/ui/chat_state.py`
- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `core/mental_model_flags.py`
- `core/orchestration/response_surface.py`
- `web/src/api/types.ts`
- `web/src/components/conversation/ConversationView.tsx`
- `web/src/components/conversation/ConversationView.module.css`
- `web/src/i18n/dictionary.ts`
- `tests/test_web_app.py`

Special commit rule:

- `AGENTS.md` should be committed separately as docs/ops policy, not mixed into the
  functional conversation-surface chain

## Shared Hotspots

Vibelution should treat these as shared hotspots across multiple active lines:

- `tests/test_web_app.py`
- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `web/src/api/types.ts`
- `web/src/i18n/dictionary.ts`
- `core/web/routes/evolution.py`
- `core/web/app.py`

## Safe Governance Work

Vibelution can safely act on:

- root-level temporary review artifacts
- rebuildable frontend outputs in `web/dist/`
- root-level dev logs
- frontend Vite logs
- governance documentation
- ignore policy

## Governance Rule for This Round

If a path appears in a minimum commit boundary or shared hotspot list, Vibelution must
prefer documentation, labeling, and ignore-policy work over source cleanup.
