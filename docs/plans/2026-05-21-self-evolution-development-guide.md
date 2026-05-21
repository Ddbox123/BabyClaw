# 无监督进化开发指导文档

## 定位

无监督进化线负责让 Vibelution 在没有人类逐步评价每个候选的情况下，进行一轮受控、自证据驱动、自我约束的改进尝试。

它不是自由改写系统，也不是监督进化的替代品。它的职责是读取当前目标、工作区现场、最近事务、监督建议和运行证据，决定是否启动一轮 bounded self-evolution，并在运行后留下可诊断、可回滚、可删除的事务证据。

## 当前事实

- Web 自进化页已有 start 按钮、运行状态、历史组、批量删除和 stale run 解锁逻辑。
- `self_evolution_control_service` 已能处理 stale queued/paused/running 快照。
- 自进化启动会检查 active supervised run，避免和监督运行冲突。
- 自进化历史删除以 txnIds 为唯一入口，审计尾迹同步清理。
- 预览和 run prompt 已包含目标、建议基线、工作区快照、最近事务和 fitness。
- 这条线仍以 helper/control/service 层为主，不应随意改共享 workbench 入口。

## 职责边界

无监督进化线负责：

- 自进化 run 的 start、pause、resume、stop、stale unlock。
- 启动前现场摘要：goal、worktree、recent transactions、fitness、advisory baseline。
- 自进化事务历史和 audit 证据。
- 自进化运行与监督 active run 的互斥。
- 自进化结果的可诊断性、可回滚性、可删除性。
- 运行失败或停止后的用户可见恢复说明。

无监督进化线不负责：

- 监督决策的 PROMOTE/HOLD/ROLLBACK 判定。
- 对话消息展示、工具调用卡片、聊天停止按钮 UI。
- LLM provider/profile 的配置安全。
- 直接修改冻结评测集或监督 policy。
- 绕过 risky write transaction gate。

## 关键文件

核心服务：

- `core/evaluation/self_evolution_workbench.py`
- `core/web/services/self_evolution_control_service.py`
- `core/web/routes/evolution.py`
- `core/runtime_manager/evolution_store.py`
- `core/runtime_manager/daemon.py`

共享治理：

- `core/infrastructure/evolution_governor.py`
- `core/infrastructure/git_memory.py`
- `core/infrastructure/tool_executor.py`
- `core/gym/advisory.py`

前端：

- `web/src/routes/EvolutionRoute.tsx`
- `web/src/routes/EvolutionRoute.module.css`
- `web/src/api/client.ts`
- `web/src/api/types.ts`
- `web/src/store/shellStore.ts`
- `web/src/i18n/dictionary.ts`

工件：

- `workspace/evolution/audit.jsonl`
- `workspace/evolution/proposals`
- `workspace/gym/proposals`
- `workspace/supervised_evolution/policy`
- `.runtime`，如当前 runtime manager 使用该目录

测试：

- `tests/test_self_evolution_control_service.py`
- `tests/test_web_app.py`
- `tests/test_runtime_manager.py`
- `tests/test_evolution_governor.py`
- `tests/test_git_memory.py`
- `tests/test_tool_executor.py`

## 开发原则

1. 先看现场，再决定是否开跑。
   如果 worktree 已脏、监督运行 active、stale run 未收口、最近事务失败，先解释和收口，不直接开新 run。

2. 自进化必须 bounded。
   每轮要有目标、预算、停止条件、事务边界和可见结果。

3. 自进化不能自改评判标准。
   可以参考 active advisory baseline，但不能直接改写监督 policy 或冻结验收逻辑。

4. 高风险写入必须走事务。
   `core/`、`tools/`、`config/`、`workspace/prompts/` 等路径必须由 risky write gate 保护。

5. 失败也是证据。
   失败 run 要写清楚原因、阶段、工具、路径、是否可恢复，而不是只留一个 failed 状态。

## 优先任务

### 任务 1：稳定启动前现场检查

目标：用户点开始前，能看清楚这一轮是否适合启动。

重点检查：

- active supervised run 是否阻止 self-evolution start。
- stale queued/paused/running 是否能自动收口或给出解释。
- worktree snapshot 是否展示 dirty files、branch、recent transactions。
- advisory baseline 是否明确标注“参考，不是开关”。

建议测试：

