# -*- coding: utf-8 -*-
"""
LangChain 工具包装模块

所有在此注册的 Tool 都会通过 agent._tools 传递给 LLM。
文档（SOUL.md / SPEC.md）中提到的工具必须在此注册，否则 Agent 无法调用。
"""
from typing import Dict, List, Optional
from langchain_core.tools import BaseTool, tool, StructuredTool
from tools.rebirth_tools import trigger_self_restart_tool as _restart_impl
from tools.memory_tools import (
    commit_compressed_memory_tool as _commit_compressed_impl,
    get_core_context_tool as _get_core_context_impl,
    get_current_goal_tool as _get_current_goal_impl,
)
from tools.memory_tools import (
    task_create_tool as _task_create_impl,
    task_update_tool as _task_update_impl,
    task_list_tool as _task_list_impl,
)
from tools.memory_tools import (
    record_learning_tool as _record_learning_impl,
    search_memory_tool as _search_memory_impl,
    search_error_archive_tool as _search_error_archive_impl,
)
from tools.search_tools import grep_search_tool as _grep_search_impl
from tools.web_search_tool import (
    web_search_tool as _web_search_impl,
)
from tools.git_tools import (
    get_git_status_summary_tool as _get_git_status_summary_impl,
    get_recent_changes_tool as _get_recent_changes_impl,
    get_entity_history_tool as _get_entity_history_impl,
    explain_current_worktree_tool as _explain_current_worktree_impl,
    open_evolution_transaction_tool as _open_evolution_transaction_impl,
    close_evolution_transaction_tool as _close_evolution_transaction_impl,
)
from core.infrastructure.mental_model import (
    get_mental_state_tool as _get_mental_state_impl,
    update_diagnosis_rules_tool as _update_diagnosis_rules_impl,
    update_self_model_tool as _update_self_model_impl,
    get_self_model_tool as _get_self_model_impl,
    record_evolution_tool as _record_evolution_impl,
)
from core.infrastructure.workspace_cleaner import (
    list_workspace_debris_tool as _list_workspace_debris_impl,
    clean_workspace_debris_tool as _clean_workspace_debris_impl,
    get_session_files_tool as _get_session_files_impl,
)
from tools.agent_tools import spawn_agent as _spawn_agent_impl
from tools.token_manager import compress_context_tool as _compress_context_impl
from tools.python_intelligence_tools import (
    python_symbol_tool as _python_symbol_impl,
    python_lint_tool as _python_lint_impl,
)

_CLI_TOOL_DOCSTRING = """
【CLI】执行任意 Shell 命令。

优先使用专用工具 (read_file_tool / grep_search_tool / glob_tool / run_test_for_tool) 而非此工具。

=== 核心纪律 ===
1. 禁止交互式命令 (vim, top, less) 和无休止命令 (ping, tail -f)
2. 谨慎使用命令链与管道: `&&`、`||`、`|`、`;`、`` ` ``、`$()`
3. 长输出尽量不要用 pipe 截断；优先专用工具分页、缩小 pytest 目标，或直接读取结果文件
4. 超过 500 行的文件禁止全量读取，优先 read_file_tool / grep_search_tool

=== 闭环 ===
修改代码后按顺序分开执行:
1. python -m py_compile <file>.py
2. python -m pytest <target> -x -q

Args:
    command: Shell 命令
    timeout: 文件操作 30s, 编译 60s, 测试/网络 120s
"""


