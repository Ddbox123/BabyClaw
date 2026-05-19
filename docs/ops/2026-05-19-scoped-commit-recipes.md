# 2026-05-19 Scoped Commit Recipes

## Purpose

This note turns the three active line reports into commit-boundary guidance so later
git cleanup does not accidentally blend unrelated work.

## Commit Rule Zero

If a file is listed in a minimum commit boundary, do not move it into a governance
cleanup commit. Governance commits should stay on docs, ignore policy, and explicitly
approved non-source cleanup only.

## Recipe A: Unsupervised Chat / Workbench

Recommended minimum commit boundary:

- `core/web/services/session_service.py`
- `web/src/routes/ChatCodingRoute.tsx`
- `web/src/i18n/dictionary.ts`
- `tests/test_web_app.py`

Reason:

- state persistence
- file-context replay
- user-facing copy
- regression coverage

These four files are one functional chain and should land together.

## Recipe B: Frontend Conversation Surface

Recommended minimum commit boundary:

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

Reason:

- response surface, state persistence, frontend rendering, and tests were changed as
  one end-to-end chain

## Recipe C: AGENTS Policy

Recommended standalone commit:

- `AGENTS.md`

Reason:

- it is operational policy, not product behavior
- it should not be mixed into a functional frontend commit

## Recipe D: Supervised Evolution Patch Freeze

Temporarily frozen files:

- `core/web/app.py`
- `tests/test_web_app.py`

Rule:

- do not stage or tidy these on behalf of the supervised line until that line either
  validates the pending Windows asyncio disconnect-noise patch or explicitly abandons
  it

## Shared Hotspot Warning

These files sit across more than one active line:

- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `web/src/api/types.ts`
- `web/src/i18n/dictionary.ts`
- `tests/test_web_app.py`

For these files:

- do not auto-stage from generic `git add .`
- do not combine them into a Vibelution governance commit
- require per-line review before any staging action

## Vibelution Commit Scope

The current Vibelution governance round should stay limited to:

- `.gitignore`
- `docs/ops/2026-05-19-vibelution-governance-map.md`
- `docs/ops/2026-05-19-worktree-ownership-audit.md`
- `docs/ops/2026-05-19-runtime-output-policy.md`
- `docs/ops/2026-05-19-scoped-commit-recipes.md`

This keeps repo-governance history separate from active product implementation.
