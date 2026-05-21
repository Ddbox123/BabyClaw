# 对话开发指导文档

## 定位

对话线负责把 Vibelution 做成一个稳定、连续、可观察的 agent 对话工作台。它的核心目标不是“多一个聊天页面”，而是让用户能在同一个会话里持续给任务、看 agent 思考、看工具调用、停止/继续运行、恢复历史上下文，并把有价值的对话经验交给监督或无监督进化线使用。

这条线覆盖 Web Chat、终端工作台、会话持久化、实时运行状态、心智状态展示、消息清洗和文件上下文。

## 当前事实

- Web Chat 已接通真实 `/api/sessions` 和 `/api/sessions/{id}/messages`。
- 对话消息支持四段式展示：思考、心智模型、工具调用、回答。
- 后端 live payload 已拆分 `thought`、`content`、`mentalSnapshot`、`toolCalls`。
- 停止请求、stopping 状态、历史恢复、active task 续跑、max continuation 都已经有实现和测试。
- 右侧会话面板已有新建和删除会话能力。
- 非 assistant 消息已有正文渲染修复。
- 对话线现在同时牵涉 Web 前端、FastAPI session service、agent runtime 和终端工作台。

## 职责边界

对话线负责：

- 用户消息提交、会话创建、删除、切换、恢复。
- assistant 回复的可见内容、思考、工具调用、心智模型分段展示。
- 运行中状态、停止、继续、busy 锁、错误可见性。
- 会话历史与当前 task goal 的连续性。
- 文件上下文在对话工作台中的阅读和引用。
- 把人工审核过的对话片段提供给数据集或监督线。

对话线不负责：

- 判定某个候选是否应该晋升为 baseline。
- 自进化事务的 apply/rollback 语义。
- Gym proposal 的生命周期。
- LLM provider/profile 的配置治理。
- Reset、Config、Pet Space 的深度功能，只能保持入口一致。

## 共享底座边界

对话线必须遵守横向计划：[WorkRun Substrate And Chat Case Loop Implementation Plan](./2026-05-21-workrun-substrate-and-chat-case-loop.md)。

统一边界：

- `ChatSession` 是持久对话容器，不是 WorkRun。
- `ChatTurn` 是一次用户请求触发的执行单元，应该登记为 `WorkRun(chat_turn)`。
- 对话线不能自己定义一套全局 active run，也不能用 Chat running 状态阻断所有进化；是否并行由 `ResourceLease` 判断。
- raw chat transcript 不能直接进入训练或监督评测。
- 对话经验必须走 `Chat Segment -> Dataset Candidate -> Review -> Reviewed Chat Case -> Dataset/Bundle`，才能交给监督进化或 Gym。

对话线向共享底座提供：

- `chat_turn` 的 queued/running/stopping/completed/failed/stopped 快照。
- 当前 turn 的 resource leases，例如 `readonly_chat` 或 `worktree_write`。
- 可审核的 chat case candidate，不提供未审核训练样本。

## 关键文件

后端：

- `core/web/routes/sessions.py`
- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `core/web/services/runtime_scene_service.py`
- `core/web/app.py`
- `core/chat/chat_session_manager.py`
- `core/ui/chat_state.py`
- `core/ui/workbench.py`
- `core/ui/cli_ui.py`
- `core/orchestration/agent_modes.py`

前端：

- `web/src/routes/ChatCodingRoute.tsx`
- `web/src/routes/ChatCodingRoute.module.css`
- `web/src/components/conversation/ConversationView.tsx`
- `web/src/components/conversation/ConversationView.module.css`
- `web/src/api/client.ts`
- `web/src/api/types.ts`
- `web/src/store/chatWorkbenchStore.ts`
- `web/src/i18n/dictionary.ts`

测试：

- `tests/test_web_app.py`
- `tests/test_workbench.py`
- `tests/test_cli_ui.py`
- `tests/test_conversation_logger.py`
- `web/src/api/client.test.ts`

## 开发原则

1. 会话连续性优先于 UI 表现。
   如果历史恢复、active task、mental snapshot、read files 任一丢失，先修数据链，不先调样式。

2. 可见内容必须清洗协议残片。
   `state`、`invoke`、`parameter`、DSML 残片、半截标签不能进入回答区或 active task 摘要。

