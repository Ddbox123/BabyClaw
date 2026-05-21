# WorkRun Substrate And Chat Case Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build one shared runtime substrate for Dialogue, Supervised Evolution, and Self Evolution while turning reviewed chat experience into supervised/Gym cases without merging the three business domains.

**Architecture:** Add a horizontal `WorkRun` substrate under the existing runtime-manager/web-service boundary. Domain services keep their own payloads and UI DTOs, but share run lifecycle, active/latest indexes, event stream shape, resource leases, and runtime summary. Chat transcripts flow through a reviewed case pipeline before they can enter datasets or supervised evolution bundles.

**Tech Stack:** Python, FastAPI SSE, existing JSON/JSONL runtime artifacts, React Query, existing `chat_dataset_capture` / `dataset_registry` / `runtime_manager` modules, pytest, Vitest where needed.

---

## Requirements Summary

Functional requirements:

- Dialogue, supervised evolution, and self evolution remain separate product tracks.
- A running chat turn, supervised run, or self-evolution run is represented as a `WorkRun`.
- `active` and `latest` are tracked per `runKind`, not as one global active lock.
- Resource leases decide whether runs may overlap.
- Chat content can become training/evaluation pressure only through `Chat Segment -> Candidate -> Review -> Reviewed Case -> Dataset/Bundle`.
- Runtime summary can show all active/latest runs and their resource leases in one place.

Non-functional requirements:

- Do not rewrite the agent loop.
- Do not migrate historical data in the first pass.
- Do not merge `session_service`, `supervised_control_service`, and `self_evolution_control_service` into one service.
- Preserve existing endpoints while adding shared internals.
- Existing tests for chat, supervised evolution, and self-evolution must keep passing.

## Shared Terms

- `Track`: product lane, one of `dialogue`, `supervised_evolution`, `self_evolution`.
- `WorkRun`: one observable and controllable execution unit.
- `RunKind`: low-level WorkRun kind, initially `chat_turn`, `supervised_evolution_run`, `self_evolution_run`, and later `proposal_action`.
- `ChatSession`: persistent conversation container; not itself a WorkRun.
- `ChatTurn`: one user request execution inside a ChatSession; this is a WorkRun.
- `ResourceLease`: concurrency control claim such as `readonly_chat`, `worktree_write`, `memory_write`, `evaluation`, `evolution_transaction`.
- `Snapshot`: bounded runtime state for UI sync and recovery.
- `EventStream`: live WorkRun events for SSE and query invalidation.
- `ReviewedChatCase`: reviewed and accepted chat-derived case that may enter datasets.
- `TrainingExport`: future model-weight training format; not the same as a supervised case.

## Key Decisions

### Decision 1: Share lifecycle, not business services

Decision: create a WorkRun substrate and let each domain service adapt to it.

Reason: current self/supervised code already duplicates lifecycle concepts, while chat has its own separate turn lifecycle. Unifying the lifecycle removes drift without forcing all business logic into one large service.

Rejected option: merge the three services.

Rejected reason: it would mix chat session history, supervised proposal lifecycle, and self-evolution transaction behavior into one high-risk module.

### Decision 2: Active is scoped by run kind

Decision: store `activeRunId` and `latestRunId` per `runKind`.

Reason: chat, supervised evolution, and self evolution need synchronized visibility, but not forced global serialization.

Rejected option: one global active run.

Rejected reason: it would prevent safe read-only chat during evolution and would make the UI less useful while long runs are active.

### Decision 3: Resource leases decide concurrency

Decision: a run can start only if its required leases do not conflict with existing active leases.

Reason: this matches the real risk boundary better than kind-level blocking. A read-only chat turn can coexist with an evaluation run, while a coding chat turn should not overlap with a self-evolution write pass.

Initial lease policy:

| Run kind | Default leases | Notes |
|---|---|---|
| `chat_turn` read-only | `readonly_chat` | Can overlap with supervised/self runs |
| `chat_turn` coding | `worktree_write`, optional `memory_write` | Conflicts with self-evolution writes |
| `supervised_evolution_run` | `evaluation` | Proposal action may need write leases |
| `self_evolution_run` | `evolution_transaction`, `worktree_write`, `memory_write` | Strictest default |
| `proposal_action` | `policy_write` | Should not run while supervised active |

### Decision 4: Raw chat never becomes training data directly

Decision: raw chat can only become a dataset case through review.

Reason: raw chat may contain thin context, wrong answers, sensitive content, or half-finished reasoning. The current code already has candidate/review/approved/negative paths; the plan promotes that path into the official boundary.

