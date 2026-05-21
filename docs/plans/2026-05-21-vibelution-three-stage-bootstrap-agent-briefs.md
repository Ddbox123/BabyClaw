# Vibelution 三阶段自递归自举 Agent Briefs

> 这份文档接续 `2026-05-19-vibelution-evolution-loop-hardening.md`，把原先 5 个加固任务重新切成 3 个可交给不同 agent 的开发包。

## 背景模型

当前讨论采用“约束递归自举模型”（CRBM）视角：

- 阶段 0/1：用人类监督和冻结规则，把外部判断蒸馏进 `V_ref` 与 `K_t`。
- 阶段 2：在受控修改空间内进行自我迭代，让系统能提出、评估、回滚和沉淀局部改进。
- 阶段 3：扩大环境开放度，用真实运行、聊天、gym、生成数据等外部经验产生候选增量，再回到冻结验收面。

旧计划里的 dataset registry、risky write gate、observing budget 已经在当前仓库出现实现痕迹；新的分工不要求 agent 重做已完成内容，而是要求先核对当前代码和测试，再补齐各阶段仍缺的闭环。

## 总体约束

- 三个 agent 必须在各自分支开发，不在 `main` 上堆改动。
- 三个 agent 都不能使用 `git add .`，只能暂存自己负责的文件。
- 三个 agent 都必须先跑自己范围内的 targeted tests，再决定是否扩大验证。
- 涉及运行时行为、状态迁移、晋升/回滚、权限边界的改动，先走 BRT checkpoint。
- 共享热点文件只做必要最小改动：`config.toml`、`tests/test_web_app.py`、`agent.py`、`core/web/app.py`、Web 路由服务文件。
- 项目记忆要在每个阶段收尾时同步到对应 lane。

## Agent A：阶段 0/1，监督自举与冻结验收面

**目标**

把“人类监督判断”变成可回放、可比较、可迁移的事实源，让系统知道什么修改能进入下一轮，什么只能观察、拒绝或回滚。

**模型角色**

- 负责 `V_ref`：参考评估器、监督决策记录、历史可回放证据。
- 负责 `K_t` 的一部分：监督流程中哪些路径、数据、决策结构不能漂移。
- 不负责无监督运行调度，也不负责 Web 视觉体验。

**主要文件边界**

- `core/evaluation/dataset_registry.py`
- `core/evaluation/supervised_evolution.py`
- `core/evaluation/supervised_dashboard.py`
- `core/evaluation/supervised_workbench.py`
- `core/evaluation/selection_policy.py`
- `core/evaluation/lineage.py`
- `core/evaluation/supervised_artifacts.py`，如仍不存在则新建
- `tests/test_dataset_registry.py`
- `tests/test_supervised_evolution.py`
- `tests/test_supervised_dashboard.py`
- `tests/test_supervised_workbench.py`
- 必要时小范围触碰 `tests/test_web_app.py`

**接手前先核对**

1. `generated_cases` 与 `chat_reviewed_multiturn` 是否已在 registry backfill 和 workspace bootstrap 中稳定可见。
2. `workspace/supervised_evolution/decisions/` 与 `workspace/supervised_evolution/policy/` 是否已有统一读取入口。
3. `HOLD` 后的 observing proposal 是否已经有预算、过期和终态。
4. dashboard/workbench 是否能读取历史漂移工件，而不是只认新格式。

**可交付任务**

1. 若 `supervised_artifacts.py` 已存在，补齐 dashboard/workbench/evolution 的统一读取；若不存在，先建立最小共享 iterator。
2. 把 policy-only、decision-only、双文件互链三种历史形态都纳入测试。
3. 明确 `HOLD -> observing -> expired/rejected` 的状态机，并让 lineage 不把过期 proposal 当作仍在观察。
4. 在监督运行记录中保留足够证据：dataset、candidate、policy action、decision path、proposal path、baseline link。

**验收命令**

```powershell
pytest tests/test_dataset_registry.py -v
pytest tests/test_supervised_evolution.py -k "observation or decision or artifact or registry" -v
pytest tests/test_supervised_dashboard.py -v
pytest tests/test_supervised_workbench.py -v
```

**完成标准**

- 监督进化记录可以从一个稳定 API/iterator 回放。
- 新旧 workspace 工件不会因为目录漂移而在 UI 或 workbench 中消失。
- 观察态有明确终点，不再无限停留。
- 项目记忆更新 `evolution-control-plane` lane。

## Agent B：阶段 2，受控自我迭代与修改闸门

**目标**

让 agent 可以安全地自改，但所有高风险修改必须在写入前被事务、白名单和回滚证据约束住。

**模型角色**

- 负责 `K_t`：演化事务、risky mutation 前置阻断、写入边界、回滚证据。
- 负责降低 `R_t`：减少写后补账、隐式修改、事务残留和日志不可诊断性。
- 不负责监督评测策略本身，也不负责开放探索数据生成。

**主要文件边界**

- `core/infrastructure/evolution_governor.py`
- `core/infrastructure/tool_executor.py`
- `core/infrastructure/git_memory.py`
- `core/orchestration/agent_modes.py`，仅当提示/模式约束必须同步时触碰
- `core/gym/coordination.py`，仅当 gym case 需要同步工具约束时触碰
- `tests/test_tool_executor.py`
- `tests/test_evolution_governor.py`
- `tests/test_git_memory.py`
- `tests/test_evolution_harness.py`
- `tests/test_gym_collections.py`

