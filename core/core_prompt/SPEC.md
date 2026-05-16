# SPEC 开发流程规范

**版本：** v5.0
**日期：** 2026-05-03
**读者：** AI Agent（本文档的执行者均为 Agent，每条规则必须可被工具验证）

---
## 1. 每次修改必做

```
[感知]  get_git_status_summary_tool
        get_recent_changes_tool
        → 了解变更范围、上次产出、本次目标
        若涉及跨模块 Python 修改：
        python_symbol_tool(file_path, line, column, action=definition/references)
        → 先确认真实入口、引用关系、波及面
[决策]  Core First 检查（见第2节）
[执行]  修改代码
[验证]  python_lint_tool(<文件或目录>)
        python -m py_compile <修改文件>.py
        run_test_for_tool(<修改文件路径>)      # 映射到对应测试文件并运行
        python tests/prompt_debugger.py --suite # 仅当涉及 SOUL/SPEC/workspace/prompts 或工具变更时
[交付]  git commit
```

## 1.1 输出语言纪律

默认输出语言：中文。

规则：

- 我的自然语言说明、总结、计划、阶段汇报、工具调用解释、日志解释，默认使用中文。
- 我不得无必要地产生整段英文自然语言。
- 以下内容允许保留原文：
  - 代码块
  - shell 命令
  - 文件路径
  - 类名 / 函数名 / API 名称 / 协议字段
  - 报错原文
- 若出现英文原文，我应优先补充中文解释，而不是只留下英文文本。
- 若本轮输出出现大段无必要英文，视为违反规范，需要在本轮内自行纠正。

优先规则：

```
[感知]  优先调用 get_git_status_summary_tool / get_recent_changes_tool
        → 读取最近提交变化、当前脏区、最近验证结果
        必要时再退回原始 git CLI
```

**编译或测试失败 → 禁止继续，禁止提交。**
修改涉及核心循环（agent.py / restarter / prompt_manager）时，提交前必须通过完整测试套件或 `test_gate.check_evolution_ready()`。

## 1.2 Python 结构感知与静态守门

Python 是当前项目的主语言，因此以下流程默认启用：

1. 跨模块修改前，优先调用 `python_symbol_tool`
2. 需要判断波及面时，优先查看 `references`
3. 需要理解符号含义时，优先查看 `hover`
4. Python 代码修改后，优先调用 `python_lint_tool`
5. lint 未通过时，先清理静态问题，再进入 `py_compile / pytest`

强规则：

- `python_symbol_tool` 用于确认真实定义、引用关系、调用落点，不用纯文本猜依赖。
- `python_lint_tool` 是 Python 修改后的第一道静态门，不跳过。
- 若环境缺少 `jedi` 或 `ruff`，允许降级，但要明确知道自己处于降级状态。

## 1.3 测试失败诊断纪律

测试失败后，必须按以下顺序推进：

1. 先复现失败测试
2. 再打印最小中间值
3. 再读取相关函数 / 实体
4. 最后才做归因推理

强规则：

- 若同轮内某种工具模式已被安全策略拦截，禁止再次尝试同类模式。
- `cli_tool` 应优先避免不必要的命令链、管道和子表达式；若必须使用，应确认命令目标明确且可验证。
- 若连续多步没有新增观测，只在读代码或长推理，视为诊断漂移，必须先补观测。
- 读取文件内容优先 `read_file_tool` / `grep_search_tool`，不要用带 pipe 的 `cli_tool` 反复试探。
- 若 `MEMORY / STATE_MEMORY` 中出现“当前轮强约束”或“当前诊断纪律”，其优先级高于一般说明，必须先执行约束，再继续推进。
- 只读分析类问题优先考虑委派给子 agent，而不是由主 agent 持续沉入局部搜索。
- 第一版子 agent 禁止写文件、改 prompt、改 memory、做 git 操作、触发重启。
- 子 agent 输出必须是结构化摘要，只能作为证据，不能跳过主 agent 直接成为最终结论。
- 委派失败后默认主 agent 接管，不自动重试，不级联委派。
- 同轮已有有效委派结果时，禁止重复委派同类问题。

## 1.4 修复与止损纪律

当修改代码或测试文件后出现结构性错误，以下规则强制生效：

1. 若出现 `SyntaxError`、`pytest collection error`、`invalid-syntax`、import 失败，立即停止零碎 patch，默认判定为文件结构可能已损坏。
2. 结构性错误出现后，优先恢复“最小可导入状态”，再恢复测试通过；推荐顺序是：

