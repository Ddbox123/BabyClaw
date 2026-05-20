# Vibelution 演化闭环加固 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 激活当前休眠的数据回路，收紧 risky mutation 的前置闸门，给长期观察态 proposal 一个明确终点，并统一监督进化决策工件的读取与落盘路径。

**Architecture:** 保留现有 `self_evolution -> supervised_evolution -> gym` 三层结构，不重写主流程。改动集中在四个窄面：`dataset_registry` 负责旧 registry 迁移与本地自有数据集 bootstrap，`tool_executor/evolution_governor/git_memory` 负责把 risky write 提前到落盘前阻断，`selection_policy/lineage` 负责让 observing proposal 不再无限漂移，`supervised_*` 读写层负责把 decision/policy 工件收束成单一可回放的事实源。

**Tech Stack:** Python、Pydantic 配置模型、JSON/JSONL 工件、现有 `workspace/` 落盘约定、`pytest`、已有 `supervised_evolution`/`gym` 测试夹具。

---

## 改造目标锁定

1. 老的 `workspace/evaluation/datasets/registry.json` 进入系统后，会自动补齐缺失的内置数据集条目。
2. `generated_cases` 与 `chat_reviewed_multiturn` 这两个自有数据集不再只存在于代码默认值里，而会在当前 workspace 真正可见、可列出、可物化。
3. 对 `core/`、`tools/`、`config/`、`workspace/prompts/` 的 risky 写入，没有 active evolution txn 时必须在真正执行工具前失败。
4. observing proposal 不能无限期停留；达到观察预算或超时后，必须进入明确终态。
5. `workspace/supervised_evolution/decisions/` 与 `workspace/supervised_evolution/policy/` 的职责清晰，dashboard/workbench/history 都能稳定回放记录。

## 非目标

1. 本轮不改变 Gym v1 的 advisory-only baseline 策略。
2. 本轮不引入新的数据库或队列系统，仍然沿用 JSON/JSONL 工件。
3. 本轮不修改 runtime LLM 协议，不碰 agent 提示词的大范围重构。

## 关键设计决策

### 决策 1：旧 registry 做“按 name 补齐”，不覆写已有字段

原因：

1. 当前 `ensure_dataset_registry()` 只在文件不存在时写默认值，老 workspace 永远看不到新增内置数据集。
2. 直接覆写整个 registry 会破坏用户自定义数据集与本地手工编辑字段。
3. 以 `dataset.name` 为键做增量 merge，能最小成本把旧实例迁到新能力面。

### 决策 2：只有“仓内自有数据集”自动 bootstrap，用户数据和外部 benchmark 不自动伪造

自动创建空文件的范围仅限：

1. `workspace/evaluation/datasets/generated_cases.jsonl`
2. `workspace/evaluation/datasets/chat_reviewed_multiturn.jsonl`

不自动创建：

1. `custom_prompt_tasks.jsonl` 之外的用户自定义任务集
2. `swe_bench_*`
3. `humaneval` / `mbpp`

这样不会把“尚未准备好的 benchmark”误报为可用。

### 决策 3：risky mutation 必须显式开账，不能靠写后补记账

原因：

1. 现在的 `note_file_modified()` 会在写后补开事务，治理时序太晚。
2. 真正的保护点应该在 `ToolExecutor.execute()` 的落盘前。
3. `EvolutionGovernor` 继续负责“有 txn 时写到哪”，`ToolExecutor` 新增“没 txn 时能不能写”的前置阻断，两层职责清楚。

### 决策 4：观察态先做“可终止”，再谈“自动晋升”

原因：

1. 眼下最真实的问题是 proposal 长期 `observing`，没有明确出口。
2. 直接引入自动晋升会放大误判风险。
3. 本轮先把超时/超预算 proposal 终止为明确状态；后续再考虑是否引入 review-ready 队列。

---

### Task 1: 迁移 dataset registry 并 bootstrap 自有数据集源文件

**Files:**
- Modify: `core/evaluation/dataset_registry.py:56-190`
- Test: `tests/test_dataset_registry.py`
- Test: `tests/test_web_app.py`