Rejected option: automatically append all chat sessions to datasets.

Rejected reason: it would pollute `V_ref`/training pressure and undermine CRBM evaluation stability.

## High-Level Architecture

```text
Dialogue Track
  ChatSession
  ChatTurn -> WorkRun(chat_turn)
  Chat Segment -> Candidate -> Review -> ReviewedChatCase

Supervised Evolution Track
  Supervised Run -> WorkRun(supervised_evolution_run)
  Dataset/Bundle <- ReviewedChatCase / GeneratedCase
  Decision Record -> Proposal/Advisory

Self Evolution Track
  Self Run -> WorkRun(self_evolution_run)
  Candidate Change / Candidate Case
  Transaction Evidence -> Supervised Validation

Shared Substrate
  WorkRun Store
  Resource Lease Policy
  Event Stream
  Runtime Summary
```

## Task 1: Add WorkRun model and store

**Files:**
- Create: `core/runtime_manager/work_run_store.py`
- Modify: `core/runtime_manager/evolution_store.py`
- Test: `tests/test_work_run_store.py`
- Test: `tests/test_runtime_manager.py`

**Step 1: Write the failing tests**

Add tests that persist and load active/latest snapshots per kind:

```python
def test_work_run_store_tracks_active_and_latest_per_kind(tmp_path, monkeypatch):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    chat = {"runId": "chat_1", "runKind": "chat_turn", "status": "running"}
    self_run = {"runId": "self_1", "runKind": "self_evolution_run", "status": "running"}

    store.persist_snapshot("chat_turn", chat, active_run_id="chat_1")
    store.persist_snapshot("self_evolution_run", self_run, active_run_id="self_1")

    assert store.load_active_snapshot("chat_turn")["runId"] == "chat_1"
    assert store.load_active_snapshot("self_evolution_run")["runId"] == "self_1"
```

Add a compatibility test that existing self/supervised helpers still work through `evolution_store.py`.

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_work_run_store.py -v
pytest tests/test_runtime_manager.py -k "evolution" -v
```

Expected: FAIL because `work_run_store.py` does not exist.

**Step 3: Write minimal implementation**

Implement:

- `normalize_run_kind(kind: str) -> str`
- `WorkRunStore.persist_snapshot(run_kind, snapshot, active_run_id="")`
- `load_run_index(run_kind)`
- `load_active_snapshot(run_kind)`
- `load_latest_snapshot(run_kind)`
- `build_work_run_summary(kinds=None)`

Keep JSON layout simple:

```text
.runtime/work_runs/<runKind>/index.json
.runtime/work_runs/<runKind>/runs/<runId>.json
```

Then update `evolution_store.py` to delegate `self` and `supervised` to the new store while preserving public functions.

**Step 4: Run test to verify it passes**

Run:

```powershell
pytest tests/test_work_run_store.py -v
pytest tests/test_runtime_manager.py -k "evolution" -v
```

Expected: PASS and no behavior change for existing evolution store callers.

**Step 5: Commit**

```powershell
git add core/runtime_manager/work_run_store.py core/runtime_manager/evolution_store.py tests/test_work_run_store.py tests/test_runtime_manager.py
git commit -m "feat(runtime): add shared work run store"
```

## Task 2: Add resource lease policy

**Files:**
- Create: `core/runtime_manager/work_run_leases.py`
- Modify: `core/web/services/session_service.py`
- Modify: `core/web/services/supervised_control_service.py`
- Modify: `core/web/services/self_evolution_control_service.py`
- Test: `tests/test_work_run_leases.py`
- Test: `tests/test_web_app.py`

**Step 1: Write the failing tests**

Add tests for lease compatibility:

```python
def test_readonly_chat_can_overlap_with_supervised_run():
    active = [{"runKind": "supervised_evolution_run", "leases": ["evaluation"], "status": "running"}]
    request = WorkRunLeaseRequest(run_kind="chat_turn", leases=["readonly_chat"])

    assert check_lease_conflicts(request, active).allowed is True
```

```python
def test_coding_chat_conflicts_with_self_evolution_write_run():
    active = [{"runKind": "self_evolution_run", "leases": ["worktree_write"], "status": "running"}]
    request = WorkRunLeaseRequest(run_kind="chat_turn", leases=["worktree_write"])

    result = check_lease_conflicts(request, active)
    assert result.allowed is False
    assert "worktree_write" in result.reason
```

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_work_run_leases.py -v
pytest tests/test_web_app.py -k "session or self_evolution or supervised" -v
```

