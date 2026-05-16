# Vibelution — 自我进化 AI Agent 系统

> **版本：** v7.0 | **日期：** 2026-05-11（文档已与仓库同步）

基于 LangChain ReAct 架构的自我进化 AI Agent。能够通过网络搜索获取新知识、读取和修改自身源代码、进行语法自检、并通过独立守护进程实现自我重启。

---

## 核心特性

```
┌─────────────────────────────────────────────────────────────────┐
│                     Vibelution 自我进化系统                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  🧠 三层记忆系统                                                 │
│     短期记忆：会话中的工具调用和思考过程                           │
│     中期记忆：世代内的任务、洞察、代码理解                         │
│     长期记忆：跨世代的核心智慧和能力画像                           │
│                                                                  │
│  🎭 双轨提示词架构                                               │
│     静态层：core/core_prompt/ (只读内置)                        │
│     动态层：workspace/prompts/ (Agent 运行时可编辑)              │
│                                                                  │
│  🔄 自我重启机制                                                 │
│     Agent 可通过 trigger_self_restart 触发进程级重启，            │
│     由 restarter.py 守护进程拉起新 Agent 实例                     │
│                                                                  │
│  📋 TaskManager 任务追踪                                         │
│     基于 tasks.json 的任务状态管理，支持创建/更新/查询            │
│                                                                  │
│  🏗️ Core First 架构                                              │
│     agent.py 约 1400+ 行（入口 + 主循环；体积随演进变化）          │
│     业务逻辑主要在 core/ 各模块                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 项目架构

```
Vibelution/                     # 项目根目录
├── agent.py                     # Agent 主入口（约 1400+ 行，见仓库实际文件）
│                                 # 职责：启动、主循环、LLM/工具协议与编排黏合
├── config.toml                  # 配置文件 (TOML格式)
│
├── config/                      # 配置模块
│   ├── __init__.py           # 统一配置入口
│   ├── models.py              # Pydantic 数据模型
│   ├── providers.py           # LLM 模型预设注册表
│   └── settings.py            # 配置加载与单例管理
│
├── core/                        # 核心模块（8 个顶层子目录）
│   │
│   ├── infrastructure/         # 基础设施（节选；完整列表见仓库）
│   │   ├── tool_executor.py    # 工具执行器 (超时/重试/并行)
│   │   ├── state.py           # 状态管理 (单例/线程安全)
│   │   ├── event_bus.py       # 事件总线 (发布订阅/通配符)
│   │   ├── security.py        # 安全验证 (白名单+路径约束)
│   │   ├── model_discovery.py  # 动态模型发现
│   │   ├── workspace_manager.py # SQLite 工作区管理
│   │   ├── tool_result.py     # 工具结果处理
│   │   ├── agent_session.py   # Session 状态管理
│   │   ├── llm_utils.py       # LLM 消息解析、错误分类等
│   │   ├── cli_utils.py       # CLI 参数解析等
│   │   ├── git_memory.py      # Git 信号与记忆辅助
│   │   ├── mental_model.py    # 心理模型 / 上下文摘要
│   │   ├── test_gate.py       # 进化相关测试门
│   │   └── ...                # reading_strategy, workspace_cleaner, tool_recommender 等
│   │
│   ├── orchestration/          # 任务与回合编排
│   │   ├── task_planner.py     # 智能任务规划 (TaskManager)
│   │   ├── delegation_governor.py
│   │   ├── response_processor.py
│   │   ├── round_state.py
│   │   └── ...                # turn_outcome, tool_lifecycle, response_surface 等
│   │
│   ├── prompt_manager/         # 提示词管理
│   │   ├── prompt_manager.py  # 动态提示词管理器
│   │   ├── builder.py         # 提示词构建
│   │   ├── sections.py / types.py / section_cache.py
│   │   ├── task_analyzer.py   # 任务分析器
│   │   └── codebase_map_builder.py # 代码库地图
│   │
│   ├── core_prompt/           # 核心提示词 (静态只读)
│   │   ├── SOUL.md           # 使命铁律
│   │   └── SPEC.md          # 开发流程规范
│   │
│   ├── logging/               # 日志系统
│   │   ├── logger.py         # 调试日志
│   │   ├── unified_logger.py # 统一日志
│   │   ├── transcript_logger.py # 对话转录
│   │   ├── tool_tracker.py   # 工具追踪
│   │   └── setup.py          # 日志配置
│   │
│   ├── ui/                    # 用户界面
│   │   ├── ascii_art.py      # ASCII Art 形象系统
│   │   ├── cli_ui.py         # CLI UI 组件
│   │   ├── workbench.py      # 工作台 Shell
│   │   ├── interactive_cli.py # 交互式 CLI
│   │   ├── token_display.py  # Token 显示
│   │   └── theme.py          # 主题系统
│   │
│   ├── pet_system/            # 宠物系统
│   │   ├── pet_system.py     # 核心类
│   │   └── models.py         # 数据模型
│   │
│   └── restarter_manager/     # 重启守护
│       └── restarter.py       # 进程接力重启
│
├── tools/                       # 工具集
│   ├── Key_Tools.py           # 工具注册 (14个 LLM 可见工具)
│   ├── shell_tools.py         # Shell 工具
│   ├── memory_tools.py        # 记忆与任务工具
│   ├── code_analysis_tools.py # 代码分析工具 (AST/Diff)
│   ├── rebirth_tools.py       # 重启/休眠工具
│   ├── search_tools.py        # Grep 搜索工具
│   ├── web_search_tool.py     # 网络搜索工具
│   └── token_manager.py       # Token 管理
│
├── workspace/                   # 工作区
│   ├── memory/               # 记忆存储
│   │   └── archives/        # 世代档案
│   ├── prompts/              # 动态提示词
│   │   ├── IDENTITY.md      # 身份定义
│   │   ├── USER.md          # 用户信息
│   │   ├── DYNAMIC.md       # 动态提示词
│   │   └── STATE_MEMORY.md  # 状态记忆
│   ├── skills/              # Skill 拓展目录
│   └── logs/                # 运行日志
│
├── tests/                      # 测试套件（40+ 个 test_*.py，pytest 收集逾 1200 条）
│   ├── conftest.py           # pytest 配置与共享 fixtures
│   └── test_*.py            # 各模块测试
│
└── docs/                      # 设计与规划（如 docs/plans/）
```

---

## Core First 架构

agent.py 遵循 Core First 原则，仅负责：
- 运行循环 (`run_loop`)
- 思考-行动循环 (`think_and_act`)
- LLM 调用和工具执行

所有业务逻辑迁移到 `core/` 对应模块：

| agent.py 原逻辑 | 迁移到 core/ |
|----------------|-------------|
| 状态管理 | `core/infrastructure/state.py` |
| 事件总线 | `core/infrastructure/event_bus.py` |
| 安全验证 | `core/infrastructure/security.py` |
| 工具执行 | `core/infrastructure/tool_executor.py` |
| 工作区管理 | `core/infrastructure/workspace_manager.py` |
| 提示词管理 | `core/prompt_manager/prompt_manager.py` |
| 任务规划 | `core/orchestration/task_planner.py` |
| 委托与回合控制 | `core/orchestration/delegation_governor.py` 等 |

---

## 快速开始

### 1. 安装依赖

建议使用 **Python 3.11–3.12** 虚拟环境（当前部分 LangChain 依赖在 **Python 3.14+** 下可能触发 Pydantic V1 兼容性告警；功能或可运行，但生产环境宜锁定受支持版本）。

```bash
pip install -r requirements.txt
```

### 2. 配置 (`config.toml` + 环境变量)

```toml
[llm.providers.remote_main]
kind = "minimax"
api_key = ""
api_key_env = "MINIMAX_API_KEY"
base_url = "https://api.minimaxi.com/v1"
compat_mode = "openai"
requires_api_key = true