**Step 1: Write the failing tests**

在 `tests/test_dataset_registry.py` 增加测试骨架：

```python
def test_ensure_dataset_registry_backfills_missing_builtin_datasets(tmp_path: Path):
    legacy_path = tmp_path / "workspace" / "evaluation" / "datasets" / "registry.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(json.dumps({
        "version": 1,
        "datasets": [{"name": "custom_prompt_jsonl", "kind": "prompt_jsonl", "bundle_name": "custom_prompt_jsonl_v1"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    ensure_dataset_registry(tmp_path)
    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    names = {item["name"] for item in payload["datasets"]}
    assert "generated_cases" in names
    assert "chat_reviewed_multiturn" in names


def test_ensure_dataset_registry_bootstraps_generated_and_chat_sources(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    assert (tmp_path / "workspace" / "evaluation" / "datasets" / "generated_cases.jsonl").exists()
    assert (tmp_path / "workspace" / "evaluation" / "datasets" / "chat_reviewed_multiturn.jsonl").exists()
```

在 `tests/test_web_app.py` 增加一个 route 级回归：

```python
def test_workbench_dataset_list_backfills_new_builtin_datasets(tmp_path, monkeypatch):
    legacy_registry = tmp_path / "workspace" / "evaluation" / "datasets" / "registry.json"
    ...
    rows = response.json()["datasets"]
    assert any(item["name"] == "generated_cases" for item in rows)
    assert any(item["name"] == "chat_reviewed_multiturn" for item in rows)
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_dataset_registry.py -k "backfills_missing_builtin_datasets or bootstraps_generated_and_chat_sources" -v
pytest tests/test_web_app.py -k "workbench_dataset_list_backfills_new_builtin_datasets" -v
```

Expected: FAIL because existing `ensure_dataset_registry()` only creates a file when missing and never backfills legacy payloads.

**Step 3: Write minimal implementation**

在 `core/evaluation/dataset_registry.py` 添加两个小 helper：

```python
def _merge_registry_payload(existing: Dict[str, Any]) -> Dict[str, Any]:
    defaults = _default_registry_payload().get("datasets") or []
    merged = list(existing.get("datasets") or [])
    existing_by_name = {str(item.get("name") or "").strip(): item for item in merged}
    for default_item in defaults:
        name = str(default_item.get("name") or "").strip()
        if name and name not in existing_by_name:
            merged.append(default_item)
    return {"version": 1, "datasets": merged}


def _bootstrap_builtin_dataset_sources(project_root: Path, specs: List[DatasetSpec]) -> None:
    bootstrap_names = {"generated_cases", "chat_reviewed_multiturn"}
    for spec in specs:
        if spec.name not in bootstrap_names or not spec.source_path:
            continue
        source = resolve_source_path(spec, project_root)
        if source and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("", encoding="utf-8")
```

并把 `ensure_dataset_registry()` 调整为：

1. 文件不存在时写默认 payload。
2. 文件存在时读取、merge、仅在内容变化时重写。
3. 无论文件是新建还是老文件，都在最后 bootstrap 自有数据集源文件。

**Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_dataset_registry.py -k "backfills_missing_builtin_datasets or bootstraps_generated_and_chat_sources" -v
pytest tests/test_web_app.py -k "workbench_dataset_list_backfills_new_builtin_datasets" -v
```

Expected: PASS with the legacy registry preserved, missing builtin datasets backfilled, and the two local JSONL files created.

**Step 5: Commit**

```bash
git add core/evaluation/dataset_registry.py tests/test_dataset_registry.py tests/test_web_app.py
git commit -m "feat: backfill builtin evaluation datasets"
```

### Task 2: 把 risky mutation 提前到落盘前阻断

**Files:**
- Modify: `core/infrastructure/evolution_governor.py:32-61`
- Modify: `core/infrastructure/tool_executor.py:320-340`
- Modify: `core/infrastructure/tool_executor.py:779-798`
- Modify: `core/infrastructure/git_memory.py:19-25`
- Modify: `core/infrastructure/git_memory.py:601-610`
- Test: `tests/test_tool_executor.py`
- Test: `tests/test_evolution_governor.py`
- Test: `tests/test_git_memory.py`

**Step 1: Write the failing tests**

在 `tests/test_tool_executor.py` 增加：

```python
def test_risky_write_without_active_txn_is_blocked_before_tool_runs(executor, monkeypatch):
    called = {"value": False}

    def fake_write(file_path, content):
        called["value"] = True
        return "should not run"

    executor.register_tool("write_file_tool", fake_write, timeout=5)
    reset_session_state()

    result, action = executor.execute("write_file_tool", {
        "file_path": "core/runtime.py",
        "content": "x",
    })

    assert action is None
    assert called["value"] is False
    assert "先调用 open_evolution_transaction_tool" in str(result)