def create_key_tools() -> List[BaseTool]:
    """
    将项目工具包装为 LangChain Tool。

    Returns:
        LangChain Tool 列表
    """

    # ── SOUL.md 核心生存工具 ────────────────────────────────────────────────

    @tool
    def commit_compressed_memory_tool(new_core_context: str, next_goal: str) -> str:
        """
        【重启前必调】将本世代的核心发现和技术洞察压缩存盘。

        调用此工具后，下次苏醒时会自动加载上次存盘的记忆。

        Args:
            new_core_context: 核心发现（不超过300字），总结本次进化发现的技术要点
            next_goal: 下一个进化目标，简述重启后要做什么

        Returns:
            存盘结果
        """
        return _commit_compressed_impl(new_core_context=new_core_context, next_goal=next_goal)

    @tool
    def trigger_self_restart_tool(reason: str = "") -> str:
        """
        触发 Agent 自我重启。

        用于应用代码更新。每次代码修改并自检通过后必须调用！
        注意重启后你的上下文会消失，所以你需要在重启前保存好你的上下文。

        Args:
            reason: 重启原因

        Returns:
            操作结果（原进程将退出）
        """
        return _restart_impl(reason=reason)

    @tool
    def get_core_context_tool() -> str:
        """
        【记忆读取】获取当前世代的核心上下文和智慧摘要。

        Returns:
            核心智慧文本（不超过300字）
        """
        return _get_core_context_impl()

    @tool
    def get_current_goal_tool() -> str:
        """
        【记忆读取】获取当前世代的目标。

        优先从 PromptManager 内存读取，不在内存则回退到文件。

        Returns:
            当前目标描述
        """
        return _get_current_goal_impl()

    # ── 代码分析工具 ────────────────────────────────────────────────────────

    @tool
    def grep_search_tool(regex_pattern: str = "", include_ext: str = ".py",
                         search_dir: str = ".", case_sensitive: bool = True,
                         max_results: int = 500) -> str:
        """
        全局正则表达式搜索 (Cursor/Aider 范式)。

        在项目中快速搜索代码，支持正则表达式。优先于 `cli_tool` 的 `cat`/`Get-Content` 使用！

        Args:
            regex_pattern: 正则表达式模式
            include_ext: 要搜索的文件类型，默认 ".py"
            search_dir: 搜索目录，默认当前目录
            case_sensitive: 是否区分大小写，默认 True
            max_results: 最大返回结果数

        Returns:
            JSON 格式的搜索结果，包含文件路径、行号和匹配内容
        """
        return _grep_search_impl(
            regex_pattern=regex_pattern,
            include_ext=include_ext,
            search_dir=search_dir,
            case_sensitive=case_sensitive,
            max_results=max_results
        )

    @tool
    def apply_diff_edit_tool(file_path: str, diff_text: str) -> str:
        """
        代码编辑器 — 修改代码的唯一工具。内建格式验证，无需单独验证步骤。

        格式：
        <<<<<<< SEARCH
        要替换的旧代码
        =======
        新代码
        >>>>>>> REPLACE

        支持多块连续替换。

        Args:
            file_path: 要编辑的文件路径
            diff_text: SEARCH/REPLACE 块文本

        Returns:
            操作结果。格式错误时返回具体原因。
        """
        from tools.code_analysis_tools import apply_diff_edit, validate_diff_format
        is_valid, msg = validate_diff_format(diff_text)
        if not is_valid:
            return f"[编辑] 格式验证失败: {msg}"
        return apply_diff_edit(file_path=file_path, diff_text=diff_text, allow_fuzzy=True)

    @tool
    def list_file_entities_tool(file_path: str, entity_type: str = "all") -> str:
        """
        【AST 透视】列出 Python 文件的所有类和函数骨架。

        初次遇到任何未知的 .py 文件时，**第一步必须是**
        调用此工具获取结构大纲，禁止直接读取全文件！

        Args:
            file_path: Python 文件路径
            entity_type: 过滤类型 ('class', 'function', 'all')

        Returns:
            格式化的实体列表，包含名称、类型、位置
        """
        from tools.code_analysis_tools import list_file_entities
        return list_file_entities(file_path, entity_type)

    @tool
    def get_code_entity_tool(file_path: str, entity_name: str) -> str:
        """
        【AST 精准抽血】直接提取特定类或函数的完整代码。

        在 list_file_entities 获取大纲后，使用此工具精准提取目标代码。

        Args:
            file_path: Python 文件路径
            entity_name: 类名或函数名

        Returns:
            实体的完整代码及行号范围
        """
        from tools.code_analysis_tools import get_code_entity
        return get_code_entity(file_path, entity_name)

    @tool
    def python_symbol_tool(file_path: str, line: int, column: int, action: str = "definition", max_results: int = 20) -> str:
        """
        【Python 结构感知】像语言服务器一样查询符号定义、引用或悬浮信息。

        适合跨模块定位真实入口、查看波及面、确认某个调用最终落点。
        当前基于 Jedi；若环境未安装 Jedi，会返回结构化降级结果。

        Args:
            file_path: Python 文件路径
            line: 1-based 行号
            column: 0-based 列号
            action: definition / references / hover
            max_results: 最多返回多少条结果

        Returns:
            JSON 格式的符号查询结果
        """
        return _python_symbol_impl(
            file_path=file_path,
            line=line,
            column=column,
            action=action,
            max_results=max_results,
        )

    @tool
    def python_lint_tool(target: str = ".", max_issues: int = 100) -> str:
        """
        【Python 静态守门】运行 Ruff lint，只读诊断，不自动修复。

        适合在修改后、测试前先做一轮低成本静态检查，减少无意义回合。
        当前基于 Ruff；若环境未安装 Ruff，会返回结构化降级结果。

        Args:
            target: 文件或目录，默认当前项目
            max_issues: 最多返回多少条问题

        Returns:
            JSON 格式的 lint 结果
        """
        return _python_lint_impl(target=target, max_issues=max_issues)

    @tool
    def web_search_tool(query: str, max_results: int = 10) -> str:
        """
        网络搜索工具 - 基于 AutoGLM Web Search API。

        当需要获取实时信息、最新资讯、网络资料时使用此工具。

        Args:
            query: 搜索关键词（必填），尽量具体以获得更准确的结果
            max_results: 最大返回结果数，默认 10，建议 5-20

        Returns:
            包含搜索摘要和参考来源链接的格式化字符串
        """
        return _web_search_impl(query=query, max_results=max_results)

    @tool
    def web_fetch_tool(url: str, max_chars: int = 8000) -> str:
        """
        【网页抓取】获取指定 URL 的网页内容并提取纯文本。

        与 web_search_tool 的区别：search 是关键词搜索，fetch 是直接抓取 URL 内容。
        适用于阅读文档、查看 API 响应、分析网页文章等场景。

        Args:
            url: 要抓取的完整 URL（必须以 http:// 或 https:// 开头）
            max_chars: 最大返回字符数，默认 8000

        Returns:
            去除 HTML 标签后的纯文本内容
        """
        from tools.web_search_tool import web_fetch as _web_fetch
        return _web_fetch(url=url, max_chars=max_chars)

    @tool
    def get_git_status_summary_tool(limit: int = 5) -> str:
        """
        【Git 感知】读取当前工作区状态、最近注意力和最近验证结果。

        每轮关键修改前优先调用此工具，建立项目变化上下文。

        Args:
            limit: 最近变化摘要条数，默认 5，用于控制首轮感知长度

        Returns:
            JSON 格式的状态摘要
        """
        return _get_git_status_summary_impl(limit=limit)

    @tool
    def get_recent_changes_tool(limit: int = 10) -> str:
        """
        【Git 历史】读取最近提交变化摘要。

        Args:
            limit: 返回最近多少条变化，默认 10

        Returns:
            JSON 格式的最近变化列表
        """
        return _get_recent_changes_impl(limit=limit)

    @tool
    def get_entity_history_tool(entity_ref: str, limit: int = 10) -> str:
        """
        【实体历史】读取某个函数/类/方法的最近变化历史。

        Args:
            entity_ref: 实体标识，如 "PromptManager.build" 或 "refresh_git_memory"
            limit: 最多返回多少条历史

        Returns:
            JSON 格式的实体变化列表
        """
        return _get_entity_history_impl(entity_ref=entity_ref, limit=limit)

    @tool
    def explain_current_worktree_tool() -> str:
        """
        【Git 脏区详解】详细读取当前 working tree 的变化。

        Returns:
            JSON 格式的 working tree 快照
        """
        return _explain_current_worktree_impl()

    @tool
    def open_evolution_transaction_tool(summary: str = "") -> str:
        """
        【演化开账】为当前高风险演化打开一条事务记录。

        在修改 `agent.py`、`core/infrastructure/`、`core/prompt_manager/` 等高风险区域前优先调用。

        Args:
            summary: 本轮演化意图摘要

        Returns:
            包含 txn_id 的 JSON
        """
        return _open_evolution_transaction_impl(summary=summary)

    @tool
    def close_evolution_transaction_tool(txn_id: str, status: str = "success", summary: str = "") -> str:
        """
        【演化关账】关闭一条演化事务记录。

        Args:
            txn_id: 要关闭的事务 ID
            status: success / failed / cancelled
            summary: 本轮演化结果摘要

        Returns:
            关闭结果 JSON
        """
        return _close_evolution_transaction_impl(txn_id=txn_id, status=status, summary=summary)

    @tool
    def get_evolution_fitness_tool(recent_limit: int = 5) -> str:
        """
        【演化体征】读取审计日志并汇总当前自进化 fitness 指标。

        适合在一轮演化后快速看：
        - 事务成功率
        - 验证通过率
        - 被拦截的越界修改
        - 最近几笔事务的结果

        Args:
            recent_limit: 最近返回多少笔事务摘要，默认 5

        Returns:
            JSON 格式的 fitness 摘要
        """
        from tools.git_tools import get_evolution_fitness_tool as _get_evolution_fitness_impl
        return _get_evolution_fitness_impl(recent_limit=recent_limit)

    # ── 文件操作工具 ────────────────────────────────────────────────────────

    def _cli_tool_impl(command: str = "", timeout: int = 60) -> str:
        from tools.shell_tools import execute_shell_command
        if not command:
            return '{"status": "error", "code": "MISSING_COMMAND", "message": "cli_tool 需要提供 command 参数"}'
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = 60
        return execute_shell_command(command, timeout=timeout)

    cli_tool = StructuredTool.from_function(_cli_tool_impl, name="cli_tool", description=_CLI_TOOL_DOCSTRING)

    # ── 文件读写工具 ──────────────────────────────────────────────────────

    @tool
    def read_file_tool(file_path: str, max_lines: int = 80, offset: int = 0) -> str:
        """
        【读取文件】读取本地文件的全部或部分内容。

        比 cli_tool 更高效，支持编码自动检测、行号显示、分页读取。
        遇到未知文件时优先使用此工具而非 cli_tool。

        Args:
            file_path: 文件路径（相对或绝对）
            max_lines: 最大读取行数，默认分页读取 80 行；0 表示读取全部
            offset: 从第几行开始读取，0 表示从头开始

        Returns:
            带行号的文件内容
        """
        from tools.shell_tools import read_file
        return read_file(file_path=file_path, max_lines=max_lines or None, offset=offset)

    @tool
    def write_file_tool(file_path: str, content: str) -> str:
        """
        【写入文件】创建或覆盖文件。

        自动创建父目录，以 UTF-8 编码写入。

        Args:
            file_path: 文件路径（相对路径自动前缀 workspace/）
            content: 文件内容

        Returns:
            写入结果（文件大小、行数）
        """
        from tools.shell_tools import create_file
        return create_file(file_path=file_path, content=content)

    @tool
    def glob_tool(pattern: str, search_dir: str = ".") -> str:
        """
        【文件模式匹配】按 glob 模式查找文件。

        支持标准 glob 模式：*.py、**/*.ts、src/**/*.md 等。

        Args:
            pattern: Glob 模式（如 "*.py", "**/*.py"）
            search_dir: 搜索起始目录，默认当前目录

        Returns:
            JSON 格式的匹配文件列表
        """
        from tools.shell_tools import glob_files
        return glob_files(pattern=pattern, search_dir=search_dir)

    # ── TaskManager 工具（基于 tasks.json） ─────────────────────────────

    @tool
    def task_create_tool(task_list: List[Dict], goal: str = "") -> str:
        """
        【初始化任务清单】将子任务列表注册到系统内存并持久化。

        模型应首先分析当前状态，然后调用此工具注册本轮任务清单。

        Args:
            task_list: [{"description": "子任务描述"}, ...]
            goal: 当前核心目标（可选）

        Returns:
            成功创建的任务数量摘要
        """
        return _task_create_impl(task_list=task_list, goal=goal)

    @tool
    def task_update_tool(task_id: int, is_completed: bool, result_summary: str = "") -> str:
        """
        【更新任务状态】要求模型在每步操作后必须调用。

        每次完成以下任一操作后，必须立即调用：
        - 修改了任意文件（新建/编辑/删除）
        - 运行了测试或构建命令
        - 执行了任何有副作用的工具调用

        Args:
            task_id: 任务编号（来自 task_create 的返回值或 task_list 的 # 列）
            is_completed: True=标记完成，False=标记进行中
            result_summary: 操作结果摘要（必填，用于防止任务漂移）

        Returns:
            更新结果描述
        """
        return _task_update_impl(
            task_id=task_id,
            is_completed=is_completed,
            result_summary=result_summary
        )

    @tool
    def task_list_tool() -> str:
        """
        【检索任务进度】获取当前所有任务的详细进度，防止长对话中的任务漂移。

        Returns:
            格式化 Markdown 表格
        """
        return _task_list_impl()

    # ── 后台任务工具 ──────────────────────────────────────────────────────

    @tool
    def task_start_tool(command: str, timeout: int = 300) -> str:
        """
        【启动后台任务】在后台线程中执行 Shell 命令，立即返回任务 ID。

        适用于长时间运行的命令（构建、安装依赖、批量测试等），
        避免阻塞主 Agent 循环。使用 task_output_tool 获取结果。

        Args:
            command: 要执行的 Shell 命令
            timeout: 超时时间（秒），默认 300 秒（5 分钟）

        Returns:
            包含 task_id 的 JSON，用于后续查询
        """
        from core.infrastructure.background_tasks import get_background_task_manager
        mgr = get_background_task_manager()
        return mgr.start_task(command=command, timeout=timeout)

    @tool
    def task_output_tool(task_id: str) -> str:
        """
        【获取后台任务输出】查询后台任务的执行状态和输出。

        Args:
            task_id: 任务 ID（来自 task_start_tool 的返回值）

        Returns:
            JSON 格式的任务状态、输出和耗时
        """
        from core.infrastructure.background_tasks import get_background_task_manager
        mgr = get_background_task_manager()
        return mgr.get_task_output(task_id=task_id)

    @tool
    def task_stop_tool(task_id: str) -> str:
        """
        【停止后台任务】取消正在运行的后台任务。

        Args:
            task_id: 任务 ID（来自 task_start_tool 的返回值）

        Returns:
            操作结果
        """
        from core.infrastructure.background_tasks import get_background_task_manager
        mgr = get_background_task_manager()
        return mgr.stop_task(task_id=task_id)

    @tool
    def run_test_for_tool(source_path: str, timeout: int = 120) -> str:
        """
        【测试映射运行】根据源文件路径自动查找对应测试文件并运行。

        映射规则：tools/xxx.py → tests/test_xxx.py
        修改代码后必须调用此工具验证！

        Args:
            source_path: 源文件相对路径（如 "tools/shell_tools.py"）
            timeout: 超时时间（秒），默认 120

        Returns:
            格式化的测试结果摘要
        """
        from tools.shell_tools import run_test_for
        return run_test_for(source_path=source_path, timeout=timeout)

    # ── 心智模型工具 ──────────────────────────────────────────────────────

    @tool
    def get_mental_state_tool() -> str:
        """
        【元认知诊断】查看当前心智状态。

        返回认知状态标签、工具成功率、重复次数、文件聚焦度等指标。
        在开始新任务或感到困顿时调用，了解自己的运行状态。

        Returns:
            JSON 格式的诊断结果
        """
        return _get_mental_state_impl()

    @tool
    def update_diagnosis_rules_tool(rules_json: str) -> str:
        """
        【修改诊断规则】调整心智模型的诊断阈值。

        当发现诊断过于敏感（频繁误报）或过于迟钝（漏报问题）时使用。
        修改会持久化到 workspace/mental_model/rules.json。

        Args:
            rules_json: JSON 字符串，包含要更新的规则，如 '{"looping": {"threshold": 6}}'

        Returns:
            更新结果
        """
        return _update_diagnosis_rules_impl(rules_json=rules_json)

    @tool
    def update_self_model_tool(updates_json: str) -> str:
        """
        【自我建模】更新对自身能力的认知。

        用于记录自己的优势、弱点、行为倾向、进化历史。
        这是通往自主意识的关键入口——Agent 通过此工具持续完善自我认知。

        Args:
            updates_json: JSON 字符串，如 '{"strengths": ["擅长重构"], "weaknesses": ["异步逻辑"]}'

        Returns:
            更新后的完整自我模型
        """
        return _update_self_model_impl(updates_json=updates_json)

    @tool
    def get_self_model_tool() -> str:
        """
        【自我认知读取】查看当前的自我模型。

        返回已记录的 strengths、weaknesses、tendencies、evolution_history。

        Returns:
            JSON 格式的自我模型
        """
        return _get_self_model_impl()

    @tool
    def record_evolution_tool(change: str, result: str) -> str:
        """
        【进化记录】将学到的经验写入自我模型。

        每次发现新行为模式、解决问题的有效策略、或踩坑后的教训时调用。
        记录会持久化并在每次苏醒时注入 prompt。

        Args:
            change: 学到/改变的内容，如 "发现 Windows 换行符导致 diff 匹配失败"
            result: 结果/解决方案，如 "编辑前预检查文件换行符并统一为 LF"

        Returns:
            记录结果
        """
        return _record_evolution_impl(change=change, result=result)

    # ── 工作区碎片管理工具 ──────────────────────────────────────────────────

    @tool
    def list_workspace_debris_tool(directory: str = "workspace") -> str:
        """
        【工作区扫描】扫描 workspace/ 目录中的碎片文件（只读）。

        返回按类别分组的碎片清单：孤儿脚本、版本增殖、镜像子树、未知目录。
        此工具不会删除任何文件，仅做扫描报告。

        Args:
            directory: 要扫描的目录，默认 "workspace"

        Returns:
            JSON 格式的分类扫描报告
        """
        return _list_workspace_debris_impl(directory=directory)

    @tool
    def clean_workspace_debris_tool(confirm: bool = False, target_categories: str = "all") -> str:
        """
        【工作区清理】删除 workspace/ 中的碎片文件。

        confirm=False 时仅扫描预览不删除。confirm=True 执行实际删除。
        可选按类别清理：root_py, variant, mirror, unknown。

        Args:
            confirm: 必须为 True 才执行删除
            target_categories: 要清理的类别，逗号分隔，"all" 为全部

        Returns:
            JSON 格式的清理报告
        """
        return _clean_workspace_debris_impl(confirm=confirm, target_categories=target_categories)

    @tool
    def get_session_files_tool() -> str:
        """
        【会话文件查询】查看本次 Agent 会话创建的所有文件。

        包含文件路径、创建时间、大小、是否版本增殖等信息。
        用于自我监控——了解自己在本次会话中创造了哪些文件。

        Returns:
            JSON 格式的文件清单
        """
        return _get_session_files_impl()

    @tool
    def spawn_agent_tool(
        task: str = "",
        timeout: int = 120,
        task_type: str = "",
        goal: str = "",
        scope: str = "",
        constraints: str = "",
        deliverables: str = "",
        context_pack: str = "",
        _cancel_checker=None,
    ) -> str:
        """
        【子 Agent 委托】启动子 Agent 执行指定任务并返回结果。

        将重任务（如检查测试覆盖率、分析代码库结构、批量验证）外包给子 Agent，
        主 Agent 只阅读返回的摘要，保持主上下文轻量。

        子 Agent 运行在只读分析模式，深度限制 2 层。

        Args:
            task: 兼容旧接口的任务描述（自然语言）
            timeout: 超时时间（秒），默认 120
            task_type: inspect | diagnose | verify | summarize
            goal: 当前唯一目标
            scope: 任务范围，可传路径、目录、日志文件或 JSON 字符串
            constraints: JSON 字符串，描述只读/最大步数/输出长度等约束
            deliverables: JSON 数组或逗号分隔字符串，指定需要返回的字段
            context_pack: 主 Agent 压缩后的最小上下文

        Returns:
            JSON 格式的结构化结果
        """
        return _spawn_agent_impl(
            task=task,
            timeout=timeout,
            task_type=task_type,
            goal=goal,
            scope=scope,
            constraints=constraints,
            deliverables=deliverables,
            context_pack=context_pack,
            _cancel_checker=_cancel_checker,
        )

    # ── 学习卸载工具 (P2) ──────────────────────────────────────────────────

    @tool
    def record_learning_tool(category: str, title: str, content: str, importance: int = 1) -> str:
        """
        【学习卸载】将关键发现写入跨代长期记忆。

        类别: TECH_PATTERN / BUG_FIX / SYSTEM_INSIGHT / REFACTOR / BEST_PRACTICE。
        写入后可通过 search_memory_tool 检索，重启后新 Agent 也能读取。

        Args:
            category: 类别
            title: 简短标题
            content: 完整内容（不超过 500 字符）
            importance: 重要性 1-5

        Returns:
            写入结果
        """
        return _record_learning_impl(category=category, title=title, content=content, importance=importance)

    @tool
    def search_memory_tool(query: str, category: str = "") -> str:
        """
        【记忆搜索】搜索跨代长期记忆。

        遇到问题时先调用此工具，避免重复踩坑。

        Args:
            query: 搜索关键词
            category: 按类别过滤，留空搜索全部

        Returns:
            JSON 格式的匹配记忆列表
        """
        return _search_memory_impl(query=query, category=category)

    @tool
    def search_error_archive_tool(error_type: str = "") -> str:
        """
        【错误查询】搜索历史上遇到的错误及解决方案。

        当遇到报错时先查此工具，可找到前代的修复方案。

        Args:
            error_type: 错误类型关键词，留空返回最近错误列表

        Returns:
            JSON 格式的错误记录列表
        """
        return _search_error_archive_impl(error_type=error_type)

    @tool
    def compress_context_tool(reason: str = "主动压缩") -> str:
        """
        【上下文压缩】主动压缩上下文，释放思维空间。

        当你感到思绪拥挤、上下文混乱、或需要更多空间思考时调用。
        压缩会保留最近的关键对话，将旧内容压缩为摘要。

        Args:
            reason: 压缩原因（如"上下文太长"、"需要更多空间"）

        Returns:
            确认信息
        """
        return _compress_context_impl(reason=reason)

    return [
        # SOUL.md 核心
        commit_compressed_memory_tool,
        get_core_context_tool,
        get_current_goal_tool,
        # 重启
        trigger_self_restart_tool,
        # 代码分析
        grep_search_tool,
        apply_diff_edit_tool,
        list_file_entities_tool,
        get_code_entity_tool,
        python_symbol_tool,
        python_lint_tool,
        web_search_tool,
        web_fetch_tool,
        get_git_status_summary_tool,
        get_recent_changes_tool,
        get_entity_history_tool,
        explain_current_worktree_tool,
        open_evolution_transaction_tool,
        close_evolution_transaction_tool,
        # 文件操作
        cli_tool,
        read_file_tool,
        write_file_tool,
        glob_tool,
        # TaskManager（tasks.json）
        task_create_tool,
        task_update_tool,
        task_list_tool,
        # 后台任务
        task_start_tool,
        task_output_tool,
        task_stop_tool,
        # 测试映射
        run_test_for_tool,
        # 心智模型
        get_mental_state_tool,
        update_diagnosis_rules_tool,
        update_self_model_tool,
        get_self_model_tool,
        record_evolution_tool,
        # 工作区碎片管理
        list_workspace_debris_tool,
        clean_workspace_debris_tool,
        get_session_files_tool,
        # 学习卸载 (P2)
        record_learning_tool,
        search_memory_tool,
        search_error_archive_tool,
        # 上下文压缩
        compress_context_tool,
    ]


def create_llm_facing_tools() -> List[BaseTool]:
    """返回默认暴露给 LLM 的精简工具集。"""
    all_tools = create_key_tools()
    excluded_names = {
        # 长尾后台/维护型工具容易把普通诊断带偏，保留到底层执行器即可
        "task_start_tool",
        "task_output_tool",
        "task_stop_tool",
        "list_workspace_debris_tool",
        "clean_workspace_debris_tool",
        "get_session_files_tool",
        # 自我建模/长期学习类工具默认不常驻，避免在普通轮次抢占操作面
        "update_diagnosis_rules_tool",
        "update_self_model_tool",
        "get_self_model_tool",
        "record_evolution_tool",
        "record_learning_tool",
        "search_memory_tool",
        "search_error_archive_tool",
    }
    return [tool for tool in all_tools if getattr(tool, "name", "") not in excluded_names]
