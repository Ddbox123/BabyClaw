# 监督进化开发指导文档

## 定位

监督进化线负责回答一个核心问题：某次候选修改是否真的比当前 baseline 更值得保留。

这条线不是自动发布系统，也不是直接改写 runtime 的开关。它的职责是运行可回放评测、生成决策记录、维护 proposal 生命周期，并把 PROMOTE、HOLD、ROLLBACK 这些结论解释清楚。

## 当前事实

- 监督进化已有 CLI 与 Web 两条入口。
- Web `/evolution` 已能启动监督运行、观察 active run、订阅 SSE，并执行 proposal action。
- `supervised_dry_run` bundle 已包含事务开账/关账探针。
- HOLD 后 observing proposal 已有默认观察预算，超预算后进入 expired 终态。
- active advisory baseline 仍然只是建议基线，不等于 runtime 已经改写。
- 当前记忆显示，历史监督记录多数仍停在 HOLD，说明候选与 baseline 的差异信号还不够强。

## 职责边界

监督进化线负责：

- dataset/bundle 选择与 materialization。
- baseline 与 candidate 的同条件比较。
- case 结果、gate、reason、score 的记录。
- Decision Record 的写入和回放。
- proposal 的 proposed/applied/active/rolled_back/superseded 生命周期。
- dashboard/workbench/Web 的监督数据读取。
- 观察预算、过期、拒绝、回滚的策略。

监督进化线不负责：

- 用户对话体验。
- Web Chat 的消息展示和停止语义。
- 自进化运行队列。
- 直接改写 runtime prompt、代码或模型配置。
- 自动把 PROMOTE 变成线上生效。

## 关键文件

核心评测：

- `core/evaluation/supervised_evolution.py`
- `core/evaluation/supervised_cli.py`
- `core/evaluation/dataset_registry.py`
- `core/evaluation/bundles/supervised_evolution_dry_run_v1.json`

策略与生命周期：

- `core/evaluation/selection_policy.py`
- `core/evaluation/lineage.py`
- `core/gym/promotion.py`
- `core/gym/advisory.py`
- `core/gym/README.md`

工作台与 Web：

- `core/evaluation/supervised_workbench.py`
- `core/evaluation/supervised_dashboard.py`
- `core/web/services/supervised_control_service.py`
- `core/web/services/evolution_service.py`
- `core/web/routes/evolution.py`
- `web/src/routes/EvolutionRoute.tsx`
- `web/src/api/types.ts`
- `web/src/i18n/dictionary.ts`

工件：

- `workspace/supervised_evolution/decisions`
- `workspace/supervised_evolution/policy`
- `workspace/supervised_evolution/dashboard`
- `workspace/supervised_evolution/workbench_state.json`
- `workspace/gym/proposals`
- `workspace/gym/decisions`

测试：

- `tests/test_supervised_evolution.py`
- `tests/test_supervised_workbench.py`
- `tests/test_supervised_dashboard.py`
- `tests/test_dataset_registry.py`
- `tests/test_web_app.py`
- `tests/test_workbench.py`

## 开发原则

1. 决策必须可回放。
   每次监督运行都要能从记录恢复出为什么 PROMOTE、HOLD 或 ROLLBACK。

2. PROMOTE 不等于生效。
   文案、API 字段和 dashboard 都必须区分 supervised decision、advisory baseline 和 runtime effect。

3. baseline 与 candidate 必须同条件比较。
   同一 bundle、同一 dataset limit、同一事务规则、同一禁止工具边界。

4. HOLD 必须有出口。
   observing 不能无限堆积，必须有预算、过期、终态和 lineage 表达。

5. Web 和 CLI 必须共享域逻辑。
   不允许 Web 另写一套监督决策或 proposal action 语义。

## 优先任务

### 任务 1：增强差异信号

目标：减少“baseline 和 candidate 看起来差不多”的 HOLD 堆积。

可做方向：

