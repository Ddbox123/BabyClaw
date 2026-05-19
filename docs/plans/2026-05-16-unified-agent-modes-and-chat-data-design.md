# Unified Agent Modes And Chat Data Design

## Goal

Turn Vibelution into one unified agent with three runtime modes:

1. `chat`
2. `self_evolution`
3. `supervised_evolution`

The core requirement is that chat and evolution must not split into two different brains. They must share:

- the same prompt assets
- the same tool stack
- the same delegation style
- the same memory and growth loop

At the same time, they must differ in orchestration behavior and operational guardrails.

This design intentionally avoids a large refactor first. It keeps `agent.py` as the composition root and adds mode-aware orchestration around the existing core modules.

---

## Product Intent

### What the user wants

- `chat` is a real ongoing conversation mode, not a thin single-turn wrapper.
- `self_evolution` keeps multi-turn context and can continue thinking, using tools, and delegating.
- `supervised_evolution` uses the same evolution orchestration as `self_evolution`, but it is driven by an explicit supervised case request.
- `supervised_evolution` must reset context between cases.
- chat should silently collect useful multi-turn conversation segments as future evolution data.
- explicit evolution requests inside chat should be routed to the workbench evolution entry, not executed inline.

### What this design avoids

- no second agent implementation for chat
- no duplicated prompt stack
- no duplicated tool layer
- no duplicated transcript or dataset format
- no immediate large-scale migration out of `agent.py`

---

## High-Level Architecture

There is still one core agent class:

- `SelfEvolvingAgent` in `C:\Users\17533\Desktop\Vibelution\agent.py`

It gains a runtime mode concept and two orchestration skeletons:

1. `chat orchestrator`
2. `evolution orchestrator`

Mode mapping:

- `chat` -> `chat orchestrator`
- `self_evolution` -> `evolution orchestrator`
- `supervised_evolution` -> `evolution orchestrator`

This means there are three modes but only two orchestration families.

Shared core modules remain the main engine:

- prompt building: `core/prompt_manager/`
- llm client: `core/llm/client.py`
- tool execution: `core/infrastructure/tool_executor.py`
- delegation: `core/orchestration/delegation_governor.py`
- response parsing: `core/orchestration/response_processor.py`
- response surfacing: `core/orchestration/response_surface.py`
- round state: `core/orchestration/round_state.py`
- turn outcome: `core/orchestration/turn_outcome.py`
- logging/transcripts: `core/logging/unified_logger.py`

The new work is not a new brain. It is mode-aware orchestration and chat-data capture layered on top of the existing brain.

---

## Mode Model

### Runtime enum

Add an internal runtime enum:

- `AgentMode.CHAT`
- `AgentMode.SELF_EVOLUTION`
- `AgentMode.SUPERVISED_EVOLUTION`

### Mode policy

Add a small mode policy object, either in `agent.py` initially or in a new helper file later.

Suggested fields:

- `mode`
- `orchestrator_kind`: `chat` or `evolution`
- `keep_multi_turn_context`
- `allow_auto_loop`
- `capture_chat_dataset_candidates`
- `route_explicit_evolution_requests`
- `reset_context_before_turn`
- `reset_context_between_cases`
- `allow_direct_supervised_payload`
- `finish_after_direct_response`

Recommended behavior:

#### `chat`

- `orchestrator_kind = "chat"`
- `keep_multi_turn_context = true`
- `allow_auto_loop = false`
- `capture_chat_dataset_candidates = true`
- `route_explicit_evolution_requests = true`
- `reset_context_before_turn = false`
- `reset_context_between_cases = false`
- `allow_direct_supervised_payload = false`
- `finish_after_direct_response = false`

#### `self_evolution`

- `orchestrator_kind = "evolution"`
- `keep_multi_turn_context = true`
- `allow_auto_loop = true`
- `capture_chat_dataset_candidates = false`
- `route_explicit_evolution_requests = false`
- `reset_context_before_turn = false`
- `reset_context_between_cases = false`
- `allow_direct_supervised_payload = false`
- `finish_after_direct_response = false`

#### `supervised_evolution`