```powershell
pytest tests/test_self_evolution_control_service.py -k "start or stale or supervised" -v
pytest tests/test_web_app.py -k "self_evolution or active_supervised" -v
```

### 任务 2：稳定运行控制

目标：start/pause/resume/stop 不互相污染，停止不会留下假 active 状态。

重点检查：

- runtime manager store 是否隔离测试和真实 `.runtime`。
- queued/paused/running/stopping 之间的状态迁移。
- stop 后 worker 是否真正停止。
- 重新加载页面时是否修复缺内存 worker 的持久化状态。

建议测试：

```powershell
pytest tests/test_self_evolution_control_service.py -v
pytest tests/test_runtime_manager.py -k "evolution or daemon" -v
```

### 任务 3：稳定事务历史

目标：自进化运行产生的事务和 audit 可以被用户理解、删除、回看。

重点检查：

- 删除入口是否只接受 txnIds。
- 删除 history 时，相关 audit jsonl 也同步清理。
- active/running/stopping 事务是否禁止删除。
- UI 是否把事务组、审计尾迹、运行状态对应起来。

建议测试：

```powershell
pytest tests/test_web_app.py -k "self_evolution.*delete or history" -v
pytest tests/test_self_evolution_control_service.py -k "history or delete" -v
```

### 任务 4：稳定自改边界

目标：无监督 agent 的修改不会绕过阶段 2 的事务治理。

重点检查：

- `open_evolution_transaction_tool` 是否在 risky write 前显式调用。
- `close_evolution_transaction_tool` 是否清理 active txn。
- `GitMemoryService.note_file_modified()` 是否只追踪 dirty state，不写后自动开账。
- cli 写入目标是否能被 `EvolutionGovernor` 解析。

建议测试：

```powershell
pytest tests/test_tool_executor.py -k "evolution or risky or transaction" -v
pytest tests/test_evolution_governor.py -v
pytest tests/test_git_memory.py -k "evolution or transaction" -v
```

### 任务 5：把开放探索变成候选增量

目标：无监督进化可以发现新策略、新 case、新工具习惯，但只进入候选池，不直接污染核心标准。

重点检查：

- generated cases 是否有 provenance。
- 运行失败是否能变成诊断 case。
- 自进化成功经验是否只作为 proposal 或 dataset candidate。
- 是否仍要回到监督线进行验收。

建议测试：

```powershell
pytest tests/test_dataset_registry.py -k "generated_cases" -v
pytest tests/test_gym_collections.py -v
```

## 与对话线的接口

无监督线可以读取：

- 用户当前目标。
- 最近对话上下文摘要。
- stop/continue 失败证据。
- runtime scene 和 conversation log。

无监督线不能修改：

- Chat 消息结构。
- ConversationView 展示规则。
- 用户对话历史的原文内容。
- 对话线的 stop/continue UI 语义。

## 与监督进化线的接口

无监督线可以读取：

- active advisory baseline 摘要。
- 最近 supervised decision。
- proposal lifecycle 状态。
- 是否存在 active supervised run。

无监督线不能直接修改：

- `workspace/supervised_evolution/decisions`
- `workspace/supervised_evolution/policy`
- `core/evaluation/selection_policy.py`
- accepted baseline registry

任何自进化产出的“更好策略”都必须回到监督线验收，不能自己宣布生效。

## 验收清单

- 有 active supervised run 时，self-evolution start 被拒绝。
- stale self-evolution run 能收口或解释。
- start/pause/resume/stop 状态稳定。
- 历史删除以 txnId 为唯一入口。
- risky write 必须显式开账。
- 失败 run 有可读原因。
- 成功经验只进入候选增量，不直接改写标准。

## 推荐验证

```powershell
pytest tests/test_self_evolution_control_service.py -v
pytest tests/test_runtime_manager.py -k "evolution or daemon" -v
pytest tests/test_web_app.py -k "self_evolution or active_supervised" -v
pytest tests/test_tool_executor.py -k "evolution or risky or transaction" -v
pytest tests/test_evolution_governor.py -v
pytest tests/test_git_memory.py -k "evolution or transaction" -v
```

## 提交说明

无监督进化线提交建议使用：

- `feat(self-evolution): ...`
- `fix(self-evolution): ...`
- `refactor(self-evolution): ...`
- `test(self-evolution): ...`

不要把监督 selection policy、Chat UI、Config security 的无关改动混进无监督提交。
