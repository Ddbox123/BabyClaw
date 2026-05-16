# Terminal-Bench Integration Implementation Plan

> **Goal:** Make Vibelution survive and improve inside a real terminal task environment by integrating a first external benchmark ecology without bloating the agent core.

**Architecture:** Reuse the existing `scripts/evolution_harness.py` as the common sandbox runner, then add a thin evaluation layer around it for `Terminal-Bench`: one adapter, one comparative baseline-versus-candidate runner, one structured result store, and one simple promotion policy. The first phase avoids broad generalization and proves the selection loop end to end.

**Tech Stack:** Python, pytest, existing `agent.py` single-turn and auto entrypoints, `scripts/evolution_harness.py`, `core/infrastructure/evolution_governor.py`, local workspace storage.

---

## Phase Scope

This phase should deliver:

1. a `TerminalBenchAdapter`
2. a reusable benchmark harness entrypoint
3. comparative `baseline vs candidate` case execution
4. structured evaluation result persistence
5. a minimal promotion decision rule
6. focused tests for the new evaluation flow

This phase should **not** yet deliver:

- full multi-benchmark abstraction beyond what Terminal-Bench needs
- live benchmark ingestion
- SWE-bench container orchestration
- benchmark-aware logic inside `agent.py`

---

## Task 1: Create the minimal evaluation package

**Files:**
- Create: `C:\Users\17533\Desktop\Vibelution\core\evaluation\__init__.py`
- Create: `C:\Users\17533\Desktop\Vibelution\core\evaluation\case_models.py`
- Create: `C:\Users\17533\Desktop\Vibelution\core\evaluation\benchmark_adapter.py`
- Create: `C:\Users\17533\Desktop\Vibelution\core\evaluation\benchmark_registry.py`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_benchmark_registry.py`

**Step 1: Write the failing test**

Add tests for:

- adapter registration by benchmark name
- resolving a registered adapter
- duplicate registration rejection
- a small typed case/result model round-trip

Expected objects:

- `PreparedCase`
- `CaseRunRequest`
- `CaseRunResult`
- `CaseScore`

**Step 2: Run test to verify it fails**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_benchmark_registry.py -q --tb=short --no-header
```

Expected: FAIL before the evaluation package exists.

**Step 3: Write minimal implementation**

Implement:

- a lightweight abstract `BenchmarkAdapter`
- a simple in-process registry
- small dataclasses or typed models for cases, runs, and scores

Keep the surface narrow. Do not design for every future benchmark yet.

**Step 4: Run test to verify it passes**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_benchmark_registry.py -q --tb=short --no-header
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/evaluation/__init__.py core/evaluation/case_models.py core/evaluation/benchmark_adapter.py core/evaluation/benchmark_registry.py tests/test_benchmark_registry.py
git commit -m "feat(evaluation): add minimal benchmark adapter registry"
```

---

## Task 2: Add a Terminal-Bench adapter

**Files:**
- Create: `C:\Users\17533\Desktop\Vibelution\core\evaluation\adapters\__init__.py`
- Create: `C:\Users\17533\Desktop\Vibelution\core\evaluation\adapters\terminal_bench.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\core\evaluation\benchmark_registry.py`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_terminal_bench_adapter.py`

**Step 1: Write the failing test**

Add tests for:

- transforming a terminal benchmark case into a `PreparedCase`
- generating the agent prompt for a terminal task
- producing a runtime config payload for the harness
- rejecting malformed or incomplete case inputs cleanly

The adapter test should not depend on a live Terminal-Bench install yet. Use a small fixture payload that represents a terminal task.

**Step 2: Run test to verify it fails**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_terminal_bench_adapter.py -q --tb=short --no-header
```

Expected: FAIL until the adapter exists.

**Step 3: Write minimal implementation**

Implement a `TerminalBenchAdapter` that:

- accepts a simple case schema
- materializes a prompt for Vibelution
- defines a terminal-oriented runtime profile
- exposes enough metadata for downstream scoring

Do not yet embed benchmark-specific score logic beyond what the tests require.

**Step 4: Run test to verify it passes**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_terminal_bench_adapter.py -q --tb=short --no-header
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/evaluation/adapters/__init__.py core/evaluation/adapters/terminal_bench.py core/evaluation/benchmark_registry.py tests/test_terminal_bench_adapter.py
git commit -m "feat(evaluation): add terminal bench adapter"
```

---

## Task 3: Extract a reusable harness runner surface

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\scripts\evolution_harness.py`
- Create: `C:\Users\17533\Desktop\Vibelution\scripts\benchmark_harness.py`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_benchmark_harness.py`

**Step 1: Write the failing test**