3. 停止必须是真停止。
   Web stop 不能只写一个 UI 状态；必须传递到当前 turn control 和子进程等待循环。

4. 对话页只展示对话该展示的东西。
   不要把 Git、Config、Evolution、Reset 的深层控制面塞回 Chat 主区域；它们应留在顶栏或对应页面。

5. 多轮推进要有上限。
   `max_continuation_turns` 的目的不是削弱能力，而是避免同一用户消息无限自转。

## 优先任务

### 任务 1：稳定会话恢复

目标：刷新页面、重启服务、打开旧会话后，用户能看到同一条 active task、最近消息、文件上下文和心智状态。

重点检查：

- `SessionService` 是否从 chat state 恢复最近消息。
- `MentalModel` seed 是否包含历史摘要。
- `readFiles`、`previewTabs`、`activePreviewPath` 是否只在用户明确打开文件时恢复。
- stale running/stopping 会话是否能给出可见恢复提示。

建议测试：

```powershell
pytest tests/test_web_app.py -k "session or continuation or mental or stop" -v
```

### 任务 2：稳定运行中视图

目标：运行中时，用户能看懂 agent 在做什么，而不是只看到 loading 或半截协议文本。

重点检查：

- live payload 的 `thought/content/toolCalls/mentalSnapshot` 分流。
- `ConversationView` 的四段式折叠逻辑。
- SSE 或轮询刷新不会覆盖用户输入草稿。
- 回到底部按钮和滚动锁定是否稳定。

建议测试：

```powershell
pytest tests/test_web_app.py -k "live or events or toolCalls or visible" -v
cd web; npm test -- --run client
```

### 任务 3：稳定停止和继续

目标：用户点停止后，后台不会继续跑；用户发送“继续”后，能接上上一轮任务目标。

重点检查：

- `SessionTurnControl` 与 result stop flag 必须同时参与可见停止提示。
- 子 agent 进程树必须能被取消。
- `recent_blockers` 不应被子 agent 空结果污染。
- 继续时应保留上一 active task goal，而不是把“继续”本身当成目标。

建议测试：

```powershell
pytest tests/test_web_app.py -k "stop or continue or blocker or subagent" -v
```

### 任务 4：把对话经验交给进化线

目标：人工审核过的多轮对话片段能进入 `chat_reviewed_multiturn` 候选数据集，但不能直接污染冻结验收集。

重点检查：

- `core/web/services/chat_review_service.py`
- `tests/test_chat_dataset_capture.py`
- `core/evaluation/dataset_registry.py`

要求：

- 每条片段必须有来源会话、review 状态和采样边界。
- 未审核片段不能被当成监督正样本。
- 对话线只提供候选数据，不决定 PROMOTE。

## 与监督进化线的接口

对话线向监督线提供：

- 人工审核过的多轮对话样本。
- 用户最终接受的 assistant 回复版本。
- 工具调用轨迹与任务完成结果。

对话线不能直接修改：

- `workspace/supervised_evolution/decisions`
- `workspace/supervised_evolution/policy`
- `core/evaluation/selection_policy.py`

## 与无监督进化线的接口

对话线向无监督线提供：

- 当前会话目标。
- 最近失败/停止/恢复证据。
- 用户对 agent 行为的纠正。
- 可作为自我诊断输入的 runtime scene 日志。

对话线不能直接做：

- 自进化事务开账或关账。
- 自进化历史删除。
- 自进化运行的 start/pause/resume/stop 控制语义。

## 验收清单

- 用户能创建、删除、切换会话。
- 旧会话恢复后，不丢最近消息和任务目标。
- assistant 消息不显示协议残片。
- 工具调用跟随消息显示，不串到别轮。
- stop 后后台真正停止。
- continue 后接续上一任务，而不是开始无意义新任务。
- Web 和终端的对话语义不互相冲突。

## 推荐验证

```powershell
pytest tests/test_web_app.py -k "session or message or stop or continuation or mental or tool" -v
pytest tests/test_workbench.py -k "chat or tool" -v
pytest tests/test_cli_ui.py -v
cd web; npm test -- --run client
cd web; npm run build
```

## 提交说明

对话线提交建议使用：

- `fix(chat): ...`
- `feat(chat): ...`
- `refactor(chat): ...`
- `test(chat): ...`

每次提交只覆盖一个行为目标。不要把 Evolution、Config、Reset 的无关改动混进对话线提交。