```

在 `tests/test_git_memory.py` 把当前“写后自动补开 txn”的断言改成：

```python
def test_note_file_modified_tracks_dirty_state_without_auto_opening_risky_txn(...):
    service.note_file_modified("core/example.py")
    assert session.get_active_evolution_txn() is None
```

保留 `tests/test_evolution_governor.py` 现有“有 txn 时白名单照样生效”的测试，外加一个“无 txn 不进 whitelist 分支”的小回归。

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_tool_executor.py -k "risky_write_without_active_txn_is_blocked_before_tool_runs or active_evolution_transaction_blocks_writes_outside_allowed_dirs" -v
pytest tests/test_git_memory.py -k "auto_opening_risky_txn or evolution" -v
pytest tests/test_evolution_governor.py -v
```

Expected: FAIL because the write tool still executes and `GitMemoryService.note_file_modified()` still auto-opens a txn after the fact.

**Step 3: Write minimal implementation**

在 `core/infrastructure/evolution_governor.py` 增加一个前置检查 helper：

```python
def require_explicit_transaction(tool_name: str, tool_args: dict, active_txn_id: str | None) -> str | None:
    if active_txn_id:
        return None
    target_paths = extract_target_paths(tool_name, tool_args)
    risky = [path for path in target_paths if _is_risky_path(path)]
    if not risky:
        return None
    return "[演化治理] risky 修改前必须先调用 open_evolution_transaction_tool。"
```

然后在 `core/infrastructure/tool_executor.py` 的真正工具调用前插入：

```python
guard = get_evolution_governor().require_explicit_transaction(tool_name, tool_args, session.get_active_evolution_txn())
if guard:
    return guard, None
```

并把 `core/infrastructure/git_memory.py` 里的这段删除或改成纯 tracking：

```python
if _is_risky_evolution_path(filepath) and not session.get_active_evolution_txn():
    txn_id = self.open_evolution_transaction(...)
    session.set_active_evolution_txn(txn_id)
```

保留 `note_file_modified()` 的 dirty-path 和记忆同步，不再做写后补开账。

**Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_tool_executor.py -k "risky_write_without_active_txn_is_blocked_before_tool_runs or active_evolution_transaction_blocks_writes_outside_allowed_dirs" -v
pytest tests/test_git_memory.py -k "evolution" -v
pytest tests/test_evolution_governor.py -v
```

Expected: PASS with risky writes blocked before tool execution and whitelist behavior preserved for active transactions.

**Step 5: Commit**

```bash
git add core/infrastructure/evolution_governor.py core/infrastructure/tool_executor.py core/infrastructure/git_memory.py tests/test_tool_executor.py tests/test_evolution_governor.py tests/test_git_memory.py
git commit -m "fix: require explicit txn before risky evolution writes"
```

### Task 3: 给 observing proposal 增加观察预算和过期清扫

**Files:**
- Modify: `config/models.py:1123-1188`
- Modify: `config.toml:534-560`
- Modify: `core/evaluation/selection_policy.py:212-476`
- Modify: `core/evaluation/lineage.py:20-159`
- Test: `tests/test_supervised_evolution.py`
- Test: `tests/test_lineage.py`

**Step 1: Write the failing tests**

在 `tests/test_supervised_evolution.py` 增加：

```python
def test_hold_candidate_expires_after_observation_budget(tmp_path: Path):
    # 同一个 candidate 连续进入 HOLD，多次后不应继续 observing
    ...
    assert decision.policy_action["action"] == "REJECT"
    assert "observation budget" in decision.policy_action["summary"]
