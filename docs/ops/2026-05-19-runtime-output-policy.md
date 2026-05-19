# 2026-05-19 Runtime Output Policy

## Purpose

This policy defines how Vibelution should treat local runtime state, diagnostic scene
artifacts, frontend build output, and local dev logs while the repo is under parallel
development.

## Classification

### Local Runtime State

Paths:

- `.runtime/`

Policy:

- treat as machine-local runtime state
- do not commit
- do not use as a source-organization target
- do not bulk-delete during an active development session unless the owner of the
  running scene confirms it is safe

## Diagnostic Scene Evidence

Paths:

- `logs/runtime_scenes/`

Policy:

- treat as diagnostic evidence, not as normal cleanup trash
- preserve the current live scene
- preserve a small recent window of failed or anomalous scenes for postmortem use
- only delete stopped scenes after they are outside the retention window
- never clear active scenes just to reduce worktree noise

Current protected live scene on 2026-05-19:

- `logs/runtime_scenes/20260519T120249Z__bd2eb15adc4e`

## Rebuildable Frontend Output

Paths:

- `web/dist/`

Policy:

- treat as rebuildable local output
- safe to remove during repo cleanup
- keep ignored in Git

## Local Dev Logs

Paths:

- `web-dev.log`
- `web-dev.err.log`
- `web/.vite-*.log`
- `web/vite-*.log`
- `%TEMP%/vibelution-web-dev-*.log`

Policy:

- treat as ephemeral local logs
- safe to delete when no live process is holding them open
- if a file is locked by a live dev server, do not force-delete by killing the process
  unless the owner has explicitly agreed to stop that process
- keep repo-local log names ignored in Git

## Active Port Awareness

Legacy local ports that required governance attention during this round included
`4173`, `5173`, `5174`, and `8766`. Port occupancy is a governance concern, not just
a runtime concern. Vibelution should avoid deleting files or directories that are
currently being written by live processes.

## Cleanup Order

When reducing local-output noise, use this order:

1. remove root-level review artifacts that were explicitly approved for migration
2. remove rebuildable output such as `web/dist/`
3. remove stale local logs that are not locked
4. leave locked logs alone until the owning process stops
5. do not touch live runtime scenes

## Residue Note

During the first cleanup pass, a legacy Vite chain kept several log files locked.
After Vibelution explicitly stopped the leftover `node.exe` and `cmd.exe` launcher
processes, those locked log files were removed and the watched ports were confirmed
idle.