[llm.profiles.primary]
provider_id = "remote_main"
model = "MiniMax-M2.7"
temperature = 0.2
max_output_tokens = 4096
timeout = 120
connect_timeout = 20
streaming = true

[llm.role_bindings]
primary = "primary"

[agent]
name = "SelfEvolvingAgent"
awake_interval = 60
max_iterations = 100
```

推荐做法：

```powershell
$env:MINIMAX_API_KEY="your-api-key"
```

如果你使用本地模型：

```toml
[llm.providers.local_main]
kind = "local"
api_key = ""
api_key_env = ""
base_url = "http://localhost:8000/v1"
compat_mode = "openai"
requires_api_key = false
context_window = 65536

[llm.profiles.primary]
provider_id = "local_main"
model = "qwen-32b-awq"
temperature = 0.2
max_output_tokens = 4096
timeout = 45
connect_timeout = 5
streaming = true

[llm.role_bindings]
primary = "primary"
```

项目提供了一个可复制的示例文件：`config.example.toml`。

推荐同时启用稳定运行档案：

```toml
[runtime]
profile = "safe_remote"
preflight_doctor = true
require_venv = true
```

可用档案：
- `safe_local`: 本地模型优先，关闭动态发现，收紧超时和迭代次数
- `safe_remote`: 远程模型优先，保留自检和压缩
- `debug`: 打开调试追踪
- `ci`: 面向自动化验证，关闭高波动特性

### 3. 运行

```bash
# 自动模式
python agent.py --auto