```

在 `tests/test_lineage.py` 增加：

```python
def test_refresh_lineage_marks_stale_observations_as_rejected(tmp_path: Path):
    proposal = {
        "status": "observing",
        "decision": "HOLD",
        "observation_count": 5,
        "updated_at": "2026-05-10T00:00:00Z",
    }
    ...
    index = load_lineage_index(project_root=tmp_path)
    assert index.cases[0].chain[0].status == "rejected"
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_supervised_evolution.py -k "observation_budget" -v
pytest tests/test_lineage.py -k "stale_observations" -v
```

Expected: FAIL because current `selection_policy` always appends another observing record and never converts long-lived observations to a terminal state.

**Step 3: Write minimal implementation**

先在 `config/models.py` 的 `EvolutionConfig` 增加两个简单阈值字段，并在 `config.toml` 配默认值：

```python
supervised_observation_limit: int = Field(default=3, ge=1)
supervised_observation_max_age_hours: int = Field(default=72, ge=1)
```

再在 `core/evaluation/selection_policy.py` 加两个 helper：

```python
def _observation_budget_exhausted(existing: dict, *, limit: int, max_age_hours: int, now_iso: str) -> bool:
    ...


def _expire_observing_proposal(...):
    # 写 proposal.status="rejected"
    # 追加 candidate_rejections.jsonl
    # reason = "observation budget exhausted"
```

`execute_supervised_policy()` 在 `decision.decision == "HOLD"` 分支中改成：

1. 先读取该 candidate 的既有 proposal。
2. 如果还在预算内，继续 `status="observing"`。
3. 如果超过预算或超过 age 阈值，转成 `status="rejected"`，并把该 case 计入 `rejected_cases`。

最后在 `_refresh_lineage_index()` 或一个新的 `sweep_stale_observations()` helper 里，确保“当前没被新 run 命中的旧 observing proposal”也会被清扫掉。

**Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_supervised_evolution.py -k "observation_budget" -v
pytest tests/test_lineage.py -k "stale_observations" -v
```

Expected: PASS with long-lived observing candidates moved to a terminal rejected state instead of drifting forever.

**Step 5: Commit**

```bash
git add config/models.py config.toml core/evaluation/selection_policy.py core/evaluation/lineage.py tests/test_supervised_evolution.py tests/test_lineage.py
git commit -m "feat: expire stale supervised observation proposals"
```

### Task 4: 统一 supervised decision 与 policy 工件的事实源

**Files:**
- Create: `core/evaluation/supervised_artifacts.py`
- Modify: `core/evaluation/supervised_evolution.py:856-867`
- Modify: `core/evaluation/supervised_dashboard.py:59-100`
- Modify: `core/evaluation/supervised_workbench.py:482-504`
- Test: `tests/test_supervised_evolution.py`
- Test: `tests/test_supervised_dashboard.py`
- Test: `tests/test_supervised_workbench.py`

**Step 1: Write the failing tests**

在 `tests/test_supervised_evolution.py` 增加：

```python
def test_supervised_run_writes_canonical_decision_record_and_policy_link(tmp_path: Path):
    decision = run_supervised_evolution_session(...)
    decision_path = tmp_path / "workspace" / "supervised_evolution" / "decisions" / f"{decision.session_id}.json"
    assert decision_path.exists()
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    assert payload["policy_action"]["policy_record_path"].endswith(f"{decision.session_id}.json")
```

在 `tests/test_supervised_dashboard.py` 与 `tests/test_supervised_workbench.py` 增加“只有 policy 文件、没有 decisions 文件时仍能读到记录”的兼容测试：

```python
def test_dashboard_loads_policy_fallback_when_decision_record_missing(tmp_path: Path):
    ...
    records, skipped = load_dashboard_records(project_root=tmp_path)
    assert len(records) == 1
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_supervised_evolution.py -k "canonical_decision_record" -v
pytest tests/test_supervised_dashboard.py -k "policy_fallback" -v
pytest tests/test_supervised_workbench.py -k "policy_fallback" -v
```

