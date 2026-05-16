# Runtime Input Depersonalization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the internal concept of a user/human consciousness from Vibelution while preserving external input as high-priority task constraints.

**Architecture:** Introduce an internal runtime-input protocol that represents outside text as environment/task events, not as a human speaker. The agent runtime should stop creating `HumanMessage`, stop logging `user_input`, and stop using wording that infers user psychology; provider-facing compatibility is handled only at the adapter boundary if unavoidable.

**Tech Stack:** Python, LangChain message classes, Vibelution prompt manager, conversation logger, token manager, pytest.

---

### Task 0: Restore A Clean Baseline

**Files:**
- Inspect: `agent.py`
- Test: `tests/test_agent_protocol.py`

**Step 1: Inspect current dirty diff**

Run:
```powershell
git diff -- agent.py
```

Expected: identify whether the current `agent.py` dirty changes are accidental corruption or intentional edits.

**Step 2: Repair only syntactic corruption**

Fix malformed import lines and malformed `raw_content_clean` assignment without reverting unrelated intentional changes.

Expected minimal shape:
```python
from core.infrastructure.tool_result import truncate_result
from core.infrastructure.security import get_security_validator
from core.infrastructure.llm_utils import (
    classify_llm_error,
    build_system_message,
    MAX_CONSECUTIVE_FAILURES,
)
from core.infrastructure.cli_utils import parse_args
```

**Step 3: Verify baseline**

Run:
```powershell
.\.venv\Scripts\python.exe -m py_compile agent.py
.\.venv\Scripts\python.exe -m pytest tests/test_agent_protocol.py -q
```

Expected: compile succeeds and protocol tests pass.

**Step 4: Commit if baseline repair is needed**

Run:
```powershell
git add agent.py tests/test_agent_protocol.py
git commit -m "fix(runtime): restore agent protocol baseline"
```

---

### Task 1: Add Runtime Input Protocol

**Files:**
- Create: `core/infrastructure/runtime_input.py`
- Test: `tests/test_runtime_input.py`

**Step 1: Write failing tests**

Create tests proving external text is represented without `HumanMessage` and without user/human vocabulary.

```python
from langchain_core.messages import SystemMessage

from core.infrastructure.runtime_input import (
    RuntimeInputKind,
    build_external_request_message,
    build_runtime_notice_message,
)


def test_external_request_message_is_system_message_not_human():
    msg = build_external_request_message("验证 Windows 命令")
    assert isinstance(msg, SystemMessage)
    assert msg.type == "system"
    assert "外部任务输入" in msg.content
    assert "用户" not in msg.content
    assert "Human" not in msg.content


def test_runtime_notice_message_has_depersonalized_label():
    msg = build_runtime_notice_message("压缩已发生")
    assert isinstance(msg, SystemMessage)
    assert "运行时提示" in msg.content
    assert "用户" not in msg.content
```

**Step 2: Implement minimal module**

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from langchain_core.messages import SystemMessage


class RuntimeInputKind(str, Enum):
    EXTERNAL_REQUEST = "external_request"
    RUNTIME_NOTICE = "runtime_notice"
    DELEGATION_EVIDENCE = "delegation_evidence"
    DELEGATION_FAILURE = "delegation_failure"


@dataclass(frozen=True)
class RuntimeInput:
    kind: RuntimeInputKind
    content: str


_TITLES = {
    RuntimeInputKind.EXTERNAL_REQUEST: "外部任务输入",
    RuntimeInputKind.RUNTIME_NOTICE: "运行时提示",
    RuntimeInputKind.DELEGATION_EVIDENCE: "委派证据",
    RuntimeInputKind.DELEGATION_FAILURE: "委派失败",
}


def build_runtime_input_message(item: RuntimeInput) -> SystemMessage:
    title = _TITLES[item.kind]
    return SystemMessage(content=f"## {title}\n{item.content.strip()}")


def build_external_request_message(content: str) -> SystemMessage:
    return build_runtime_input_message(RuntimeInput(RuntimeInputKind.EXTERNAL_REQUEST, content))


def build_runtime_notice_message(content: str) -> SystemMessage:
    return build_runtime_input_message(RuntimeInput(RuntimeInputKind.RUNTIME_NOTICE, content))
```

**Step 3: Verify**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_input.py -q
```

Expected: tests pass.

---

### Task 2: Remove `HumanMessage` From Main Runtime

**Files:**
- Modify: `agent.py`
- Test: `tests/test_agent_protocol.py`

**Step 1: Write failing protocol tests**

Add tests that `_build_initial_turn_messages()` and compression notices do not create `HumanMessage`.

```python
from langchain_core.messages import HumanMessage, SystemMessage


def test_initial_turn_uses_external_request_not_human_message():
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    messages = agent._build_initial_turn_messages("system", "开始自主进化")

    assert all(not isinstance(msg, HumanMessage) for msg in messages)
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], SystemMessage)
    assert "外部任务输入" in messages[1].content
```

