# Vibelution 项目索引

**版本：** v7.0
**日期：** 2026-05-11
**用途：** AI Agent 执行任务的执行参数（结构说明已与仓库同步）

---

## 项目结构

```
Vibelution/
├── agent.py                    # Agent 主程序（约 1400+ 行，随演进变化）
├── reset.py                    # 一键初始化脚本
├── config.toml                 # TOML 配置文件
├── core/                       # 核心模块（按功能分类）
│   ├── infrastructure/         # 基础设施
│   │   ├── agent_session.py    # Session 状态管理
│   │   ├── background_tasks.py # 后台任务管理
│   │   ├── cli_utils.py        # CLI 辅助工具
│   │   ├── cron_scheduler.py   # Cron 调度系统
│   │   ├── event_bus.py        # 事件总线
│   │   ├── git_memory.py       # Git 信号与记忆辅助
│   │   ├── llm_utils.py        # LLM 辅助工具
│   │   ├── mental_model.py     # 心理模型
│   │   ├── model_discovery.py   # 模型动态发现
│   │   ├── reading_strategy.py # 阅读策略
│   │   ├── security.py         # 安全模块
│   │   ├── state.py            # 状态管理
│   │   ├── test_gate.py        # 进化测试门
│   │   ├── tool_executor.py    # 工具执行器
│   │   ├── tool_intents.py     # 工具意图
│   │   ├── tool_recommender.py # 工具推荐
│   │   ├── tool_result.py      # 工具结果处理
│   │   ├── workspace_cleaner.py # 工作区清理
│   │   └── workspace_manager.py # 工作区管理
│   ├── logging/                # 日志系统
│   │   ├── logger.py           # 日志模块
│   │   ├── setup.py            # 日志设置
│   │   ├── tool_tracker.py     # 工具追踪器
│   │   ├── transcript_logger.py # 转录日志
│   │   └── unified_logger.py   # 统一日志
│   ├── orchestration/          # 任务与回合编排
│   │   ├── task_planner.py     # 任务计划器
│   │   ├── delegation_governor.py
│   │   ├── response_processor.py
│   │   ├── response_surface.py
│   │   ├── round_state.py
│   │   ├── tool_lifecycle.py
│   │   └── turn_outcome.py
│   ├── pet_system/             # 宠物系统 (10大子系统)
│   │   ├── pet_system.py
│   │   ├── models.py
│   │   ├── subsystems/         # 心跳/饥饿/健康/日记/梦境/基因/装扮/社交/声音/性格
│   │   └── utils/
│   ├── prompt_manager/         # 提示词管理
│   │   ├── builder.py          # 提示词构建器
│   │   ├── codebase_map_builder.py # 代码库地图
│   │   ├── prompt_manager.py   # 提示词管理器
│   │   ├── section_cache.py    # 章节缓存
│   │   ├── sections.py         # 章节工厂
│   │   ├── task_analyzer.py    # 任务分析器
│   │   └── types.py            # 类型定义
│   ├── restarter_manager/       # 重启管理
│   │   └── restarter.py
│   ├── ui/                     # 用户界面
│   │   ├── ascii_art.py        # ASCII 艺术
│   │   ├── cli_ui.py           # CLI UI
│   │   ├── workbench.py        # 工作台 Shell
│   │   ├── interactive_cli.py  # 交互式 CLI
│   │   ├── theme.py            # 主题配置
│   │   └── token_display.py    # Token 显示
│   └── core_prompt/            # 核心提示词
│       ├── SOUL.md             # 身份定义 (v4.1)
│       └── SPEC.md             # 开发流程规范 (v4.5)
├── tools/                      # 工具集
│   ├── agent_tools.py          # 子代理工具
│   ├── code_analysis_tools.py  # 代码分析工具
│   ├── codebase_analyzer.py    # 代码库分析器
│   ├── key_info_extractor.py   # 关键信息提取
│   ├── Key_Tools.py            # LangChain 工具包装
│   ├── memory_tools.py         # 记忆管理
│   ├── rebirth_tools.py        # 重生工具
│   ├── search_tools.py         # 搜索工具
│   ├── shell_tools.py          # Shell 工具
│   ├── state_broadcaster.py    # 状态广播
│   ├── token_manager.py        # Token 管理
│   └── web_search_tool.py      # 网络搜索
├── tests/                      # 测试套件（40+ 个 test_*.py；数量以 pytest 收集为准）
└── workspace/                   # 工作区
    ├── prompts/
    │   ├── DYNAMIC.md          # 动态任务描述
    │   ├── IDENTITY.md         # 身份定义
    │   └── USER.md             # 用户环境
    └── memory/archives/        # 压缩记忆存档
```

