# Vibelution

> 仓库状态快照：2026-05-19

Vibelution 是一套面向编码与自我改进场景的 AI Agent 系统。它已经不再只是一个单文件 CLI 实验，而是一个由 Python runtime、FastAPI 后端、React/Vite Web workbench、监督评测 harness、Gym promotion 记录链路和多档 LLM 配置组成的完整工程。

当前仓库的主线能力集中在 3 条工作模式上：

- `chat`：面向日常编码协作的工作台模式
- `self_evolution`：围绕当前代码库进行自我修复、自检、重启和迭代
- `supervised_evolution`：用 bundle / dataset 运行基线与候选对比，记录决策、lineage 和 proposal 生命周期

---

## 现在这个仓库包含什么

截至本次 README 同步时，仓库已经具备：

- 统一 Agent 入口：[agent.py](agent.py)
- Core First 架构：主流程尽量下沉到 `core/`
- 配置驱动的 LLM profiles / providers / model library
- 统一工作台 Shell + Web workbench
- Git memory、演化事务、test gate、重启守护
- 监督进化 harness、dashboard、dataset registry、Gym proposal 生命周期
- 前后端分离的 Web UI：后端 FastAPI，前端 React + Vite
- 较完整的测试覆盖：`pytest` 当前收集约 `1611` 条测试用例，另有前端 `vitest`

当前仓库盘点中，`agent.py` 约 `1625` 行，`core/` 已扩展到 `169` 个文件，`web/` 有独立前端工程，`tests/` 有 `71` 个测试模块。也就是说，这个项目现在更接近一个可持续演进的 Agent workbench，而不是早期的“单轮 ReAct 脚本”。

---

## 运行模式

| 模式 | 作用 | 默认入口 |
| --- | --- | --- |
| `chat` | 日常对话式编码协作、会话状态管理、文件预览、日志与 session 追踪 | 工作台默认 Shell 模式 |
| `self_evolution` | 自检、自修改、事务跟踪、重启与回流观察 | 默认 headless 模式 |
| `supervised_evolution` | 用 bundle / dataset 跑基线与候选，生成决策与可追踪评测记录 | 通过 CLI 参数显式进入 |

模式定义与策略入口在 [core/orchestration/agent_modes.py](core/orchestration/agent_modes.py)。

---

## 项目结构

```text
Vibelution/
├── agent.py                    # Agent 主入口与主循环编排
├── config/                     # 配置模型、加载、public config 同步
├── core/
│   ├── infrastructure/         # session、tool executor、git memory、security、workspace
│   ├── orchestration/          # 模式策略、回合收束、委托与响应编排
│   ├── prompt_manager/         # 提示词拼装、任务分析、代码库地图
│   ├── evaluation/             # supervised evolution、dataset registry、dashboard
│   ├── gym/                    # promotion proposal、activation/advisory 记录
│   ├── web/                    # FastAPI app、routes、services
│   ├── ui/                     # 统一 Shell / CLI workbench
│   └── logging/                # transcript、tool tracker、runtime log
├── tools/                      # LLM 可见工具与内部工具封装
├── web/                        # React + Vite 前端工程
├── workspace/                  # prompts、memory、evaluation、logs 等运行态产物
├── tests/                      # Python 测试套件
├── scripts/web_workbench.py    # 本地 Web workbench 启动脚本
└── AGENTS.md                   # 协作约束与工程规范
```

---

## 快速开始

### 1. 安装依赖

建议使用 Python `3.11` 或 `3.12`，并在项目虚拟环境中运行。

```bash
pip install -r requirements.txt
```

如果要运行前端开发环境：

```bash
cd web
npm install
```

### 2. 配置 LLM

新环境建议从 [config.example.toml](config.example.toml) 开始。当前配置体系已经切换到“profile + inline provider + model library”风格，不再是旧版 README 里那种 `llm.providers.remote_main` / `role_bindings` 的单层写法。

一个最小可读的配置骨架大致如下：

```toml
[runtime]
profile = "safe_remote"
preflight_doctor = true
require_venv = true

[llm.profiles.primary]
model = ""
temperature = 1.0
max_output_tokens = 8192
timeout = 120
streaming = true
api_key_env = "VIBELUTION_LLM_REMOTE_MAIN_MINIMAX_M2_7_API_KEY"

[llm.profiles.primary.provider]
kind = "minimax"
api_key_env = "MINIMAX_API_KEY"
base_url = "https://api.minimaxi.com/v1"
compat_mode = "openai"
requires_api_key = true

[agent.modes]
default_shell_mode = "chat"
default_headless_mode = "self_evolution"
explicit_evolution_request_behavior = "route_to_workbench"
```

