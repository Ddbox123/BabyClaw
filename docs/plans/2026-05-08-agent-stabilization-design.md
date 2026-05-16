# Agent Stabilization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stabilize the agent's self-evolution loop so code changes become safe, testable, and repeatable before adding more capabilities.

**Architecture:** Keep the existing ReAct-style control flow, but harden the protocol and validation layers around it. The work is split into three tracks: protect the main loop with protocol-level tests, build a minimal post-change acceptance pipeline, and separate primary tool-calling behavior from fallback behavior so failures are observable instead of silent.

**Tech Stack:** Python 3.14, LangChain message objects, pytest, current `agent.py` loop, `core/infrastructure/*`, `tools/*`.

---

### Task 1: Lock down the main loop message protocol

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\agent.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\core\infrastructure\llm_utils.py`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_agent_protocol.py`

**Step 1: Write the failing test**

Add tests for:
- assistant message with `tool_calls` survives a round-trip through `_invoke_llm`
- tool results become `ToolMessage` when `tool_call_id` exists
- XML fallback still works when no standard `tool_call_id` exists
- state injection does not strip tool metadata from standard tool-calling responses

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_agent_protocol.py -q -s --tb=short --no-header`

Expected: failure in one or more protocol assertions.

**Step 3: Write minimal implementation**

Update the loop so:
- standard assistant responses are preserved as full `AIMessage` objects
- tool results use `ToolMessage` when a `tool_call_id` exists
- XML fallback remains explicitly separated as a non-standard path
- any helper that normalizes messages keeps metadata instead of rebuilding from raw text only

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_agent_protocol.py -q -s --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add agent.py core/infrastructure/llm_utils.py tests/test_agent_protocol.py
git commit -m "test: lock down tool-calling protocol flow"
```

### Task 2: Build a focused main-loop regression suite

**Files:**
- Create: `C:\Users\17533\Desktop\Vibelution\tests\test_agent_loop.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\tests\conftest.py`
- Reference: `C:\Users\17533\Desktop\Vibelution\agent.py`

**Step 1: Write the failing test**

Add a small, high-value suite covering:
- local provider boot without API key when `require_api_key = false`
- repeated tool-call turn with prior history preserved
- LLM error retry path
- compression request path after a tool turn
- restart-tool result handling path

Use mocks only where external providers or UI would make the test flaky.

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --tb=short --no-header`

Expected: FAIL until fixtures and loop hooks are complete.

**Step 3: Write minimal implementation**

Only adjust production code when a real loop invariant is missing. Prefer fixture and harness improvements over broad rewrites.

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_agent_loop.py tests/conftest.py
git commit -m "test: add core agent loop regression coverage"
```

### Task 3: Create a minimal post-change acceptance pipeline

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\tests\test_runner.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\tools\shell_tools.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\core\infrastructure\test_gate.py`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_runner.py`

**Step 1: Write the failing test**

Add tests for a minimal acceptance profile that runs:
- protocol regressions
- tool executor regressions
- code analysis regressions
- shell security smoke checks

The test should verify the runner can expose a "safe to continue" subset without requiring the full suite every time.

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_runner.py -q --tb=short --no-header`

Expected: FAIL because the focused acceptance set does not exist yet.

**Step 3: Write minimal implementation**

Add a small named profile such as `core_acceptance` that:
- selects specific files or markers
- is cheap enough to run after every self-edit
- returns structured pass/fail output that the agent can log or store

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_runner.py -q --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_runner.py tools/shell_tools.py core/infrastructure/test_gate.py
git commit -m "feat: add focused post-change acceptance pipeline"
```

### Task 4: Separate primary tool-calling from fallback tool-calling

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\agent.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\core\infrastructure\llm_utils.py`
- Create: `C:\Users\17533\Desktop\Vibelution\tests\test_tool_call_fallbacks.py`

**Step 1: Write the failing test**

Add tests that distinguish:
- standard OpenAI-style tool-calling path
- XML tool-call fallback
- no-tool plain-text response
- malformed fallback payload

The expected outcome is explicit branch behavior, not best-effort guessing.

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_tool_call_fallbacks.py -q --tb=short --no-header`

Expected: FAIL before the fallback contract is formalized.

**Step 3: Write minimal implementation**