**接手前先核对**

1. `ToolExecutor` 是否已经在工具真正运行前调用 evolution governor。
2. `GitMemoryService.note_file_modified()` 是否已停止为 risky path 自动补开事务。
3. `cli_tool`、PowerShell 写文件、Python `open(..., "w")`、`Path.write_text()`、重定向写入是否都能提取目标路径。
4. 开账/关账工具是否正确设置和清理 session active txn。

**可交付任务**

1. 把 risky write gate 的测试扩到所有真实写入入口，而不只是 `write_file_tool`。
2. 确认无 active txn 时，高风险路径在工具运行前失败，且不会执行被注册工具。
3. 确认有 active txn 时，仍受 allowed dirs 和事务路径约束。
4. 确认事务 close 后 active txn 必须清空，后续 risky write 重新需要显式开账。
5. 补日志，让下一轮从 `logs/` 能看出被拦截的 tool、目标路径、拦截原因。

**验收命令**

```powershell
pytest tests/test_tool_executor.py -k "evolution or risky or transaction" -v
pytest tests/test_evolution_governor.py -v
pytest tests/test_git_memory.py -k "evolution or transaction" -v
pytest tests/test_evolution_harness.py -k "transaction or forbidden" -v
```

**完成标准**

- risky mutation 不再依赖写后补记账。
- 每次高风险写入都有明确的事务前置条件。
- 失败路径有可诊断日志。
- 项目记忆更新 `agent-runtime-core` 或 `quality-and-operations` lane。

## Agent C：阶段 3，开放探索与经验回灌

**目标**

把更开放环境中的真实经验变成候选数据和候选策略，但不直接污染核心验收标准。探索只产生假设，进入核心仍需通过阶段 0/1 的冻结验收面和阶段 2 的事务闸门。

**模型角色**

- 负责 `O_t`：开放度、外部经验、聊天审核样本、generated cases、gym case 扩展。
- 负责提升 `A_t` 的候选输入：更多任务分布、更真实失败模式、更多可复现 case。
- 不负责直接改写 `V_ref`，不绕过 `K_t`。

**主要文件边界**

- `core/gym/generated_cases.py`
- `core/gym/intelligence.py`
- `core/gym/local.py`
- `core/web/services/chat_review_service.py`
- `core/evaluation/dataset_registry.py`，只在数据源状态展示需要时小改
- `core/evaluation/bundles/*.json`
- `tests/test_chat_dataset_capture.py`
- `tests/test_vibelution_gym_adapter.py`
- `tests/test_gym_collections.py`
- `tests/test_dataset_registry.py`
- 必要时小范围触碰 Web 展示测试

**接手前先核对**

1. `chat_reviewed_multiturn.jsonl` 是否能从人工审核的聊天样本追加记录。
2. `generated_cases.jsonl` 是否要求 provenance，是否阻止 holdout 污染。
3. dataset materialization 是否能把新样本变成可运行 bundle。
4. Gym 生成的 case 是否仍遵守 forbidden tools 和事务要求。

**可交付任务**

1. 明确 `chat_reviewed_multiturn` 的正样本/负样本/修改后样本结构。
2. 明确 `generated_cases` 的 provenance、source run、review state、holdout 标记。
3. 给 dataset status 增加“可作为探索样本 / 可作为训练候选 / 可作为冻结验收”的边界提示。
4. 确认开放探索产生的数据只进入候选池，不直接改 baseline、`V_ref` 或核心 prompt。

**验收命令**

```powershell
pytest tests/test_chat_dataset_capture.py -v
pytest tests/test_dataset_registry.py -k "generated_cases or chat_reviewed" -v
pytest tests/test_vibelution_gym_adapter.py -v
pytest tests/test_gym_collections.py -v
```

**完成标准**

- 开放探索数据有来源、有审核状态、有污染边界。
- 生成样本能进入候选数据集，但不能绕过监督验收。
- Gym/聊天数据回灌路径可解释、可测试、可回滚。
- 项目记忆更新 `self-evolution-loop` 或 `evolution-control-plane` lane。

## 三个 Agent 的集成顺序

推荐顺序：

1. Agent B 先收紧写入闸门，因为它保护后续所有自改。
2. Agent A 再统一监督事实源，因为它决定哪些改动能进入 baseline。
3. Agent C 最后扩大探索数据面，避免把未治理的数据提前灌进核心。

如果必须并行：

- Agent A 和 Agent C 不要同时修改 `core/evaluation/dataset_registry.py`。
- Agent A 和 Agent B 不要同时修改 `tests/test_web_app.py`。
- Agent B 修改工具治理时，Agent C 只能读 gym forbidden tools 契约，等 B 合并后再补测试。

## 汇总验证

三阶段合并后至少跑：

```powershell
pytest tests/test_dataset_registry.py tests/test_chat_dataset_capture.py tests/test_gym_collections.py -v
pytest tests/test_tool_executor.py tests/test_evolution_governor.py tests/test_git_memory.py -v
pytest tests/test_supervised_evolution.py tests/test_supervised_dashboard.py tests/test_supervised_workbench.py -v
pytest tests/test_web_app.py -k "dataset_list or self_evolution_routes_expose_read_only_evidence" -v
```

最终判断不是“测试全绿”就结束，而是看三件事是否同时成立：

- 外部监督事实源稳定。
- 自我修改前置受控。
- 开放探索只能产生候选增量，不能直接改写真理标准。