说明：

- `config.example.toml` 提供了完整示例
- `llm.model_library` 中已预置 DeepSeek、OpenAI、MiniMax 等模型条目
- `runtime.profile` 当前支持 `safe_local`、`safe_remote`、`debug`、`ci`
- 新配置优先级仍是：CLI 覆盖 > 环境变量 > `config.toml` > 默认值

设置环境变量示例：

```powershell
$env:MINIMAX_API_KEY="your-api-key"
$env:DEEPSEEK_API_KEY="your-api-key"
$env:OPENAI_API_KEY="your-api-key"
```

### 3. 启动方式

#### 统一 Shell

默认直接运行：

```bash
python agent.py
```

在当前配置下，这会进入统一工作台，并默认落在 `chat` 模式。

#### Headless / 单轮执行

```bash
python agent.py --auto
python agent.py --mode chat --prompt "分析当前仓库结构" --single-turn
python agent.py --mode self_evolution --prompt "检查最近变更的回归风险"
```

#### 监督进化 CLI

```bash
python agent.py --list-datasets
python agent.py --choose-dataset
python agent.py --supervised-evolution --bundle supervised_evolution_dry_run_v1
python agent.py --dataset custom_prompt_jsonl --dataset-limit 20
python agent.py --supervised-dashboard
```

---

## Web Workbench

项目现在有独立的 Web workbench。

### 后端

```bash
python scripts/web_workbench.py --reload
```

默认监听 `http://127.0.0.1:8000`。

### 前端开发服务器

```bash
cd web
npm run dev
```

默认监听 `http://127.0.0.1:5173`，并代理 `/api` 到后端。

### 前端验证

```bash
cd web
npm run test
npm run build
```

Web workbench 当前已经覆盖：

- Chat 编码会话
- Session 列表与实时事件流
- 文件树与只读预览
- Runtime summary / health / mental state 摘要
- Self-evolution 与 supervised-evolution 轨道页
- Logs / Config / Reset / Pet 等路由

---

## 自进化与监督进化

### Self Evolution

当前自进化链路已经具备这些关键部件：

- Git working tree 信号采集
- 演化事务记录与 fitness 摘要
- 重启守护与回流观察
- 运行时约束与 tool blocking
- chat 数据采样与候选评测输入

### Supervised Evolution

监督进化已经不是占位命令，而是完整的最小闭环：

- baseline / candidate 对比运行
- decision record 持久化
- bundle / dataset materialization
- lineage 索引与链路摘要
- Gym promotion proposal lifecycle
- dashboard 生成

数据集注册表位于：

- [workspace/evaluation/datasets/registry.json](workspace/evaluation/datasets/registry.json)

当前内置或约定支持的来源包括：

- dry-run probe bundle
- reviewed chat multiturn
- generated cases
- HumanEval / MBPP 风格本地 JSONL
- SWE-bench Lite / Verified 占位入口

其中 SWE-bench 相关条目目前仍依赖额外 harness，仓库已经给出 registry 与物化入口，但不代表开箱即跑。

---

## 当前边界

这里特意写清楚，避免 README 比系统本身更乐观：

- `Gym promotion` 的 `active advisory baseline` 目前是观察与治理语义，不代表自动把新能力重写进 runtime
- 监督进化默认 bundle 仍偏向 dry-run / transaction safety / regression probe，而不是大规模真实 benchmark
- Web 前端已经可构建，但随着功能扩展，chunk 拆分和包体优化仍是持续工作
- 当前系统仍以本地仓库演化、评测和工作台协作为主，不应被误解成一个“自动线上部署代理”

---

## 测试与验证

### Python

当 `config.toml` 中 `runtime.require_venv = true` 时，建议显式使用项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

常用局部验证：

```bash
pytest tests/test_tool_executor.py -v
pytest tests/test_web_app.py -v
pytest tests/test_supervised_evolution.py -v
```

### Frontend

```bash
cd web
npm run test
npm run build
```

---

## 进一步阅读

| 文档 | 作用 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 仓库协作约束与工程规范 |
| [INDEX.md](INDEX.md) | 项目索引 |
| [CONTEXT.md](CONTEXT.md) | 运行上下文说明 |
| [core/core_prompt/SOUL.md](core/core_prompt/SOUL.md) | 核心使命与行为边界 |
| [core/core_prompt/SPEC.md](core/core_prompt/SPEC.md) | 核心开发规范 |

---

## License

MIT