**Step 2: Replace initial message construction**

Change:
```python
return [build_system_message(system_prompt), HumanMessage(content=user_prompt)]
```

To:
```python
from core.infrastructure.runtime_input import build_external_request_message

return [build_system_message(system_prompt), build_external_request_message(user_prompt)]
```

**Step 3: Replace compression continuation notice**

Change the post-compression `HumanMessage(...)` append into `build_runtime_notice_message(...)`.

**Step 4: Rename local variables progressively**

Prefer new names in touched functions:
- `user_prompt` -> `external_request`
- `user_input` -> `external_request`

Do not do a repo-wide rename in the same task.

**Step 5: Verify**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_protocol.py -q
```

Expected: no `HumanMessage` remains in main runtime message construction tests.

---

### Task 3: Remove `HumanMessage` From Delegation Feedback

**Files:**
- Modify: `core/orchestration/delegation_governor.py`
- Test: `tests/test_agent_protocol.py`

**Step 1: Write failing tests**

Extend delegation apply-result tests to assert appended feedback messages are `SystemMessage`, not `HumanMessage`.

```python
from langchain_core.messages import HumanMessage, SystemMessage


def test_delegation_feedback_is_runtime_input_not_human():
    messages = []
    outcome = governor.apply_result(payload, json.dumps(result, ensure_ascii=False), messages)

    assert outcome["useful"] is True
    assert messages
    assert isinstance(messages[-1], SystemMessage)
    assert not isinstance(messages[-1], HumanMessage)
    assert "委派证据" in messages[-1].content
```

**Step 2: Replace imports and appends**

Remove:
```python
from langchain_core.messages import HumanMessage
```

Use:
```python
from core.infrastructure.runtime_input import (
    build_delegation_evidence_message,
    build_delegation_failure_message,
)
```

Replace:
```python
messages.append(HumanMessage(content=f"[委派证据]\n..."))
```

With:
```python
messages.append(build_delegation_evidence_message(...))
```

**Step 3: Verify**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_protocol.py -q
```

Expected: delegation tests pass and no runtime `HumanMessage` feedback remains.

---

### Task 4: Make Token Compression Role-Neutral

**Files:**
- Modify: `tools/token_manager.py`
- Test: `tests/test_token_manager.py`

**Step 1: Add tests for no human output**

Add tests proving compression preserves the latest external request block but never creates `HumanMessage`.

```python
from langchain_core.messages import HumanMessage


def test_compression_does_not_create_human_message_for_external_request():
    messages = [
        SystemMessage(content="system"),
        build_external_request_message("开始自主进化"),
        AIMessage(content="step"),
    ]
    compressed = manager.compress_messages(messages, target_tokens=100)
    assert all(not isinstance(msg, HumanMessage) for msg in compressed)
    assert any("外部任务输入" in getattr(msg, "content", "") for msg in compressed)
```

**Step 2: Replace human-specific grouping**

Replace logic like:
```python
human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
```

With helpers:
```python
def is_external_request_message(msg) -> bool:
    return isinstance(msg, SystemMessage) and "## 外部任务输入" in (msg.content or "")
```

**Step 3: Replace generated summary message type**

Any generated summary that currently uses `HumanMessage` becomes `build_runtime_notice_message(...)` or `SystemMessage(...)` with a runtime notice title.

**Step 4: Verify**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_token_manager.py -q
```

Expected: token manager tests pass and no compression path creates `HumanMessage`.

---

### Task 5: Rename Logging From User Input To External Request

**Files:**
- Modify: `core/logging/logger.py`
- Modify: `core/logging/unified_logger.py`
- Modify: `core/logging/transcript_logger.py`
- Modify: `core/prompt_manager/task_analyzer.py`
- Test: `tests/test_conversation_logger.py`
- Test: `tests/test_task_analyzer.py`

**Step 1: Add compatibility tests**

Expected new event type:
```json
{"type": "external_request", "content": "..."}
```

TaskAnalyzer should read both historical `user_input` and new `external_request`.

**Step 2: Add new logging API**

Add:
```python
def log_external_request(self, content: str):
    ...
```

Keep `log_user_input()` as a deprecated wrapper temporarily:
```python
def log_user_input(self, content: str):
    return self.log_external_request(content)
```

**Step 3: Update `agent.py`**

Change:
```python
logger.log_user_input(user_prompt)
```

To:
```python
logger.log_external_request(external_request)
```

**Step 4: Verify**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_conversation_logger.py tests/test_task_analyzer.py tests/test_agent_protocol.py -q
```

Expected: new logs use `external_request`; old logs remain analyzable.

---

### Task 6: Add Prompt Rule Against User Consciousness