Add tests for:

- running a prepared benchmark case through the harness without using built-in probe scenarios
- passing a structured prompt and config overlay into the harness
- emitting a structured benchmark run report
- distinguishing `candidate` and `baseline` executions in the report metadata

Mock or stub the heavy agent execution path where needed. The test should lock down the protocol surface, not require a full live benchmark run.

**Step 2: Run test to verify it fails**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_benchmark_harness.py -q --tb=short --no-header
```

Expected: FAIL before the benchmark harness surface exists.

**Step 3: Write minimal implementation**

Do the following:

- keep `scripts/evolution_harness.py` as the runtime engine
- add a thin wrapper in `scripts/benchmark_harness.py`
- define a structured input payload for benchmark runs
- add metadata fields such as:
  - `benchmark_name`
  - `case_id`
  - `run_role` (`baseline` or `candidate`)
  - `candidate_id`

Avoid forking a second sandbox implementation.

**Step 4: Run test to verify it passes**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_benchmark_harness.py -q --tb=short --no-header
```

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/evolution_harness.py scripts/benchmark_harness.py tests/test_benchmark_harness.py
git commit -m "feat(harness): add benchmark harness entrypoint"
```

---

## Task 4: Persist benchmark results in workspace

**Files:**
- Create: `C:\Users\17533\Desktop\Vibelution\core\evaluation\result_store.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\core\infrastructure\workspace_manager.py`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_evaluation_result_store.py`

**Step 1: Write the failing test**

Add tests for:

- creating the evaluation directory structure under `workspace/`
- writing one case result JSON file
- appending a run summary to a leaderboard or run log
- reading back recent results for a benchmark bundle

Suggested directories:

- `workspace/evaluation/runs/`
- `workspace/evaluation/case_results/`
- `workspace/evaluation/leaderboards/`

**Step 2: Run test to verify it fails**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_evaluation_result_store.py -q --tb=short --no-header
```

Expected: FAIL before the result store exists.

**Step 3: Write minimal implementation**

Add a small result store that can:

- persist case-level results
- persist run-level summaries
- query recent results by benchmark name and bundle

Keep this filesystem-first. Do not move benchmark persistence into SQLite yet unless the implementation becomes awkward.

**Step 4: Run test to verify it passes**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_evaluation_result_store.py -q --tb=short --no-header
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/evaluation/result_store.py core/infrastructure/workspace_manager.py tests/test_evaluation_result_store.py
git commit -m "feat(evaluation): persist benchmark results in workspace"
```

---

## Task 5: Add baseline-versus-candidate comparison

**Files:**
- Create: `C:\Users\17533\Desktop\Vibelution\core\evaluation\selection_policy.py`
- Create: `C:\Users\17533\Desktop\Vibelution\core\evaluation\runner.py`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_selection_policy.py`

**Step 1: Write the failing test**

Add tests for:

- a candidate that beats baseline on primary score and has no safety regression gets promoted
- a candidate with a small score gain but larger complexity cost gets rejected
- a candidate that regresses safety gets rejected
- a tie defaults to conservative retention of baseline

Suggested inputs:

- `primary_score`
- `success_rate`
- `validation_failed`
- `complexity_delta`
- `elapsed_seconds`

**Step 2: Run test to verify it fails**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_selection_policy.py -q --tb=short --no-header
```

Expected: FAIL before the selection policy exists.

**Step 3: Write minimal implementation**

Implement:

- a simple baseline-vs-candidate comparison routine
- a promotion decision structure with:
  - `decision`
  - `reason`
  - `score_delta`
  - `safety_regression`
  - `complexity_penalty`

Keep the scoring rule transparent and deterministic.

**Step 4: Run test to verify it passes**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_selection_policy.py -q --tb=short --no-header
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/evaluation/selection_policy.py core/evaluation/runner.py tests/test_selection_policy.py
git commit -m "feat(evaluation): compare baseline and candidate runs"
```

---

## Task 6: Expose environment fitness to the agent

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\tools\git_tools.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\tools\Key_Tools.py`
- Create: `C:\Users\17533\Desktop\Vibelution\tests\test_environment_fitness_tool.py`

**Step 1: Write the failing test**

Add tests for:

- reading recent environment evaluation summaries
- separating internal mutation fitness from benchmark environment fitness
- returning a compact JSON summary suitable for prompt injection

Suggested tool behavior:

- keep `get_evolution_fitness_tool()` for internal audit fitness
- add a new tool such as `get_environment_fitness_tool()`