---

## 版本信息

| 文件 | 版本 | 更新日期 |
|------|------|----------|
| INDEX.md | v7.0 | 2026-05-11 |
| SOUL.md | v4.1 | 2026-04-30 |
| SPEC.md | v4.5 | 2026-04-30 |

---

## 核心约束

| 约束 | 限制 | 当前状态 |
|------|------|----------|
| agent.py 体量 | 优先将新逻辑放入 `core/`，入口保持黏合与循环 | ⚠️ 当前约 1400+ 行，持续收敛中 |
| Core First 规范 | 必须执行 | ✅ 已建立 |
| 测试 | 变更后跑相关 `pytest`；全量见下 | ✅ `tests/` 下 40+ 文件，pytest 收集逾 1200 条 |

---

## 开发流程 (SPEC.md)

每次任务执行流程：

```
[感知] git diff --stat 上次变更
[感知] 读取 INDEX.md 修改日志
[对比] 对比本次目标与上次产出
[决策] Core First 检查
[执行] 修改代码
[验证] py_compile + pytest + prompt_debugger
[分析] 流程自分析与优化
[记录] INDEX.md 修改日志追加
[交付] git commit
```

### Core First 检查清单

```
1. ls core/ → 了解目录结构
2. rg "function_name" core/ --type py → 搜索相似功能
3. 有 → import 使用，agent.py 仅写调用代码 (<10行)
   无 → 在 core/ 对应子目录创建/修改
```

---

## 测试状态

勿在此手工维护用例个数（易与仓库漂移）。在已激活的 **项目 `.venv`** 下执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ --collect-only -q
```

全量运行（同上，需 venv 以满足 `environment_smoke`）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

---

## 待处理任务追踪表

| # | 优先级 | 任务描述 | 状态 |
|---|--------|----------|------|
| 1 | P1 | 将 `agent.py` 中非循环黏合逻辑继续下沉到 `core/` | 📋 待办 |
| 2 | P1 | 生产环境锁定 Python 3.11–3.12 并文档化 CI 镜像 | 📋 待办 |
| 3 | P2 | 清理 tools/backups/ 历史备份（若仍存在） | 📋 待办 |
| 4 | P2 | 优化 `core/prompt_manager/builder.py` 可读性 | 📋 待办 |

---

## 关键文件路径

| 文件 | 用途 |
|------|------|
| `core/core_prompt/SOUL.md` | 身份定义 (56 行) |
| `core/core_prompt/SPEC.md` | 开发流程规范 (294 行) |
| `workspace/prompts/DYNAMIC.md` | 动态任务描述 |
| `workspace/prompts/IDENTITY.md` | 身份定义 |
| `workspace/prompts/USER.md` | 用户环境 |

---

## 健康检查

- [x] Core First 规范已建立
- [x] 索引与 README 已与当前目录树对齐（持续随提交更新）
- [x] 测试套件：`tests/` 下多文件，`pytest` 收集逾 1200 条（以本地收集为准）
- [ ] agent.py 体量偏大，按任务表继续收敛

---

## 修改日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v7.0 | 2026-05-11 | 同步项目结构（orchestration、infrastructure、ui）；修正 agent.py 体量与测试说明；移除过时的 ≤500 行与手工用例计数表 |
| v7.0 | 2026-05-03 | 重建 INDEX.md，修复损坏的表格格式；记录 v7.0 版本信息；清理冗余内容；建立清晰的待处理任务追踪表 |
| v6.9 | 2026-04-30 | 补充缺失的测试用例；完善 prompt_manager 模块 |
| v6.8 | 2026-04-29 | 完成 Core First 规范建立；agent.py 代码迁移完成 |