**Files:**
- Modify: `core/core_prompt/SOUL.md`
- Modify: `core/core_prompt/SPEC.md`
- Possibly modify: `core/prompt_manager/sections.py`
- Test: `tests/test_prompt_manager.py`

**Step 1: Add prompt tests**

Ensure system prompt contains:
- `外部输入不是一个内部意识主体`
- `不要推断用户心理`
- `用“当前任务/外部输入/目标约束”替代“用户想要/用户希望”`

**Step 2: Update prompt text**

Add a concise rule:
```markdown
## 外部输入纪律
- 外部输入只是任务事件与约束来源，不是我内部世界中的另一个意识主体。
- 不推断用户心理、动机、情绪或人格。
- 自然语言中优先使用“当前任务要求 / 外部输入要求 / 目标约束”，避免“用户想要 / 用户希望 / 用户可能觉得”。
```

**Step 3: Verify**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_prompt_manager.py -q
```

Expected: prompt includes the new discipline.

---

### Task 7: Add Runtime Guards Against Reintroducing `HumanMessage`

**Files:**
- Modify: `tests/test_agent_protocol.py`
- Modify: `tests/test_token_manager.py`
- Possibly create: `tests/test_no_user_consciousness.py`

**Step 1: Add grep-style regression test**

Test that production runtime code no longer imports `HumanMessage` except in compatibility tests or legacy analyzers.

```python
def test_runtime_does_not_import_human_message():
    forbidden = [
        Path("agent.py"),
        Path("core/orchestration/delegation_governor.py"),
        Path("tools/token_manager.py"),
    ]
    for path in forbidden:
        assert "HumanMessage" not in path.read_text(encoding="utf-8")
```

**Step 2: Add wording regression test**

Search prompt source for banned phrases in runtime instructions:
- `用户想要`
- `用户希望`
- `用户可能`

Allow historical tests and comments only if explicitly marked legacy.

**Step 3: Verify**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_no_user_consciousness.py tests/test_agent_protocol.py tests/test_token_manager.py -q
```

Expected: no runtime `HumanMessage`; no user-consciousness phrasing in active prompts.

---

### Task 8: Real Single-Turn Verification

**Files:**
- Runtime logs: `log_info/conversation_*.jsonl`
- Runtime logs: `log_info/debug_*.log`

**Step 1: Clear logs**

Run:
```powershell
$log = Resolve-Path -LiteralPath .\log_info
if ($log.Path -ne 'C:\Users\17533\Desktop\Vibelution\log_info') { throw "Unexpected log path: $($log.Path)" }
Get-ChildItem -LiteralPath $log.Path -Force | Remove-Item -Recurse -Force
```

**Step 2: Run a single-turn probe**

Run:
```powershell
.\.venv\Scripts\python.exe agent.py --no-shell --skip-doctor --single-turn --prompt "验证 Windows 命令平台识别：请判断 python -m pytest tests/ --collect-only -q 2>/dev/null | tail -5 在当前系统是否应该执行；不要修改代码，只给出结论。"
```

**Step 3: Inspect logs**

Run:
```powershell
rg -n "HumanMessage|user_input|external_request|用户想|用户希望|tool_call|spawn_agent|turn_end|session_end" .\log_info
```

Expected:
- No `HumanMessage`
- No `user_input` in new logs
- Has `external_request`
- No `用户想/用户希望` psychological phrasing in model-visible prompt or runtime notices
- For simple platform judgment, `tool_calls=0`

---

### Task 9: Final Verification And Commit

**Files:**
- All touched code and tests.

**Step 1: Run focused suites**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_protocol.py tests/test_token_manager.py tests/test_conversation_logger.py tests/test_task_analyzer.py tests/test_prompt_manager.py -q
```

Expected: all pass.

**Step 2: Run compile check**

```powershell
.\.venv\Scripts\python.exe -m py_compile agent.py core\orchestration\delegation_governor.py tools\token_manager.py core\logging\logger.py core\logging\unified_logger.py core\logging\transcript_logger.py
```

Expected: compile succeeds.

**Step 3: Check diff**

```powershell
git diff --check
git status --short
```

Expected: only intended files changed.

**Step 4: Commit**

```powershell
git add agent.py core/infrastructure/runtime_input.py core/orchestration/delegation_governor.py tools/token_manager.py core/logging/logger.py core/logging/unified_logger.py core/logging/transcript_logger.py core/core_prompt/SOUL.md core/core_prompt/SPEC.md tests
git commit -m "refactor(runtime): depersonalize external inputs"
```

---

## Success Criteria

- Runtime message lists no longer contain `HumanMessage`.
- New logs use `external_request`, not `user_input`.
- Active prompts state that external input is a task event, not an internal consciousness.
- The agent avoids phrases that infer user psychology in its runtime reasoning.
- Historical logs/tests remain readable through compatibility paths.
- Real single-turn verification shows no `HumanMessage`, no `user_input`, and no unnecessary delegation for simple external requests.