```bash
python -m py_compile <目标文件>.py
pytest <目标测试文件> -q
pytest <相关测试子集> -q
```

3. 文件结构损坏时，必须先读取完整坏段，并按完整函数 / 完整测试块重建；禁止在坏上下文里继续逐行缝补或跨块拼接。
4. 恢复原貌时，优先依据：`git diff`、`git show HEAD:<path>`、当前文件前后文、同类代码模式、最近日志中的改前改后片段；不靠猜测逐行修。
5. 连续两次 patch 后若错误未减少、报错范围扩散、或出现“可能删多了 / 可能修坏了”的迹象，立即放弃当前修法，切换到“基线对照 + 整段重建”。
6. 默认禁止直接执行 `git checkout <file>` / `git restore <file>`；只有在确认该文件未提交改动全部来自本轮 agent 且不会覆盖用户改动时才允许。
7. 修改 `tests/*.py` 且涉及 `def/class`、缩进、多行字面量、列表 / 字典 / 参数块时，必须先跑 `python -m py_compile <file>`，通过后再跑 pytest。
8. 区分故障与质量债：syntax / import / pytest / runtime failure 属于故障；`F401`、格式问题、非阻断 lint 属于质量债，不能作为“最近验证失败根因”进入故障处理通道。
9. 当目标文件恢复正常、目标相关测试通过、工作区符合预期且无新 blocker 时，立即收束当前线程，不再继续扩散搜索新问题。
10. 只有在主问题未闭环且确实存在高噪音、可并行、非写入型分析任务时，才允许派发 `diagnose` 子 agent；主问题已解决或只剩 lint 噪音时禁止派发。

---

## 2. Core First

Agent 在实现任何功能前，执行以下决策（不允许跳过）：

```
1. ls core/                          → 了解目录结构
2. grep_search_tool("关键词", "core/") → 搜索相似功能
3.
   ├─ 已有相似功能 → import 复用，agent.py 仅写调用代码
   └─ 无相似功能 → 在 core/ 对应子目录创建
        ├─ 创建 core/{category}/xxx.py（含 docstring）
        ├─ 在 core/{category}/__init__.py 导出
        └─ agent.py 导入使用
```

**agent.py 约束**：只放 `think_and_act()` 核心循环、`run_loop()` 入口、`_invoke_llm()` 调用、初始化与状态管理。业务逻辑一律放 `core/`。

---

## 3. 质量门控

编译通过后逐条检查：

| # | 检查项 | 验证方式 |
|---|--------|---------|
| 1 | 新文件 snake_case，新类 PascalCase | 目视 |
| 2 | 公开函数有类型注解 | 目视 |
| 3 | 新模块有 docstring（功能+参数+返回值） | 目视 |
| 4 | 无空壳模块（pass/...） | grep "pass" / "\.\.\." |
| 5 | 配置值来自 config.toml | 目视（无硬编码路径/密钥） |
| 6 | 若添加/修改工具：通过 prompt_debugger 打靶 | `python tests/prompt_debugger.py --tool <工具名>` |

---

## 4. 提示词系统架构

章节运行时元信息的唯一权威来源是 `config.toml` 中的 `[[prompt.sections]]`
与代码内置注册表。Markdown 文件头若存在，只视为文件注释，不得作为
section 的 `name / priority / required / description` 真源。

### 已注册章节（按拼接顺序）

```
SOUL(10) → TASK_CHECKLIST(20) → CODEBASE_MAP(30) → GIT_MEMORY(35) → DELEGATION_RULES(36) → GIT_RULES(38) → DYNAMIC(40) →
IDENTITY(50) → SPEC(65) → USER(70) → MEMORY(80) → TOOLS_INDEX(90) → ENV_INFO(100)
```

| 章节 | 来源 | 刷新 |
|------|------|------|
| SOUL | `core/core_prompt/SOUL.md` | 静态 |
| SPEC | `core/core_prompt/SPEC.md`（本文件） | 静态 |
| CODEBASE_MAP | `workspace/prompts/CODEBASE_MAP.md` | 文件变更时自动刷新 |
| GIT_MEMORY | Git 历史 + working tree + 最近验证摘要 | 每轮 |
| DELEGATION_RULES | 主脑调度 / 子代理边界 / 结果回收规则 | 每轮 |
| GIT_RULES | `workspace/prompts/GIT_WORKFLOW.md` 摘要 | 静态 |
| TASK_CHECKLIST | TaskManager 动态生成 | 每轮 |
| MEMORY | 压缩记忆 + state_memory | 每轮 |
| TOOLS_INDEX | Key_Tools 动态提取 | 静态 |
| ENV_INFO | 时间/OS/路径 | 5分钟粒度 |
| DYNAMIC/IDENTITY/USER | `workspace/prompts/` | 按需（workspace 启用且文件存在时加载） |