- 设计更能暴露行为差异的 case。
- 把 trace-driven diagnosis 纳入 candidate 对比。
- 增强每个 case 的 failure reason。
- 对工具序列、事务开关、停止语义给出更细粒度评分。

建议测试：

```powershell
pytest tests/test_supervised_evolution.py -k "case or score or decision" -v
pytest tests/test_dataset_registry.py -v
```

### 任务 2：统一监督事实源

目标：无论记录来自 `decisions/`、`policy/` 还是 gym proposal，都能被 dashboard、workbench 和 Web 稳定读取。

重点检查：

- 是否需要引入或补齐 `core/evaluation/supervised_artifacts.py`。
- policy-only 历史记录是否能回放。
- decision 记录里是否包含 proposal path、policy action、runtime effect。

建议测试：

```powershell
pytest tests/test_supervised_dashboard.py -v
pytest tests/test_supervised_workbench.py -v
pytest tests/test_web_app.py -k "evolution_routes_use_real_supervised_records or supervised_run" -v
```

### 任务 3：收紧 proposal action 语义

目标：apply、activate、rollback、delete 都有清晰前置条件和用户可见解释。

重点检查：

- active run 存在时 proposal action 是否锁定。
- active proposal 是否禁止删除。
- missing/proposed/applied/active/rolled_back 的按钮状态是否合理。
- Web 和 CLI 文案是否都说明 runtime effect。

建议测试：

```powershell
pytest tests/test_web_app.py -k "supervised_run_action or proposal or delete" -v
pytest tests/test_supervised_workbench.py -k "promotion or lifecycle" -v
```

### 任务 4：稳定监督运行控制

目标：Web 启动、暂停、恢复、停止监督运行时，状态不会卡死或污染下一轮。

重点检查：

- 单 active run 锁。
- SSE event tail。
- pause/resume/terminate 结果。
- dataset limit 是否只写入独立 bundle，不污染默认 dry-run bundle。
- open/close evolution transaction 是否显式完成。

建议测试：

```powershell
pytest tests/test_web_app.py -k "start_supervised_run or active_supervised or pause_resume" -v
pytest tests/test_dataset_registry.py -k "supervised_bundle" -v
```

## 与对话线的接口

监督线可以读取：

- `chat_reviewed_multiturn` 这类经人工审核的对话数据集。
- 对话线提供的最终用户接受样本。
- 工具调用和任务结果作为 case 元数据。

监督线不能要求对话线：

- 直接把未审核聊天历史变成评测集。
- 为了监督评测改变 Chat 的消息展示结构。
- 在对话页展示 PROMOTE 等同于 runtime 生效。

## 与无监督进化线的接口

监督线向无监督线提供：

- active advisory baseline 摘要。
- 最近 decision 结果。
- proposal lifecycle 状态。
- 当前是否有 active supervised run。

监督线不应允许：

- 无监督线在 active supervised run 期间启动冲突运行。
- 无监督线绕过 proposal action 直接改 policy 工件。
- 无监督线把 HOLD/OBSERVE 当成可直接应用的改进。

## 验收清单

- 每次监督运行都有 decision record。
- dashboard/workbench/Web 都读同一套事实。
- PROMOTE、applied、active、runtime effect 清楚分层。
- observing proposal 有预算和终态。
- active run 期间动作锁定。
- proposal action 的结果可回放、可撤销。
- dataset limit 不污染默认 bundle。

## 推荐验证

```powershell
pytest tests/test_dataset_registry.py -v
pytest tests/test_supervised_evolution.py -v
pytest tests/test_supervised_workbench.py -v
pytest tests/test_supervised_dashboard.py -v
pytest tests/test_web_app.py -k "evolution or supervised" -v
```

## 提交说明

监督进化线提交建议使用：

- `feat(supervised): ...`
- `fix(supervised): ...`
- `refactor(supervised): ...`
- `test(supervised): ...`

不要把 Chat UI、Self Evolution run control、Config security 的改动混进监督提交。