- `orchestrator_kind = "evolution"`
- `keep_multi_turn_context = true`
- `allow_auto_loop = false`
- `capture_chat_dataset_candidates = false`
- `route_explicit_evolution_requests = false`
- `reset_context_before_turn = true` only when a new case starts
- `reset_context_between_cases = true`
- `allow_direct_supervised_payload = true`
- `finish_after_direct_response = false`

---

## Config Design

This behavior must be visible and tunable in config instead of being hidden in hardcoded branches.

### 1. Extend `AgentConfig`

File:

- `C:\Users\17533\Desktop\Vibelution\config\models.py`

Add nested config under `agent`:

- `default_mode`
- `modes`

Suggested model:

```python
class AgentModesConfig(BaseModel):
    chat_enabled: bool = True
    self_evolution_enabled: bool = True
    supervised_evolution_enabled: bool = True
    default_shell_mode: str = "chat"
    default_headless_mode: str = "self_evolution"
    explicit_evolution_request_behavior: str = "route_to_workbench"

class AgentConfig(BaseModel):
    ...
    default_mode: str = "self_evolution"
    modes: AgentModesConfig = Field(default_factory=AgentModesConfig)
```

Meaning:

- `default_mode` is the general fallback when code needs one mode.
- `default_shell_mode` is what the workbench should highlight first.
- `default_headless_mode` is what direct CLI auto-run uses.

### 2. Add chat dataset capture config under `EvolutionConfig`

This belongs under evolution, not under UI, because the point is to turn chat into evolution evidence.

Suggested model:

```python
class ChatDatasetCaptureConfig(BaseModel):
    enabled: bool = True
    source_modes: List[str] = Field(default_factory=lambda: ["chat"])
    auto_capture: bool = True
    segmentation_strategy: str = "task_contiguous"
    min_turns: int = 2
    max_turns: int = 12
    require_tool_call_or_analysis_or_conclusion: bool = True
    exclude_pure_chitchat: bool = True
    candidate_dir: str = "workspace/evaluation/chat_candidates"
    review_queue_path: str = "workspace/evaluation/chat_review_queue.jsonl"
    approved_raw_dir: str = "workspace/evaluation/chat_approved/raw"
    approved_jsonl_path: str = "workspace/evaluation/datasets/chat_reviewed_multiturn.jsonl"
    rejected_log_path: str = "workspace/evaluation/chat_rejected.jsonl"
```

And add:

```python
class EvolutionConfig(BaseModel):
    ...
    chat_dataset: ChatDatasetCaptureConfig = Field(default_factory=ChatDatasetCaptureConfig)
```

### 3. `config.toml` additions

File:

- `C:\Users\17533\Desktop\Vibelution\config.toml`

Add:

```toml
[agent]
default_mode = "self_evolution"

[agent.modes]
chat_enabled = true
self_evolution_enabled = true
supervised_evolution_enabled = true
default_shell_mode = "chat"
default_headless_mode = "self_evolution"
explicit_evolution_request_behavior = "route_to_workbench"

[evolution.chat_dataset]
enabled = true
source_modes = ["chat"]
auto_capture = true
segmentation_strategy = "task_contiguous"
min_turns = 2
max_turns = 12
require_tool_call_or_analysis_or_conclusion = true
exclude_pure_chitchat = true
candidate_dir = "workspace/evaluation/chat_candidates"
review_queue_path = "workspace/evaluation/chat_review_queue.jsonl"
approved_raw_dir = "workspace/evaluation/chat_approved/raw"
approved_jsonl_path = "workspace/evaluation/datasets/chat_reviewed_multiturn.jsonl"
rejected_log_path = "workspace/evaluation/chat_rejected.jsonl"
```

### 4. CLI exposure

File:

- `C:\Users\17533\Desktop\Vibelution\core\infrastructure\cli_utils.py`

Add:

```python
parser.add_argument(
    "--mode",
    choices=["chat", "self_evolution", "supervised_evolution"],
    default=None,
    help="运行模式"
)
```

`build_config_kwargs()` should not hardwire the mode into config unless explicitly desired. Prefer using CLI mode as a runtime override and config mode as a default fallback.

---

## Orchestration Design

## Chat orchestrator