Expected: FAIL because lease policy does not exist.

**Step 3: Write minimal implementation**

Implement:

- `WorkRunLeaseRequest`
- `WorkRunLeaseDecision`
- `infer_chat_turn_leases(payload)`: read-only by default unless message/tool mode implies coding write.
- `leases_conflict(requested, active)`
- `check_lease_conflicts(request, active_runs)`

Wire only start/resume gates first:

- `session_service` asks for chat leases before scheduling `_run_session_turn`.
- `supervised_control_service` asks for evaluation lease before start/resume.
- `self_evolution_control_service` asks for write/evolution leases before start/resume.

Do not replace all existing busy checks in this task. Keep them as defense in depth.

**Step 4: Run test to verify it passes**

Run:

```powershell
pytest tests/test_work_run_leases.py -v
pytest tests/test_web_app.py -k "session or self_evolution or supervised" -v
```

Expected: PASS with current behavior preserved and conflict reasons centralized.

**Step 5: Commit**

```powershell
git add core/runtime_manager/work_run_leases.py core/web/services/session_service.py core/web/services/supervised_control_service.py core/web/services/self_evolution_control_service.py tests/test_work_run_leases.py tests/test_web_app.py
git commit -m "feat(runtime): add work run lease policy"
```

## Task 3: Register chat turns as WorkRuns

**Files:**
- Modify: `core/web/services/session_service.py`
- Modify: `core/web/services/runtime_service.py`
- Test: `tests/test_web_app.py`
- Test: `tests/test_work_run_store.py`

**Step 1: Write the failing tests**

Add tests that a running chat turn is visible in WorkRun summary:

```python
def test_chat_turn_registers_as_work_run(client, monkeypatch):
    session = client.post("/api/sessions", json={"title": "Demo"}).json()
    response = client.post(f"/api/sessions/{session['id']}/messages", json={"content": "解释当前状态"})

    assert response.status_code == 202
    summary = client.get("/api/runtime/summary").json()
    assert summary["workRuns"]["active"]["chat_turn"]["runKind"] == "chat_turn"
```

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_web_app.py -k "chat_turn_registers_as_work_run or runtime_summary" -v
```

Expected: FAIL because chat turns are not in WorkRun summary.

**Step 3: Write minimal implementation**

In `session_service.py`:

- assign a `runId` for each turn, for example `chat_turn:{session_id}:{turn_number}`.
- persist a WorkRun snapshot when the turn is queued/running/stopping/completed/failed/stopped.
- keep `ChatSession` persistence in `chat_state`; do not move messages into WorkRun store.

In `runtime_service.py`:

- add `workRuns` to `/api/runtime/summary`.
- include active/latest by kind and current leases.

**Step 4: Run test to verify it passes**

Run:

```powershell
pytest tests/test_web_app.py -k "chat_turn_registers_as_work_run or runtime_summary or session" -v
```

Expected: PASS and existing session behavior remains unchanged.

**Step 5: Commit**

```powershell
git add core/web/services/session_service.py core/web/services/runtime_service.py tests/test_web_app.py tests/test_work_run_store.py
git commit -m "feat(chat): register turns as work runs"
```

## Task 4: Move self and supervised summaries onto WorkRun summary

**Files:**
- Modify: `core/web/services/supervised_control_service.py`
- Modify: `core/web/services/self_evolution_control_service.py`
- Modify: `core/web/services/runtime_service.py`
- Modify: `web/src/api/types.ts`
- Test: `tests/test_web_app.py`

**Step 1: Write the failing tests**

Add runtime summary tests that show all three kinds:

```python
def test_runtime_summary_exposes_three_work_run_kinds(client, monkeypatch):
    summary = client.get("/api/runtime/summary").json()
    assert "chat_turn" in summary["workRuns"]["latest"]
    assert "supervised_evolution_run" in summary["workRuns"]["latest"]
    assert "self_evolution_run" in summary["workRuns"]["latest"]
```

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_web_app.py -k "runtime_summary_exposes_three_work_run_kinds" -v
```

Expected: FAIL until runtime summary includes shared WorkRun payloads.

**Step 3: Write minimal implementation**

- Map existing manager snapshots from `self` to `self_evolution_run`.
- Map existing manager snapshots from `supervised` to `supervised_evolution_run`.
- Keep `/api/evolution/*` responses unchanged.
- Extend TypeScript runtime summary types without forcing UI changes yet.

**Step 4: Run test to verify it passes**

Run:

```powershell
pytest tests/test_web_app.py -k "runtime_summary_exposes_three_work_run_kinds or evolution or session" -v
cd web; npm test -- --run
```