Expected: FAIL because dashboard/workbench currently只扫描 `workspace/supervised_evolution/decisions/`，而现有 workspace 已经出现 `policy/` 有记录、`decisions/` 缺失的漂移。

**Step 3: Write minimal implementation**

创建 `core/evaluation/supervised_artifacts.py`，集中做三件事：

```python
def decisions_dir(project_root: Path) -> Path: ...
def policy_dir(project_root: Path) -> Path: ...
def iter_supervised_records(project_root: Path, limit: int) -> list[tuple[dict, Path]]: ...
```

`iter_supervised_records()` 的规则：

1. 优先读取 `decisions/*.json`。
2. 若 `decisions/` 缺失或指定 session 缺文件，则回退读取 `policy/*.json`。
3. 对 policy-only 记录，构造最小兼容 payload，至少补齐 `session_id`、`decision`、`policy_action`、`decision_path`。

然后：

1. `core/evaluation/supervised_evolution.py` 显式保证 `decisions/` 目录存在，并在最终写盘后保留 `policy_record_path` 互链。
2. `core/evaluation/supervised_dashboard.py` 改为走共享 iterator。
3. `core/evaluation/supervised_workbench.py` 的 `list_recent_decision_records()` 改为走共享 iterator。

**Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_supervised_evolution.py -k "canonical_decision_record" -v
pytest tests/test_supervised_dashboard.py -k "policy_fallback" -v
pytest tests/test_supervised_workbench.py -k "policy_fallback" -v
```

Expected: PASS with a stable canonical decision record path and graceful fallback for historical drift.

**Step 5: Commit**

```bash
git add core/evaluation/supervised_artifacts.py core/evaluation/supervised_evolution.py core/evaluation/supervised_dashboard.py core/evaluation/supervised_workbench.py tests/test_supervised_evolution.py tests/test_supervised_dashboard.py tests/test_supervised_workbench.py
git commit -m "refactor: unify supervised evolution artifact loading"
```

### Task 5: 做一轮 targeted smoke，确认四条修复线没有互相打架

**Files:**
- Test: `tests/test_dataset_registry.py`
- Test: `tests/test_tool_executor.py`
- Test: `tests/test_git_memory.py`
- Test: `tests/test_evolution_governor.py`
- Test: `tests/test_supervised_evolution.py`
- Test: `tests/test_supervised_dashboard.py`
- Test: `tests/test_supervised_workbench.py`
- Test: `tests/test_web_app.py`

**Step 1: Run the targeted suite**

Run:

```bash
pytest \
  tests/test_dataset_registry.py \
  tests/test_tool_executor.py \
  tests/test_git_memory.py \
  tests/test_evolution_governor.py \
  tests/test_supervised_evolution.py \
  tests/test_supervised_dashboard.py \
  tests/test_supervised_workbench.py \
  -v
```

Expected: PASS.

**Step 2: Run the narrow web regression**

Run:

```bash
pytest tests/test_web_app.py -k "dataset_list or self_evolution_routes_expose_read_only_evidence" -v
```

Expected: PASS with no regression to existing read-only evidence routes.

**Step 3: Do one manual artifact sanity check**

Run:

```bash
python - <<'PY'
from pathlib import Path
from core.evaluation.dataset_registry import list_dataset_status
root = Path(".").resolve()
for row in list_dataset_status(root):
    if row["name"] in {"generated_cases", "chat_reviewed_multiturn"}:
        print(row["name"], row["source_exists"], row["bundle_exists"], row["runnable"])
PY
```

Expected: both datasets appear with `source_exists=True`.

**Step 4: Capture the output paths in the commit message or PR body**

Include:

1. the registry migration behavior
2. the new risky-write governance message
3. one example of a stale observation moving to terminal state
4. one example decision/policy artifact pair

**Step 5: Commit**

```bash
git add .
git commit -m "test: validate hardened evolution loop end to end"
```
