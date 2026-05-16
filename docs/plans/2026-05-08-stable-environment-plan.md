# Stable Environment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a stable, reproducible, and safe runtime environment for the agent so its self-evolution work happens on predictable ground.

**Architecture:** Treat environment stability as a layered problem: configuration stability first, runtime and dependency stability second, workspace and path stability third, then deterministic validation entrypoints. The plan avoids adding new product behavior and instead makes the existing system easier to boot, test, and recover.

**Tech Stack:** Python 3.14, TOML config, pytest, local workspace layout, current `agent.py` bootstrap path.

---

### Task 1: Remove secrets from tracked config and define environment layering

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\config.toml`
- Modify: `C:\Users\17533\Desktop\Vibelution\README.md`
- Create: `C:\Users\17533\Desktop\Vibelution\config.example.toml`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_config_redaction.py`

**Step 1: Write the failing test**

Add tests that verify:
- tracked config files do not contain real API keys
- `config.example.toml` uses placeholders only
- bootstrap still works when keys come from environment variables

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_config_redaction.py -q --tb=short --no-header`

Expected: FAIL until config files are split correctly.

**Step 3: Write minimal implementation**

Do the following:
- replace the tracked key in `config.toml` with an env-driven placeholder
- add `config.example.toml` as the documented source of truth
- document required env vars per provider in `README.md`

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_config_redaction.py -q --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add config.toml config.example.toml README.md tests/test_config_redaction.py
git commit -m "chore: externalize secrets from tracked config"
```

### Task 2: Define stable runtime profiles

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\config.toml`
- Create: `C:\Users\17533\Desktop\Vibelution\config\profiles.py`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_runtime_profiles.py`

**Step 1: Write the failing test**

Add tests for explicit runtime profiles:
- `safe_local`
- `safe_remote`
- `debug`
- `ci`

Each profile should assert concrete values for timeouts, iteration limits, compression, and provider expectations.

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_runtime_profiles.py -q --tb=short --no-header`

Expected: FAIL before profile resolution exists.

**Step 3: Write minimal implementation**

Implement a thin profile layer that resolves sane environment-specific defaults without forcing every operator to hand-edit `config.toml`.

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_runtime_profiles.py -q --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add config/profiles.py config.toml tests/test_runtime_profiles.py
git commit -m "feat: add stable runtime profiles"
```

### Task 3: Stabilize dependency and interpreter entrypoints

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\requirements.txt`
- Create: `C:\Users\17533\Desktop\Vibelution\scripts\doctor.ps1`
- Create: `C:\Users\17533\Desktop\Vibelution\tests\test_environment_doctor.py`

**Step 1: Write the failing test**

Add tests that verify the environment doctor reports:
- expected Python executable
- presence of `.venv`
- importability of critical packages
- availability of pytest via `python -m pytest`

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_environment_doctor.py -q --tb=short --no-header`

Expected: FAIL until the doctor script exists.

**Step 3: Write minimal implementation**

Create a single operator command, `scripts/doctor.ps1`, that checks the interpreter, venv, key imports, and common environment drift.

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_environment_doctor.py -q --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add requirements.txt scripts/doctor.ps1 tests/test_environment_doctor.py
git commit -m "feat: add environment doctor entrypoint"
```

### Task 4: Make workspace and path behavior deterministic

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\config\models.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\core\infrastructure\workspace_manager.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\tools\shell_tools.py`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_workspace_manager.py`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_shell_tools.py`

**Step 1: Write the failing test**

Add tests for:
- stable workspace root resolution
- consistent behavior for nonexistent paths
- explicit allowed-root calculation
- no accidental fallback to surprising current working directories

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_workspace_manager.py tests\test_shell_tools.py -q --tb=short --no-header`

Expected: FAIL where path rules are ambiguous.

**Step 3: Write minimal implementation**

Normalize path behavior so every file and shell tool resolves against a well-defined root set and returns deterministic errors.

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_workspace_manager.py tests\test_shell_tools.py -q --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add config/models.py core/infrastructure/workspace_manager.py tools/shell_tools.py tests/test_workspace_manager.py tests/test_shell_tools.py
git commit -m "fix: make workspace and path behavior deterministic"
```