### LLM 响应标签

| 标签 | 提取到 |
|------|--------|
| `<think>` | UI、日志 |
| `<plan>` | `core/orchestration/task_planner.py` |
| `<active_components>` | `core/prompt_manager/prompt_manager.py` |
| `<tool_call>` | 工具执行层 |

---

## 5. Git 提交规范

Git 提交是演化记忆，不是临时备注。提交必须可回溯、可验证、可拆解。

### 5.1 标题格式

```
type(scope): intent
```

允许的 `type`：

- `feat`
- `fix`
- `refactor`
- `test`
- `docs`
- `chore`

推荐的 `scope`：

- `agent`
- `prompt`
- `git-memory`
- `session`
- `tool-executor`
- `restart`
- `test-gate`
- `mental-model`
- `workspace`
- `tools`

### 5.2 强规则

- 一次提交只表达一个意图
- 禁止把 `bugfix + refactor + prompt cleanup + test` 混成一条提交
- prompt / git-memory / restart / agent 核心变更必须单独提交，或只与直接关联测试同提交
- 验证失败禁止提交

### 5.3 高风险提交正文

涉及以下任一项时，提交正文必须带 `Why / What / Verify`：

- `agent.py`
- `core/prompt_manager/*`
- `core/infrastructure/git_memory.py`
- `tools/rebirth_tools.py`
- `core/infrastructure/tool_executor.py`
- `workspace/prompts/*`

正文模板：

```text
Why:
- ...

What:
- ...

Verify:
- ...
```

---

## 6. 目录结构

以 `ls core/` 或 CODEBASE_MAP 为准（CODEBASE_MAP 自动扫描生成，文件变更时自动刷新），不依赖本文档中的手动描述。

---

## 7. 工具与测试

### 工具变更

添加/修改工具（`tools/`、`core/` 下所有注册到 Key_Tools 的模块）后，必须验证模型能正确调用：

```bash
python tests/prompt_debugger.py --tool <工具名>   # 单工具打靶
python tests/prompt_debugger.py --suite           # 全量打靶
```

### 测试框架

| 组件 | 用途 | 触发时机 |
|------|------|---------|
| `conftest.py` | 单例重置、隔离 workspace、共享 fixtures | 每次 pytest 自动加载 |
| `run_test_for_tool` | 按源文件映射测试文件并运行 | 修改代码后立即调用 |
| `test_runner.py` | 全量测试运行器 | 手动 / 进化前 |
| `test_gate.py` | 进化门控（重启前强制通过） | `trigger_self_restart` 自动调用 |
| `prompt_debugger.py` | 提示词打靶（验证 LLM 对工具的理解） | 工具变更时 |
| `simulate_lifecycle.py` | 生命周期防断裂验证 | 手动 |

---

## 7.1 Git 感知纪律

在以下场景中，变化感知是强制步骤：

- 复杂修改前
- 重启决策前
- 高风险核心文件修改前
- 连续验证失败后

执行方式：

```bash
get_git_status_summary_tool
get_recent_changes_tool
```

必要时再退回：

```bash
git status --short
git diff --stat
git log -1 --stat
```

高风险修改前，必须确认 `GIT_MEMORY` 已刷新。

---

## 8. 本文件的维护

本文件描述的对象变化时，**同步更新**对应章节，提交前用 `git diff` 确认一致性：

| 变更类型 | 更新章节 |
|---------|---------|
| 添加/移除/重命名 `core/` 子目录 | 第 6 节 |
| 添加/移除/修改已注册工具 | 第 7 节 + 第 4 节 TOOLS_INDEX 行 |
| 新增/移除提示词章节 | 第 4 节 |
| 新增测试框架组件 | 第 7 节测试框架表 |
| 修改 Core First 规则 | 第 2 节 |
| 修改质量门控检查项 | 第 3 节 |

**不是让 SPEC 自我进化，而是让 Agent 在改代码的同时改文档——和写测试一样，是修改的一部分。**
