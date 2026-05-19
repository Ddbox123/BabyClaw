# Vibelution Web Workbench Wireframes

**Purpose:** 基于 [2026-05-18-vibelution-web-workbench-design.md](/C:/Users/17533/Desktop/Vibelution/docs/plans/2026-05-18-vibelution-web-workbench-design.md) 的已锁定行为，给出低保真页面结构图与区域职责，作为后续前端实现前的最后一层结构收口。

**Design Direction:** 使用 `frontend-design` 的思路，但当前产物仍然是低保真结构，不进入视觉细节和组件实现。气质保持：

- warm
- reliable
- high-density
- quietly professional

---

## 1. Top-Level Shell

所有主页面共享同一套顶层壳。

```text
+--------------------------------------------------------------------------------------------------+
| Vibelution | Chat / Coding | Evolution                                          [gear: Config] |
+--------------------------------------------------------------------------------------------------+
|                                                                                                  |
|                                        Active Domain Body                                         |
|                                                                                                  |
+--------------------------------------------------------------------------------------------------+
```

### Shell Rules

1. 顶部只承担工作域切换，不放次级工具入口。
2. `Config` 通过右上角齿轮进入独立页。
3. 顶层切换应稳定，不做戏剧化过场。

---

## 2. Chat / Coding Wireframe

这是默认首页，也是最高频工作面。

```text
+--------------------------------------------------------------------------------------------------+
| Vibelution | Chat / Coding | Evolution                                          [gear: Config] |
+--------------------------------------------------------------------------------------------------+
| LEFT STATUS RAIL      | CENTER WORKSPACE                                        | RIGHT PANEL    |
|-----------------------|---------------------------------------------------------|----------------|
| Agent identity        | [Agent Session] [file_a.py] [notes.md]                 | [Sessions|Files]|
| short status line     |---------------------------------------------------------|----------------|
|                       |                                                         |                |
| Current session card  | Active tab content                                      | If Sessions:   |
| - title               |                                                         | - session list |
| - task summary        | If Agent Session:                                       | - task status  |
| - phase               | - conversation stream                                   | - last updated |
|                       | - current assistant work                                |                |
| Runtime block         | - tool/result messages                                  | If Files:      |
| - mode                |                                                         | - project tree |
| - run state           | If File Preview:                                        | - changed marks|
| - model               | - read-only code/text preview                           | - open file    |
| - profile             | - changed sections visible                              |                |
|                       |                                                         |                |
| Context block         |                                                         |                |
| - context usage       |                                                         |                |
| - tool/delegation     |                                                         |                |
|                       |                                                         |                |
| Recent outcome block  |                                                         |                |
| - changed files count |                                                         |                |
| - recent action       |                                                         |                |
| - success/failure     |                                                         |                |
+--------------------------------------------------------------------------------------------------+
```

### 2.1 Left Status Rail

左栏不是导航，是长期可见的工作温度计。

#### Section order

1. `Agent identity`
2. `Current session summary`
3. `Runtime`
4. `Context/tools`
5. `Recent outcome`

#### Left rail rules

1. 显示当前会话摘要，但不承担切换。
2. 陪伴感来自 agent identity 和短状态语，不来自夸张装饰。
3. 每块信息应可快速扫读，避免大段说明文字。

### 2.2 Center Workspace

中间区是单一主焦点，采用标签式工作区。

#### Allowed tab types

1. `Agent Session`
2. `Read-only File Preview`

#### Behavior

1. `Agent Session` 标签长期存在。
2. 从右栏文件树打开文件时：
   - 若未打开，新增预览标签
   - 若已打开，聚焦已有标签
3. 文件预览只读，不提供人工编辑。
4. 若 AI 修改了已打开文件，该预览内容刷新，但不抢当前焦点。
5. 文件预览集合按会话隔离。

### 2.3 Right Utility Panel

右栏只做上下文和管理，不抢工作中心。

#### Toggle model

```text
[ Sessions ] [ Files ]
```

一次只显示一个面板。

#### Sessions mode

```text
+----------------------------+
| Sessions                   |
|----------------------------|
| Session A      running     |
| task summary               |
| last active time           |
|----------------------------|
| Session B      waiting     |
| task summary               |
| ...                        |
+----------------------------+
```

#### Files mode

```text
+----------------------------+
| Files                      |
|----------------------------|
| project/                   |
|   core/                    |
|     agent.py      *changed |
|     prompt.py              |
|   docs/                    |
|   tests/                   |
+----------------------------+
```

### 2.4 Chat / Coding Interaction Notes

#### Opening a file

```text
Files panel -> select file -> center opens read-only preview tab
```

#### Switching a session

```text
Sessions panel -> choose session ->
- center Agent Session restored
- that session's preview tabs restored
- left rail updates to this session
```

#### AI changes files

```text
AI acts -> files updated in workspace ->
- conversation explains what changed
- changed marks appear in file tree
- open preview tabs refresh if affected
- center focus stays where user already is
```

---

## 3. Evolution Wireframe

`Evolution` 是服务进化的工作域，不是聊天历史页。

### 3.1 Evolution Shell

```text
+--------------------------------------------------------------------------------------------------+
| Vibelution | Chat / Coding | Evolution                                          [gear: Config] |
+--------------------------------------------------------------------------------------------------+
| Evolution | Overview | Runs | Library                                                     |
+--------------------------------------------------------------------------------------------------+
|                                                                                                  |
|                                    Evolution Active Subview                                      |
|                                                                                                  |
+--------------------------------------------------------------------------------------------------+
```