### Task 5: Create a stable boot pipeline

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\agent.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\config\settings.py`
- Create: `C:\Users\17533\Desktop\Vibelution\tests\test_boot_pipeline.py`

**Step 1: Write the failing test**

Add boot tests for:
- local provider boot
- remote provider boot with env key
- missing-key failure with clear message
- config/profile load order
- boot without UI side effects in test mode

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_boot_pipeline.py -q --tb=short --no-header`

Expected: FAIL until boot invariants are explicit.

**Step 3: Write minimal implementation**

Make bootstrap order deterministic and keep test mode from mutating stdout/stderr in ways that destabilize pytest and automation.

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_boot_pipeline.py -q --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add agent.py config/settings.py tests/test_boot_pipeline.py
git commit -m "test: stabilize boot pipeline"
```

### Task 6: Define the stable validation surface

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\tests\test_runner.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\pytest.ini`
- Create: `C:\Users\17533\Desktop\Vibelution\tests\test_environment_smoke.py`

**Step 1: Write the failing test**

Add tests for a dedicated `environment_smoke` surface that verifies:
- config loads
- boot prerequisites exist
- workspace can initialize
- shell safety is active
- acceptance runner can execute through `python -m pytest`

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_environment_smoke.py tests\test_runner.py -q --tb=short --no-header`

Expected: FAIL until the smoke profile is defined.

**Step 3: Write minimal implementation**

Expose a single stable smoke command that operators and the agent can run before deeper work.

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_environment_smoke.py tests\test_runner.py -q --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_runner.py pytest.ini tests/test_environment_smoke.py
git commit -m "feat: add stable environment smoke validation"
```

### Task 7: Document the operator workflow

**Files:**
- Create: `C:\Users\17533\Desktop\Vibelution\docs\stable-environment.md`
- Modify: `C:\Users\17533\Desktop\Vibelution\README.md`

**Step 1: Write the checklist**

Document:
- how to set env vars
- how to choose a runtime profile
- how to run the doctor
- how to run environment smoke
- what to check before letting the agent self-modify

**Step 2: Validate the checklist**

Run:
- `powershell -ExecutionPolicy Bypass -File .\scripts\doctor.ps1`
- `.\.venv\Scripts\python.exe -m pytest tests\test_environment_smoke.py -q --tb=short --no-header`

Expected: PASS and the docs match actual commands.

**Step 3: Commit**

```bash
git add docs/stable-environment.md README.md
git commit -m "docs: define stable environment workflow"
```

### Recommended execution order

1. Task 1
2. Task 5
3. Task 3
4. Task 4
5. Task 6
6. Task 2
7. Task 7

### Why this order

- Task 1 removes the highest-risk instability immediately: tracked secrets and ambiguous config ownership.
- Task 5 makes startup deterministic, which unblocks every other environment check.
- Task 3 gives you a single command to detect drift.
- Task 4 makes path behavior stop depending on luck.
- Task 6 creates a cheap validation gate.
- Task 2 is useful, but only after the basics are stable.
- Task 7 comes last so docs describe the real workflow.

### Immediate priority notes

- `config.toml` currently contains a real-looking API key and should be treated as compromised until rotated.
- The project currently depends on `.venv\Scripts\python.exe -m pytest` more reliably than bare `pytest`; the plan should preserve that as the canonical test entrypoint.
- Boot behavior in `agent.py` still deserves explicit isolation from UI and console side effects during automated runs.

### Success criteria

- No real secrets remain in tracked config
- The project has one deterministic way to check environment health
- Startup behavior is testable and repeatable across local and remote providers
- Path and workspace rules are explicit
- A small smoke surface exists for operators and for the agent itself