Refactor parsing and dispatch so:
- standard path is preferred and isolated
- XML path is clearly marked as fallback
- malformed fallback data is logged and ignored cleanly
- fallback messages cannot accidentally poison the standard message history

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_tool_call_fallbacks.py -q --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add agent.py core/infrastructure/llm_utils.py tests/test_tool_call_fallbacks.py
git commit -m "refactor: split standard and fallback tool-call paths"
```

### Task 5: Make failure memory first-class

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\tools\memory_tools.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\tools\key_info_extractor.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\workspace\prompts\STATE_MEMORY.md`
- Test: `C:\Users\17533\Desktop\Vibelution\tests\test_memory_tools.py`

**Step 1: Write the failing test**

Add tests for recording and retrieving:
- protocol failures
- flaky tool signatures
- timeout failures
- patch-application failures

The test should prove that failure summaries are retrievable in a compact, structured format.

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_memory_tools.py -q --tb=short --no-header`

Expected: FAIL until the failure memory shape is added.

**Step 3: Write minimal implementation**

Add a lightweight structure for "avoid repeating this mistake" entries, separate from broad narrative memory. Keep it small and directly queryable.

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_memory_tools.py -q --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add tools/memory_tools.py tools/key_info_extractor.py workspace/prompts/STATE_MEMORY.md tests/test_memory_tools.py
git commit -m "feat: persist structured failure memory"
```

### Task 6: Add health metrics for self-evolution

**Files:**
- Modify: `C:\Users\17533\Desktop\Vibelution\core\logging\tool_tracker.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\core\logging\unified_logger.py`
- Modify: `C:\Users\17533\Desktop\Vibelution\core\infrastructure\mental_model.py`
- Create: `C:\Users\17533\Desktop\Vibelution\tests\test_agent_health_metrics.py`

**Step 1: Write the failing test**

Add tests for metrics such as:
- tool success rate
- timeout count
- consecutive failed turns
- compression frequency
- restart recovery count

**Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_agent_health_metrics.py -q --tb=short --no-header`

Expected: FAIL until the metrics are emitted and queryable.

**Step 3: Write minimal implementation**

Store the metrics in the existing logging and mental-model layers without creating a separate observability subsystem.

**Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_agent_health_metrics.py -q --tb=short --no-header`

Expected: PASS.

**Step 5: Commit**

```bash
git add core/logging/tool_tracker.py core/logging/unified_logger.py core/infrastructure/mental_model.py tests/test_agent_health_metrics.py
git commit -m "feat: track agent health metrics for evolution"
```

### Task 7: Define the daily operating loop for safe self-evolution

**Files:**
- Create: `C:\Users\17533\Desktop\Vibelution\docs\agent-operating-loop.md`
- Modify: `C:\Users\17533\Desktop\Vibelution\README.md`
- Reference: `C:\Users\17533\Desktop\Vibelution\tests\test_runner.py`

**Step 1: Write the failing test**

This task is doc-first. Instead of a code test, write a checklist and verify it matches the actual commands and test profiles created in Tasks 1-6.

**Step 2: Run validation to verify the checklist is real**

Run:
- `.\.venv\Scripts\python.exe -m pytest tests\test_agent_protocol.py -q -s --tb=short --no-header`
- `.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -q --tb=short --no-header`
- `.\.venv\Scripts\python.exe -m pytest tests\test_tool_call_fallbacks.py -q --tb=short --no-header`

Expected: PASS for the documented commands.

**Step 3: Write minimal implementation**

Document:
- what to run after self-edit
- what blocks restart
- what belongs in failure memory
- which metrics indicate the agent is degrading

**Step 4: Re-run validation**

Use the same commands from Step 2 and make sure the document matches reality.

**Step 5: Commit**

```bash
git add docs/agent-operating-loop.md README.md
git commit -m "docs: define safe self-evolution operating loop"
```

### Recommended execution order

1. Task 1
2. Task 2
3. Task 3
4. Task 4
5. Task 5
6. Task 6
7. Task 7

### Stop conditions

Pause implementation and report immediately if:
- the main loop tests require live network calls to stay meaningful
- protocol fixes break XML fallback without a clear compatibility path
- the acceptance pipeline becomes slow enough to discourage use after each edit
- failure-memory writes begin polluting the main prompt instead of summarizing it

### Success criteria

- Main-loop protocol behavior is directly tested and stable
- Self-edits can be validated with a small, repeatable acceptance profile
- Standard and fallback tool-calling paths are visibly distinct
- Failures are remembered structurally, not just narratively
- The project has a documented operating loop for safe self-evolution