### 3.2 Evolution Overview

默认入口是混合总览。

```text
+--------------------------------------------------------------------------------------------------+
| Evolution | Overview | Runs | Library                                         [Intake: Auto v]|
+--------------------------------------------------------------------------------------------------+
| Current evolution status                     | Recent library additions                           |
|----------------------------------------------|----------------------------------------------------|
| - now running / idle                         | - item A                                           |
| - current stage                              | - item B                                           |
| - last result                                | - pending candidate count                          |
|                                              |                                                    |
| Recent run performance trend                 | Quick links                                        |
|----------------------------------------------|----------------------------------------------------|
| - last N runs                                | [open latest run] [open candidates] [switch mode] |
| - score / compare / regressions              |                                                    |
+--------------------------------------------------------------------------------------------------+
```

#### Overview rules

1. 首先回答“现在整体情况如何”。
2. 其次回答“最近变好了还是变差了”。
3. 再回答“沉淀了什么内容”。
4. `Intake mode` 切换在这里可快捷改，但它不是独立业务系统。

### 3.3 Runs

```text
+--------------------------------------------------------------------------------------------------+
| Evolution | Overview | Runs | Library                                                     |
+--------------------------------------------------------------------------------------------------+
| Filters / sort / status                                                                      |
+--------------------------------------------------------------------------------------------------+
| Run list                              | Run detail                                              |
|---------------------------------------|---------------------------------------------------------|
| Run 143   success   score 81          | summary                                                 |
| Run 142   failed    score 43          | diagnosis                                               |
| Run 141   success   score 77          | changed assets                                          |
| ...                                   | candidate outputs                                       |
+--------------------------------------------------------------------------------------------------+
```

#### Runs rules

1. 左侧列表，右侧细节。
2. 重点展示结果、评分、失败原因、沉淀候选。
3. 不把 Runs 做成纯日志墙。

### 3.4 Library

```text
+--------------------------------------------------------------------------------------------------+
| Evolution | Overview | Runs | Library                                                     |
+--------------------------------------------------------------------------------------------------+
| [Library Items] [Pending Review]                                                              |
+--------------------------------------------------------------------------------------------------+
| Item list                             | Item detail                                             |
|---------------------------------------|---------------------------------------------------------|
| Prompt pattern A      auto-ingested   | source run                                              |
| Case fragment B       manual-approved | why reusable                                            |
| Candidate C           pending         | status / notes                                          |
| ...                                   | approve / reject if pending                            |
+--------------------------------------------------------------------------------------------------+
```

#### Library rules

1. 明确区分正式条目和待确认候选。
2. 条目必须带来源信息。
3. 自动入库与人工确认的来源语义不能混淆。

---

## 4. Config Wireframe

`Config` 是独立页，不和主工作台挤在一起。

```text
+--------------------------------------------------------------------------------------------------+
| Vibelution | Config                                                                  [back/work]|
+--------------------------------------------------------------------------------------------------+
| Section navigation        | Config main content                                                |
|---------------------------|--------------------------------------------------------------------|
| Runtime                   | cards / grouped settings                                            |
| Models                    |                                                                    |
| Evolution                 | intake mode, thresholds, policies                                  |
| Appearance                |                                                                    |
| Diagnostics               | validation / save / apply                                           |
+--------------------------------------------------------------------------------------------------+
```

### Config rules

1. `Evolution intake mode` 在这里是完整配置项，不只是快捷切换。
2. 配置页语义是系统设置页，不承担主工作流输出。
3. 从工作台进入配置页后，应能稳定返回原工作域。

---

## 5. Visual Brief For Later Frontend Design

这个部分给后续真正进入 `$frontend-design` 实现时使用。

### 5.1 Emotional target

用户打开页面时应感到：

1. 这是一个能长期待着的工作台
2. 系统是活的，但不吵
3. agent 在陪我干活，而不是表演

### 5.2 Composition target

1. 三栏布局稳定、克制
2. 左栏更像仪表与陪伴条，不像导航树
3. 中间区必须最有分量
4. 右栏像安静的上下文抽屉

### 5.3 Aesthetic notes

1. 深色基底
2. 暖色点亮
3. 柔和边界
4. 细腻层次，不做赛博炫光
5. 字体避免通用 AI 套路

---

## 6. Acceptance Sketches

### 6.1 Chat / Coding

1. 打开应用默认进入 `Chat / Coding`
2. 左栏显示当前会话摘要和运行状态
3. 右栏能在 `Sessions / Files` 间切换
4. 点文件树可在中间打开只读预览标签
5. 切会话后恢复该会话自己的预览标签集合

### 6.2 Agent Change Visibility

1. AI 改文件后不抢主焦点
2. 文件树显示变更标记
3. 已打开预览刷新到最新内容
4. 会话消息有改动说明

### 6.3 Evolution

1. 进入 `Evolution` 默认落到 `Overview`
2. `Overview` 显示当前状态、近期表现、最近沉淀
3. `Runs` 能看单次运行细节
4. `Library` 能区分正式条目与待确认候选
5. `Overview` 与 `Config` 的 intake mode 切换严格同步

---

## 7. Next Step

在这份低保真结构图之后，下一步应进入：

1. 视觉方向板
2. 页面层级细化
3. 前端技术栈与实现骨架

除非需求目标再次变化，否则不应再回退到信息架构争论。