Purpose:

- ongoing interaction
- same tools and same style as the main agent
- sample high-value conversations in the background
- route explicit evolution requests away from the chat loop

Behavior:

1. preserve turn carryover across the session
2. allow tool use
3. allow delegation/subagents
4. never auto-sleep or auto-loop by itself
5. if the input is an explicit evolution request, do not execute it inline; surface a routing signal back to the workbench
6. after each turn, try to emit a chat dataset candidate

This orchestrator should still reuse:

- `TurnOutcomeController.prepare_turn_messages(...)`
- `ToolLifecycleBridge`
- `ResponseProcessor`
- `ResponseSurfaceController`
- `TurnOutcomeController.finish_turn_message_carryover(...)`

The main difference is policy, not mechanics.

## Evolution orchestrator

Purpose:

- autonomous evolution loops
- supervised-case-driven evolution
- persistent multi-step execution

Behavior:

1. preserve multi-turn context inside the current evolution run
2. allow tool use and delegation
3. permit restart-focused behavior and evolution transactions
4. for `self_evolution`, run from goal-driven autonomous prompting
5. for `supervised_evolution`, inject a supervised case request and reset context before each case

### Supervised case boundary

This is a hard rule:

- context is preserved inside one supervised case
- context is reset between supervised cases

The reset must clear:

- carryover messages
- active turn goal
- runtime constraint state
- mode-local chat candidate buffers

It must not clear:

- shared prompt assets on disk
- long-term workspace memories
- approved evolution datasets

---

## Runtime Input Design

The existing `runtime_input` protocol is task-oriented. That is acceptable for evolution mode but awkward for user chat.

File:

- `C:\Users\17533\Desktop\Vibelution\core\infrastructure\runtime_input.py`

Add two new input kinds:

- `CHAT_USER_MESSAGE`
- `SUPERVISED_EVOLUTION_REQUEST`

Suggested usage:

- chat turns should be wrapped as `CHAT_USER_MESSAGE`
- supervised cases should be wrapped as `SUPERVISED_EVOLUTION_REQUEST`

This keeps one message protocol while letting prompt framing differ by mode.

---

## Chat Data Capture Design

The chat dataset pipeline must reuse the current logging system and the current evaluation dataset system.

### Raw capture source

Reuse:

- `core/logging/unified_logger.py`
- `core/logging/transcript_logger.py`
- existing conversation JSON logs

Do not invent a separate raw conversation store.

### Candidate generation pipeline

New lightweight modules are acceptable under a small namespace such as:

- `core/evaluation/chat_dataset_capture.py`
- `core/evaluation/chat_segmenter.py`
- `core/evaluation/chat_review_queue.py`

Responsibilities:

#### `chat_segmenter`

Split a full conversation session into multi-turn task-contiguous segments.

A segment should track:

- `session_id`
- `segment_id`
- `mode`
- `start_turn`
- `end_turn`
- `turn_count`
- `user_messages`
- `assistant_messages`
- `tool_calls`
- `has_delegation`
- `has_explicit_conclusion`
- `has_next_action`
- `topic_summary`

#### `chat_dataset_capture`

Apply automatic inclusion and exclusion rules.

Default inclusion signals:

- tool call happened
- meaningful analysis happened
- task got narrowed
- conclusion was produced
- next action was recommended
- multi-step collaboration happened

Default exclusion signals:

- pure greeting
- short acknowledgement only
- emotional companionship without task work
- no reasoning progress
- no conclusion
- no concrete collaborative movement

Only qualified candidates enter the review queue.

#### `chat_review_queue`

Persist:

- candidate metadata
- raw excerpt path
- review status
- reviewer note
- approved/rejected timestamp

### Review queue storage

Recommended storage:

- queue index: JSONL
- raw segment content: one JSON file per candidate

This keeps auditability simple.

---

## Reviewed Dataset Design

When approved, a candidate becomes two artifacts:

1. raw approved segment
2. structured evolution sample

### Raw approved segment

Store under:

- `workspace/evaluation/chat_approved/raw/`

Each file should preserve:

- exact multi-turn dialogue
- tool activity summary
- source session id
- source turn range
- approval metadata

