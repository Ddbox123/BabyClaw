# 2026-05-19 Vibelution Governance Map

## Purpose

This note records the current Vibelution-level repo governance boundary while three
parallel development lines are still active. It is intentionally conservative:
protect shared source seams first, reduce root-level noise second, and postpone
structural source cleanup until the active lines have landed.

## Freeze Zone

Do not rename, move, split, reformat, or otherwise "tidy" these paths in the current
governance round:

- `core/web/app.py`
- `tests/test_web_app.py`
- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `core/web/routes/evolution.py`
- `web/src/api/types.ts`
- `web/src/i18n/dictionary.ts`
- `web/src/components/conversation/`
- `core/ui/chat_state.py`
- `core/orchestration/response_surface.py`
- `core/mental_model_flags.py`
- `agent.py`
- `core/chat/`
- `core/web/`
- `web/src/`

These files are currently shared seams across the supervised evolution, unsupervised
chat/workbench, and frontend conversation surfaces. Even harmless-looking cleanup such
as import sorting or test reshaping can create cross-line merge risk.

## Active Runtime Scene Guard

The following runtime locations are not part of this cleanup round and must be treated
as live scene evidence:

- `.runtime/`
- `logs/runtime_scenes/20260519T120249Z__bd2eb15adc4e`

At the end of the Vibelution cleanup pass, no known legacy frontend dev ports
remained active on `4173`, `5173`, `5174`, or `8766`. If new local servers are
started later, Vibelution should re-check port occupancy before treating log files as
stale.

## Low-Risk Governance Zone

Vibelution may safely work in these areas during the current round:

- root-level review screenshots and temporary inspection files
- local build products such as `web/dist/`
- root-level dev logs such as `web-dev.log` and `web-dev.err.log`
- frontend local log files such as `web/.vite-*.log` and `web/vite-*.log`
- governance documentation under `docs/ops/`
- ignore policy in `.gitignore`

## Approved Root Artifact Migration Set

The following root-level files were explicitly confirmed as no longer required by the
unsupervised line and may be moved out of the repo root:

- `edge-supervised-1100.png`
- `edge-supervised-final-1100.png`
- `edge-supervised-fixed-1100.png`
- `edge-supervised-fixed2-1100.png`
- `edge-supervised-fixed2-900.png`
- `edge-supervised.png`
- `supervised-live-audit.png`
- `tmp-config-apply-sidebar.png`
- `tmp-config-collapsed-desktop.png`
- `tmp-config-collapsed-mobile.png`
- `tmp-config-desktop-refined.png`
- `tmp-config-desktop-review.png`
- `tmp-config-index-toggle.png`
- `tmp-config-late.png`
- `tmp-config-mobile.png`
- `tmp-config-polished.png`
- `tmp-config-section-toolbar.png`
- `tmp-config-sidebar-scroll.png`
- `tmp-config-single-view.png`
- `tmp-config.png`
- `tmp-logs-dom.html`
- `tmp-logs-resize-2.png`
- `tmp-logs-resize.png`
- `tmp-self-nav-after-click.png`
- `tmp-self-nav-lock.png`

## Immediate Vibelution Actions

The current governance round is allowed to do only the following:

1. Publish Vibelution governance notes and ownership boundaries.
2. Move the approved review artifacts out of the repo root.
3. Clean rebuildable local outputs and dev logs.
4. Harden ignore rules for runtime/local-output noise.

## Deferred Until Source Lines Land

Do not attempt these until the active development lines have been validated and
scoped into commits:

- `core/web/` directory reshaping
- `web/src/` route/module reshaping
- shared test decomposition around `tests/test_web_app.py`
- type/i18n/session contract consolidation
- any cross-line commit squashing