**Step 2: Run test to verify it fails**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_environment_fitness_tool.py -q --tb=short --no-header
```

Expected: FAIL until the tool and result query path exist.

**Step 3: Write minimal implementation**

Implement a compact environment fitness read path that surfaces:

- recent benchmark runs
- promotion decisions
- success rates by benchmark
- latest regressions

Keep the payload small enough to use in prompt context.

**Step 4: Run test to verify it passes**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_environment_fitness_tool.py -q --tb=short --no-header
```

Expected: PASS.

**Step 5: Commit**

```bash
git add tools/git_tools.py tools/Key_Tools.py tests/test_environment_fitness_tool.py
git commit -m "feat(prompt): expose environment fitness summary"
```

---

## Task 7: Add a focused terminal evaluation bundle

**Files:**
- Create: `C:\Users\17533\Desktop\Vibelution\workspace\evaluation\bundles\terminal_core_v1.json`
- Modify: `C:\Users\17533\Desktop\Vibelution\config.toml`
- Create: `C:\Users\17533\Desktop\Vibelution\tests\test_evaluation_bundle_config.py`

**Step 1: Write the failing test**

Add tests for:

- resolving the default stable evaluation bundle
- loading a bundle file from workspace
- validating bundle schema
- limiting case counts and time budgets

Suggested bundle fields:

- `benchmark`
- `bundle_name`
- `case_ids`
- `max_case_runtime_seconds`
- `selection_threshold`

**Step 2: Run test to verify it fails**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_evaluation_bundle_config.py -q --tb=short --no-header
```

Expected: FAIL before bundle config exists.

**Step 3: Write minimal implementation**

Add a new evaluation config block, separate from `[evolution]`, for example:

```toml
[evaluation]
enabled = true
default_profile = "terminal_local"
default_bundle = "terminal_core_v1"
result_dir = "workspace/evaluation"
promotion_threshold = 0.05
```

Keep bundle resolution simple and workspace-local.

**Step 4: Run test to verify it passes**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_evaluation_bundle_config.py -q --tb=short --no-header
```

Expected: PASS.

**Step 5: Commit**

```bash
git add workspace/evaluation/bundles/terminal_core_v1.json config.toml tests/test_evaluation_bundle_config.py
git commit -m "feat(config): add terminal evaluation bundle"
```

---

## Task 8: Add an end-to-end dry-run integration test

**Files:**
- Create: `C:\Users\17533\Desktop\Vibelution\tests\test_terminal_bench_flow.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\tests\test_runner.py`

**Step 1: Write the failing test**

Add one focused end-to-end dry-run test that verifies:

- a terminal benchmark case is loaded
- baseline and candidate requests are generated
- both are run through the benchmark harness interface
- results are scored
- a promotion decision is produced and persisted

This test should stub expensive live agent execution while keeping the orchestration path real.

**Step 2: Run test to verify it fails**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_terminal_bench_flow.py -q --tb=short --no-header
```

Expected: FAIL until the full flow exists.

**Step 3: Write minimal implementation**

Wire together:

- adapter
- benchmark harness
- result store
- selection policy

Keep the orchestration thin and explicit. Avoid adding hidden magic or implicit retries.

**Step 4: Run test to verify it passes**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests\test_terminal_bench_flow.py -q --tb=short --no-header
```

Expected: PASS.

**Step 5: Add to focused validation surface**

Update `tests/test_runner.py` so the new evaluation flow can be included in a named validation profile, but keep it out of the cheapest inner smoke profile.

**Step 6: Commit**

```bash
git add tests/test_terminal_bench_flow.py tests/test_runner.py
git commit -m "test(evaluation): add terminal bench dry-run integration flow"
```

---

## Final Verification

Run the focused suite:

```bash
.\.venv\Scripts\python.exe -m pytest ^
  tests/test_benchmark_registry.py ^
  tests/test_terminal_bench_adapter.py ^
  tests/test_benchmark_harness.py ^
  tests/test_evaluation_result_store.py ^
  tests/test_selection_policy.py ^
  tests/test_environment_fitness_tool.py ^
  tests/test_evaluation_bundle_config.py ^
  tests/test_terminal_bench_flow.py ^
  -q --tb=short --no-header
```

Then run the standard safety checks:

```bash
.\.venv\Scripts\python.exe tests/test_runner.py --environment-smoke
.\.venv\Scripts\python.exe -m pytest tests/ -x --tb=short -q
```

---

## Expected Outcome

After this phase, Vibelution should be able to:

- run terminal benchmark cases inside isolated sandboxes
- compare baseline and candidate mutations on the same tasks
- make a deterministic promotion decision
- persist external environment fitness results
- expose those results back to the agent as structured evidence

At that point, the project will have crossed an important line:

from internal self-editing with safety gates  
to environment-shaped self-evolution with real selection pressure.