Expected: PASS with API compatibility.

**Step 5: Commit**

```powershell
git add core/web/services/supervised_control_service.py core/web/services/self_evolution_control_service.py core/web/services/runtime_service.py web/src/api/types.ts tests/test_web_app.py
git commit -m "feat(runtime): expose shared work run summary"
```

## Task 5: Make chat case lifecycle explicit in the UI/API

**Files:**
- Modify: `core/web/services/chat_review_service.py`
- Modify: `core/web/routes/evolution.py`
- Modify: `web/src/routes/EvolutionRoute.tsx`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/i18n/dictionary.ts`
- Test: `tests/test_chat_dataset_capture.py`
- Test: `tests/test_web_app.py`

**Step 1: Write the failing tests**

Add tests for candidate lifecycle shape:

```python
def test_chat_review_queue_exposes_case_lifecycle(client, tmp_path, monkeypatch):
    response = client.get("/api/evolution/chat-review")
    payload = response.json()
    assert "lifecycle" in payload
    assert payload["lifecycle"]["rawChatDirectTrainingAllowed"] is False
```

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_chat_dataset_capture.py -v
pytest tests/test_web_app.py -k "chat_review" -v
```

Expected: FAIL until lifecycle metadata is exposed.

**Step 3: Write minimal implementation**

Expose metadata:

- candidate counts by status: `pending`, `positive`, `negative`, `discard`.
- dataset target: `chat_reviewed_multiturn`.
- negative target: `chat_negative_multiturn`.
- raw direct training guard: `false`.
- allowed downstream uses: `supervised_evaluation`, `gym_candidate_case`, `future_training_export`.

Update Web copy so the review surface says:

- pending candidates are not training data.
- positive reviewed cases can become supervised/Gym cases.
- negative cases are counterexamples.

**Step 4: Run test to verify it passes**

Run:

```powershell
pytest tests/test_chat_dataset_capture.py -v
pytest tests/test_web_app.py -k "chat_review" -v
cd web; npm run build
```

Expected: PASS with clearer lifecycle surface.

**Step 5: Commit**

```powershell
git add core/web/services/chat_review_service.py core/web/routes/evolution.py web/src/routes/EvolutionRoute.tsx web/src/api/types.ts web/src/i18n/dictionary.ts tests/test_chat_dataset_capture.py tests/test_web_app.py
git commit -m "feat(evolution): expose chat case lifecycle"
```

## Task 6: Connect reviewed chat cases to supervised run selection

**Files:**
- Modify: `core/evaluation/dataset_registry.py`
- Modify: `core/web/services/supervised_control_service.py`
- Modify: `core/web/services/evolution_service.py`
- Modify: `web/src/routes/EvolutionRoute.tsx`
- Test: `tests/test_dataset_registry.py`
- Test: `tests/test_web_app.py`

**Step 1: Write the failing tests**

Add tests that `chat_reviewed_multiturn` appears as an explicit supervised dataset with boundary metadata:

```python
def test_chat_reviewed_dataset_reports_review_boundary(tmp_path):
    rows = list_dataset_status(tmp_path)
    row = next(item for item in rows if item["name"] == "chat_reviewed_multiturn")
    assert row["review_required"] is True
    assert "supervised_evaluation" in row["allowed_downstream_uses"]
```

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_dataset_registry.py -k "chat_reviewed_dataset" -v
pytest tests/test_web_app.py -k "evolution_workbench or dataset" -v
```

Expected: FAIL until dataset status carries downstream metadata.

**Step 3: Write minimal implementation**

- Add optional dataset metadata: `review_required`, `source_track`, `allowed_downstream_uses`, `holdout_allowed`.
- Mark `chat_reviewed_multiturn` as reviewed-only, non-holdout by default.
- Show the dataset in supervised workbench with a concise boundary label.

**Step 4: Run test to verify it passes**

Run:

```powershell
pytest tests/test_dataset_registry.py -k "chat_reviewed or generated_cases" -v
pytest tests/test_web_app.py -k "evolution_workbench or dataset" -v
```

Expected: PASS and users can choose reviewed chat cases without confusing them with frozen holdout data.

**Step 5: Commit**

```powershell
git add core/evaluation/dataset_registry.py core/web/services/supervised_control_service.py core/web/services/evolution_service.py web/src/routes/EvolutionRoute.tsx tests/test_dataset_registry.py tests/test_web_app.py
git commit -m "feat(supervised): surface reviewed chat datasets"
```

## Task 7: Add front-end WorkRun synchronization hooks

**Files:**
- Modify: `web/src/api/queryKeys.ts`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/routes/ChatCodingRoute.tsx`
- Modify: `web/src/routes/EvolutionRoute.tsx`
- Test: `web/src/api/client.test.ts`
- Test: `tests/test_web_app.py`