### Structured sample

Append one JSONL row to:

- `workspace/evaluation/datasets/chat_reviewed_multiturn.jsonl`

Each row should include:

- `case_id`
- `mode = "multiturn_chat"`
- `scenario = "conversation_collaboration"`
- `prompt_seed` or first user request
- `conversation_turns`
- `expected_effect`
- `quality_signals`
- `dataset_ref`
- `approval`

This JSONL should then be registered in:

- `core/evaluation/dataset_registry.py`

Add one new dataset spec:

- `name = "chat_reviewed_multiturn"`
- `kind = "prompt_jsonl"`
- `bundle_name = "chat_reviewed_multiturn_v1"`
- `source_path = "workspace/evaluation/datasets/chat_reviewed_multiturn.jsonl"`
- `mode = "single_turn"` for v1 materialization, even if the content is multiturn

V1 simplification:

- materialize each approved multiturn segment into one supervised case payload
- embed the segment context into the candidate prompt

This lets the existing dataset registry and bundle materializer continue working with minimal change.

---

## Workbench Responsibilities

File:

- `C:\Users\17533\Desktop\Vibelution\core\ui\workbench.py`

Workbench remains the operational router, not a second agent.

### Chat entry

- instantiate agent with `mode="chat"`
- keep the existing user-facing shell loop
- if the agent surfaces an `evolution_route_requested` result, exit chat flow back to the evolution menu

### Evolution entry

Keep:

- self evolution controls
- supervised evolution controls
- history and evidence

Add:

- review queue for chat-derived candidates
- approve/reject actions
- preview raw segment and generated structured sample

### Supervised evolution entry

No inline chat routing here. This remains an explicit control plane for running benchmarked or reviewed cases.

---

## `agent.py` Implementation Shape

This design does not require a full runtime extraction first.

Recommended first-step edits inside `agent.py`:

1. add `AgentMode`
2. add `ModePolicy`
3. accept `mode` in `SelfEvolvingAgent.__init__`
4. split orchestration entry into:
   - `_run_chat_turn(...)`
   - `_run_evolution_turn(...)`
5. keep shared low-level helpers:
   - `_invoke_llm`
   - `_sync_runtime_state_memory`
   - `_maybe_delegate`
   - `_get_turn_outcome_controller`
   - `_get_response_surface_controller`
6. add a post-turn hook:
   - `_capture_chat_dataset_candidate_if_needed(...)`
7. add a case-boundary reset hook for supervised runs:
   - `_reset_mode_context_for_supervised_case(...)`

This is intentionally a mode-aware composition change, not a full rewrite.

---

## Testing Plan

### New tests

- `tests/test_agent_modes.py`
  - mode policy selection
  - chat mode routes explicit evolution requests
  - self evolution uses evolution orchestrator
  - supervised evolution resets context between cases

- `tests/test_chat_dataset_capture.py`
  - task-contiguous segmentation
  - pure chitchat exclusion
  - tool/analysis/conclusion inclusion
  - review queue append and approval flow

- `tests/test_dataset_registry.py`
  - new `chat_reviewed_multiturn` spec loads and materializes

### Existing tests that should keep passing

- `tests/test_agent_protocol.py`
- `tests/test_tool_executor.py`
- `tests/test_prompt_manager.py`
- `tests/test_agent_session_runtime.py`
- `tests/test_supervised_evolution.py`

---

## Incremental Rollout

### Phase 1

- add mode enum and mode policy
- keep one agent class
- add chat orchestrator branch
- add supervised case context reset

### Phase 2

- add config models and `config.toml`
- wire CLI mode override
- wire workbench chat/evolution mode selection

### Phase 3

- add chat candidate capture
- add review queue in evolution workbench
- add approved chat dataset registration

### Phase 4

- let supervised evolution run approved chat-derived cases through the existing bundle pipeline

---

## Decision Summary

The system should move to:

- one unified agent
- three runtime modes
- two orchestration families
- shared growth assets
- chat as a default data source for evolution
- evolution as the explicit governance path for promotion and supervised review

This preserves the user's core requirement:

chat and evolution are not separate systems; they are two operational faces of the same growing agent.