# 指定稳定运行档案
python agent.py --profile safe_local --auto

# 指定任务
python agent.py --prompt "读取并分析 agent.py 的结构"

# 进化测试
python agent.py --test

# 交互模式
python agent.py
```

---

## Agent 工具 (14个 LLM 可见)

| 类别 | 工具 | 功能 |
|------|------|------|
| **核心** | `commit_compressed_memory_tool` | 重启前压缩存盘记忆 |
| **世代** | `set_generation_task_tool` | 设置当前世代任务 |
| | `trigger_self_restart_tool` | 触发自我重启 |
| **代码** | `grep_search_tool` | 全局正则搜索 |
| | `apply_diff_edit_tool` | Diff 块精准编辑 |
| | `validate_diff_format_tool` | 验证 Diff 格式 |
| | `list_file_entities_tool` | AST 列出文件实体 |
| | `get_code_entity_tool` | AST 提取特定实体 |
| **搜索** | `web_search_tool` | 网络搜索 |
| **文件** | `cli_tool` | 万能 Shell 命令 |
| **休眠** | `enter_hibernation_tool` | 主动休眠 |
| **任务** | `task_create_tool` | 创建任务清单 |
| | `task_update_tool` | 更新任务状态 |
| | `task_list_tool` | 查询任务进度 |

---

## 双轨提示词架构

```
core/core_prompt/              ← 静态核心提示词（只读模板）
├── SOUL.md                   ← 使命铁律（禁止修改）
└── SPEC.md                   ← 开发流程规范（禁止修改）

workspace/prompts/            ← 动态提示词（Agent 运行时可编辑）
├── IDENTITY.md               ✅ 可修改
├── USER.md                   ✅ 可修改
├── DYNAMIC.md                ✅ 必须修改
└── STATE_MEMORY.md           ✅ 状态记忆持久化
```

**PromptManager 特性：**
- 双轨加载：workspace 优先，回退 static
- 优先级组件拼装：SOUL(10) → DYNAMIC(40) → SPEC(65) → MEMORY(80)
- 状态记忆持久化

---

## 三层记忆架构

```
短期记忆 (会话)          中期记忆 (世代)          长期记忆 (跨世代)
├── session_id           ├── generation            ├── current_generation
├── task_list            ├── current_task          ├── total_generations
├── tool_calls           ├── task_plan             ├── core_wisdom
├── thoughts             ├── completed_tasks       ├── skills_profile
└── user_inputs          ├── insights              ├── evolution_history
                         └── tool_stats            └── archive_index
```

---

## 自我重启机制

```
Agent 进程                    Restarter 进程
  └── think_and_act()
      └── trigger_self_restart()
          └── spawn restarter.py
              └── sys.exit(0)
                                  └── wait_for_process_death(pid)
                                  └── spawn_new_process(agent.py)
```

---

## 开发指南

### 运行测试

`config.toml` 中 `require_venv = true` 时，应用项目虚拟环境解释器运行测试（否则 `tests/test_environment_smoke.py` 会校验失败）。

```powershell
# Windows：推荐显式使用 .venv
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

```bash
# 运行所有测试（已激活 venv 时）
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_tool_executor.py -v

# 提示词打靶测试
python tests/prompt_debugger.py
```

### 质量门控

每次修改后执行：

```bash
python -m py_compile <修改的文件>.py
pytest tests/<相关测试>.py -v -x
git diff --stat
```

---

## 文档索引

| 文档 | 路径 | 用途 |
|------|------|------|
| 代码库地图 | `workspace/prompts/CODEBASE_MAP.md` | 自动生成的项目结构地图 |
| 开发规范 | `CLAUDE.md` | Claude Code 协作文档 |
| 核心使命 | `core/core_prompt/SOUL.md` | Agent 身份与铁律 |
| 操作规范 | `core/core_prompt/SPEC.md` | Agent 开发流程规范 |

---

## 最近变更

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v7.0 | 2026-05-11 | 文档同步：修正 agent.py 体量与目录树、测试说明与 Python 版本提示 |
| v7.0 | 2026-05-01 | 大清理：移除 ~4000 行死代码、删除 tool_registry.py、精简 14 个 LLM 工具 |
| v6.0 | 2026-04-19 | Core First 架构、agent.py 精简52%、新增 5 个 Core 模块 |
| v5.1 | 2026-04-19 | Core First 架构升级 |
| v5.0 | 2026-04-18 | 提示词自主动态拼装 |
| v4.0 | 2026-04-17 | 全面重构：SPEC、Phase 8、Token 优化 |

---

## License

MIT