**Step 1: Write the failing tests**

Add TypeScript tests for query keys:

```ts
expect(queryKeys.workRuns()).toEqual(["runtime", "work-runs"]);
expect(queryKeys.workRun("chat_turn")).toEqual(["runtime", "work-runs", "chat_turn"]);
```

**Step 2: Run test to verify it fails**

Run:

```powershell
cd web; npm test -- --run client
```

Expected: FAIL until query keys exist.

**Step 3: Write minimal implementation**

- Add `workRuns` and `workRun(kind)` query keys.
- Keep existing `sessions` and `evolution` query keys.
- On chat/evolution SSE events, invalidate `runtimeSummary` and `workRuns`.
- Do not change major layout in this task.

**Step 4: Run test to verify it passes**

Run:

```powershell
cd web; npm test -- --run client
cd web; npm run build
pytest tests/test_web_app.py -k "session or evolution" -v
```

Expected: PASS with no UI regression.

**Step 5: Commit**

```powershell
git add web/src/api/queryKeys.ts web/src/api/types.ts web/src/routes/ChatCodingRoute.tsx web/src/routes/EvolutionRoute.tsx web/src/api/client.test.ts tests/test_web_app.py
git commit -m "feat(web): sync work run query state"
```

## Task 8: Final targeted validation

**Files:**
- Test: `tests/test_work_run_store.py`
- Test: `tests/test_work_run_leases.py`
- Test: `tests/test_chat_dataset_capture.py`
- Test: `tests/test_dataset_registry.py`
- Test: `tests/test_web_app.py`
- Test: `tests/test_self_evolution_control_service.py`
- Test: `tests/test_supervised_workbench.py`

**Step 1: Run runtime substrate suite**

Run:

```powershell
pytest tests/test_work_run_store.py tests/test_work_run_leases.py tests/test_web_app.py -k "work_run or runtime_summary or session or evolution" -v
```

Expected: PASS.

**Step 2: Run chat case loop suite**

Run:

```powershell
pytest tests/test_chat_dataset_capture.py tests/test_dataset_registry.py -k "chat_reviewed or generated_cases or review" -v
```

Expected: PASS.

**Step 3: Run existing domain regressions**

Run:

```powershell
pytest tests/test_self_evolution_control_service.py tests/test_supervised_workbench.py -v
pytest tests/test_web_app.py -k "session or self_evolution or supervised or chat_review" -v
cd web; npm run build
```

Expected: PASS.

**Step 4: Update project memory**

Run:

```powershell
python C:\Users\17533\.codex\skills\dawn-agent-html-memory\scripts\sync_project_memory.py C:\Users\17533\Desktop\Vibelution --lane "agent-runtime-core" --focus "WorkRun substrate and chat case loop" --update "Shared WorkRun substrate plan and chat case lifecycle are now the cross-track architecture reference."
python C:\Users\17533\.codex\skills\dawn-agent-html-memory\scripts\render_overview.py C:\Users\17533\Desktop\Vibelution
```

Expected: project memory pages mention the WorkRun substrate and chat case loop.

**Step 5: Commit**

```powershell
git add .docs/project-memory docs/plans PROJECT_MEMORY.html
git commit -m "docs: define work run substrate rollout"
```

## Rollout Order

Recommended sequence:

1. Task 1: store compatibility first.
2. Task 2: resource leases.
3. Task 3: chat turn registration.
4. Task 4: self/supervised summary alignment.
5. Task 5 and 6: chat case lifecycle and supervised selection.
6. Task 7: front-end sync.
7. Task 8: validation and memory.

Do not run Task 5/6 before Task 1/2 if the same engineer is also changing runtime summary. Case lifecycle can be developed in parallel only if it avoids touching `runtime_service.py`, `queryKeys.ts`, and shared API types until Task 4/7 land.

## Definition Of Done

- All three tracks expose WorkRun state through one runtime summary.
- Existing chat, supervised, and self-evolution endpoints remain compatible.
- Chat turns can be observed as WorkRuns without turning ChatSession into a run.
- Resource leases, not global active lock, decide allowed overlap.
- Reviewed chat cases can enter supervised/Gym datasets; raw chat cannot.
- Project memory and all three development guides point to this shared plan.
