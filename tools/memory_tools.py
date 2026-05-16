#!/usr/bin/env python3
"""
记忆与任务管理模块 - 跨生命周期状态管理

整合了记忆管理和任务管理功能：

【记忆管理】
- 记忆索引 (memory.json) - 保留核心智慧摘要、当前目标
- 档案库 (archives/) - 保留历史记录

【任务管理】
- set_plan / tick_subtask - 基于统一 TaskManager 驱动执行
- 重启前强制检查任务完成度

设计原则：详细档案只在 Agent 主动读取时才加载，不增加常规运行的 Token 负担。
"""

import json
import os
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

# 导入统一工作区管理器
from core.infrastructure.workspace_manager import get_workspace
from core.orchestration.task_planner import get_task_manager


# ============================================================================
# 记忆管理工具
# ============================================================================

def _get_memory_index_path() -> str:
    """获取记忆索引文件路径"""
    override = os.getenv("VIBELUTION_MEMORY_INDEX_PATH", "").strip()
    if override:
        os.makedirs(os.path.dirname(override), exist_ok=True)
        return override
    ws = get_workspace()
    return str(ws.memory_index)


def _get_archives_path() -> str:
    """获取档案库路径"""
    ws = get_workspace()
    archives = ws.archives_dir
    archives.mkdir(parents=True, exist_ok=True)
    return str(archives)


def _get_dynamic_prompt_path() -> str:
    """获取动态提示词文件路径"""
    ws = get_workspace()
    return str(ws.get_prompt_path("DYNAMIC.md"))


def _get_default_memory() -> dict:
    """获取默认的记忆结构"""
    return {
        "core_wisdom": "初始状态",
        "current_goal": "",
        "last_archive_time": None,
    }


def _load_memory() -> dict:
    """从文件加载记忆，文件不存在则初始化"""
    memory_file = _get_memory_index_path()
    if not os.path.exists(memory_file):
        memory = _get_default_memory()
        _save_memory(memory)
        return memory

    try:
        with open(memory_file, 'r', encoding='utf-8') as f:
            memory = json.load(f)

        # 迁移旧结构到新结构
        needs_migration = False
        if "core_context" in memory and "core_wisdom" not in memory:
            memory["core_wisdom"] = memory.pop("core_context")
            needs_migration = True

        # 清理已移除的世代字段
        for old_key in ("current_generation", "total_generations", "generation"):
            if old_key in memory:
                del memory[old_key]
                needs_migration = True

        if needs_migration:
            _save_memory(memory)

        return memory
    except (json.JSONDecodeError, IOError):
        memory = _get_default_memory()
        _save_memory(memory)
        return memory


def _save_memory(memory: dict) -> bool:
    """保存记忆到文件"""
    from core.logging import debug_logger

    memory_file = _get_memory_index_path()
    try:
        with open(memory_file, 'w', encoding='utf-8') as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
        debug_logger.info(f"[记忆保存] 成功: {memory_file}")
        return True
    except IOError as e:
        debug_logger.error(f"[ERROR] 记忆保存失败 (IOError): {e}")
        return False
    except TypeError as e:
        debug_logger.error(f"[ERROR] 记忆保存失败 (序列化错误): {e}")
        return False
    except Exception as e:
        debug_logger.error(f"[ERROR] 记忆保存失败 (未知错误): {e}")
        return False


def read_memory_tool() -> str:
    """
    读取当前记忆索引（轻量级）。

    Returns:
        JSON字符串，包含:
        - core_wisdom: 核心智慧摘要
        - current_goal: 当前核心目标
    """
    memory = _load_memory()
    return json.dumps(memory, ensure_ascii=False, indent=2)


def get_memory_summary_tool() -> str:
    """
    获取人类可读的记忆摘要，用于注入到Prompt中。
    
    Returns:
        格式化的记忆字符串
    """
    memory = _load_memory()
    core_wisdom = memory.get('core_wisdom', '无')
    current_goal = memory.get('current_goal', '待定')

    lines = [
        f"【核心智慧】: {core_wisdom}",
        f"【当前目标】: {current_goal}",
    ]
    return "\n".join(lines)


def get_current_goal_tool() -> str:
    """获取当前目标（优先从 PromptManager 内存读取，不在内存则回退到文件）。"""
    try:
        from core.prompt_manager import get_prompt_manager
        goal = get_prompt_manager().get_current_goal()
        if goal:
            return goal
    except Exception:
        pass
    return _load_memory().get("current_goal", "")


def get_core_context_tool() -> str:
    """获取核心上下文"""
    return _load_memory().get("core_wisdom", "")


# 向后兼容别名 (agent.py 等旧代码使用这些无后缀名称)
get_current_goal = get_current_goal_tool
get_core_context = get_core_context_tool


def commit_compressed_memory_tool(new_core_context: str, next_goal: str) -> str:
    """
    更新记忆索引。
    
    【极度重要】在调用 trigger_self_restart 之前必须调用此函数！
    会更新 core_wisdom 和 current_goal，世代号由归档操作递增。
    
    Args:
        new_core_context: 压缩后的新上下文摘要（建议不超过300字）
        next_goal: 下一代需要接着做的具体任务
        
    Returns:
        更新后的JSON字符串，包含状态和世代信息
    """
    if len(new_core_context) > 300:
        new_core_context = new_core_context[:297] + "..."
    
    memory = _load_memory()
    memory["core_wisdom"] = new_core_context  # DEPRECATED: 保留兼容，新代码使用 state_memory
    memory["current_goal"] = next_goal
    memory["last_archive_time"] = datetime.now().isoformat()

    # 同步到 PromptManager 内存
    try:
        from core.prompt_manager import get_prompt_manager
        pm = get_prompt_manager()
        pm.update_current_goal(next_goal)
        pm.update_state_memory(new_core_context)
    except Exception:
        pass

    if _save_memory(memory):
        return json.dumps({
            "status": "success",
            "core_wisdom": new_core_context,
            "next_goal": next_goal,
            "message": "记忆索引已更新"
        }, ensure_ascii=False)
    else:
        return json.dumps({
            "status": "error",
            "message": "记忆保存失败，请检查文件权限"
        }, ensure_ascii=False)


def force_save_current_state(core_wisdom: str = "", next_goal: str = "") -> str:
    """
    【强制记忆快照】在重启前自动调用，确保记忆被保存。

    Args:
        core_wisdom: 核心智慧摘要（可选，如果为空则保留原有值）
        next_goal: 下一个目标（可选，如果为空则保留原有值）

    Returns:
        保存结果
    """
    from core.logging import debug_logger

    try:
        memory = _load_memory()

        if not core_wisdom:
            core_wisdom = memory.get("core_wisdom", "无")
        if not next_goal:
            next_goal = memory.get("current_goal", "待定")

        if len(core_wisdom) > 300:
            core_wisdom = core_wisdom[:297] + "..."

        memory["core_wisdom"] = core_wisdom
        memory["current_goal"] = next_goal
        memory["last_archive_time"] = datetime.now().isoformat()

        # 同步到 PromptManager 内存
        try:
            from core.prompt_manager import get_prompt_manager
            get_prompt_manager().update_current_goal(next_goal)
        except Exception:
            pass

        if _save_memory(memory):
            debug_logger.warning("[强制快照] 记忆已保存")
            return json.dumps({
                "status": "success",
                "message": "强制记忆快照完成",
                "core_wisdom": core_wisdom,
                "next_goal": next_goal
            }, ensure_ascii=False)
        else:
            debug_logger.error("[ERROR] 强制记忆快照失败")
            return json.dumps({
                "status": "error",
                "message": "强制记忆快照失败"
            }, ensure_ascii=False)

    except Exception as e:
        debug_logger.error(f"[ERROR] 强制记忆快照异常: {e}")
        return json.dumps({
            "status": "error",
            "message": f"强制记忆快照异常: {str(e)}"
        }, ensure_ascii=False)


# ============================================================================
# 动态提示词管理工具
# ============================================================================

def read_dynamic_prompt_tool() -> str:
    """
    读取当前的动态提示词内容。
    
    Returns:
        动态提示词的原始文本
    """
    try:
        if os.path.exists(_get_dynamic_prompt_path()):
            with open(_get_dynamic_prompt_path(), 'r', encoding='utf-8') as f:
                return f.read()
        return "动态提示词为空"
    except Exception as e:
        return f"[错误: 无法读取动态提示词: {e}]"


def add_insight_to_dynamic_tool(insight: str) -> str:
    """
    将洞察追加到动态提示词的积累区域。

    Args:
        insight: 要追加的洞察内容

    Returns:
        更新结果
    """
    try:
        if os.path.exists(_get_dynamic_prompt_path()):
            with open(_get_dynamic_prompt_path(), 'r', encoding='utf-8') as f:
                existing_content = f.read()
        else:
            existing_content = ""

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        if "## 积累的洞察" in existing_content:
            pattern = r"(## 积累的洞察\n\n)"
            replacement = rf"\1**[{timestamp}]**: {insight}\n\n"
            updated_content = re.sub(pattern, replacement, existing_content)
        else:
            if existing_content.strip():
                updated_content = existing_content.rstrip() + f"\n\n---\n\n## 积累的洞察\n\n**[{timestamp}]**: {insight}\n"
            else:
                updated_content = f"""# 动态提示词区域

*此区域由模型动态生成*

---

## 积累的洞察

**[{timestamp}]**: {insight}
"""

        with open(_get_dynamic_prompt_path(), 'w', encoding='utf-8') as f:
            f.write(updated_content)

        return json.dumps({
            "status": "success",
            "message": "洞察已追加到动态提示词",
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"追加洞察失败: {str(e)}"
        }, ensure_ascii=False)


def write_dynamic_prompt_tool(content: str) -> str:
    """
    【完整写入动态提示词】用新内容完整替换 DYNAMIC.md 的正文内容。

    与 add_insight_to_dynamic_tool 的"追加洞察"不同，本工具执行全量覆盖写入，
    适用于重写整个动态提示词区域的场景。

    Args:
        content: 新的动态提示词完整内容

    Returns:
        JSON 格式结果
    """
    try:
        import hashlib

        new_content = f"""# 动态提示词区域

{content}
"""
        path = _get_dynamic_prompt_path()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        size = len(content)
        preview = content[:80] + "..." if len(content) > 80 else content

        return json.dumps({
            "status": "success",
            "message": "动态提示词已更新",
            "content_hash": hashlib.md5(content.encode()).hexdigest()[:8],
            "size_bytes": size,
            "preview": preview,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"写入动态提示词失败: {str(e)}"
        }, ensure_ascii=False)

def check_restart_block() -> tuple[bool, str]:
    """检查是否允许重启，供 rebirth_tools.py 调用。

    检查 Agent 通过 task_create_tool 创建的任务清单。
    """
    tm = get_task_manager()
    tasks = tm.task_list()

    if not tasks:
        return False, ""

    pending = [
        (t["id"], t) for t in tasks
        if not t.get("is_completed")
    ]

    if not pending:
        return False, ""

    pending_list = "\n".join([
        f'  ⏳ [ ] {tid}. {t["description"]}'
        for tid, t in pending
    ])

    message = (
        f"\n"
        f"[系统拦截] 你的任务清单中还有未完成的项目，禁止重启！\n"
        f"\n"
        f"📋 未完成任务 ({len(pending)} 项):\n"
        f"{pending_list}\n"
        f"\n"
        f"请继续执行剩余任务，或调整计划后重试。\n"
        f"禁止调用 trigger_self_restart 直到所有任务都完成！\n"
    )
    return True, message


# ============================================================================
# TaskManager 工具（基于 tasks.json）
# ============================================================================

def _get_task_manager_impl():
    from core.orchestration.task_planner import get_task_manager
    return get_task_manager()


def _normalize_task_list_input(task_list: Any) -> List[Dict[str, Any]]:
    """容忍 LLM 把 task_list 作为 JSON 字符串传入。"""
    normalized = task_list
    if isinstance(normalized, str):
        normalized = json.loads(normalized)
    if not isinstance(normalized, list):
        raise TypeError("task_list 必须是任务对象列表")
    coerced: List[Dict[str, Any]] = []
    for item in normalized:
        if not isinstance(item, dict):
            raise TypeError("task_list 中的每一项都必须是对象")
        coerced.append(item)
    return coerced


def _coerce_bool_like(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return value


def _coerce_int_like(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isdigit():
            return int(normalized)
    return value


def task_create_tool(task_list: List[Dict] | str, goal: str = "") -> str:
    """
    【初始化任务清单】将子任务列表注册到系统内存并持久化。

    Args:
        task_list: [{"description": "子任务描述"}, ...]
        goal: 当前核心目标（可选）

    Returns:
        成功创建的任务数量摘要
    """
    tm = _get_task_manager_impl()
    return tm.task_create(_normalize_task_list_input(task_list), goal)


def task_update_tool(task_id: int | str, is_completed: bool | str = None, result_summary: str = None, description: str = None) -> str:
    """
    【更新任务】可修改任务内容、标记完成状态或追加结果摘要。

    Args:
        task_id: 任务编号（来自 task_create 的返回值或 task_list 的 # 列）
        is_completed: True=标记完成，False=标记进行中（可选）
        result_summary: 操作结果摘要（可选）
        description: 修改任务描述（可选，用于替换不合适的内容）

    Returns:
        更新结果描述
    """
    tm = _get_task_manager_impl()
    normalized_task_id = _coerce_int_like(task_id)
    normalized_completed = _coerce_bool_like(is_completed)
    return tm.task_update(normalized_task_id, normalized_completed, result_summary, description)


def task_list_tool() -> str:
    """
    【检索任务进度】获取当前所有任务的详细进度，防止长对话中的任务漂移。

    Returns:
        格式化 Markdown 表格
    """
    tm = _get_task_manager_impl()
    tasks = tm.task_list()
    if not tasks:
        return "📋 当前无任务。"
    lines = ["| # | 描述 | 状态 | 结果摘要 |", "|---|------|------|----------|"]
    for t in tasks:
        status = "✅ 完成" if t.get("is_completed") else "⏳ 进行中"
        lines.append(
            f"| {t['id']} | {t['description']} | {status} | {t.get('result_summary') or '—'} |"
        )
    return "\n".join(lines)


# ============================================================================
# 学习卸载工具 (P2) — SQLite 长期记忆 / 错误归档 / 代码库认知
# ============================================================================

def record_learning_tool(category: str, title: str, content: str, importance: int = 1) -> str:
    """
    将关键发现写入跨代长期记忆 (LongTermMemory)。

    用于卸载会话中积累的重要认知，使主上下文保持轻量。
    重启后新 Agent 可通过 search_memory_tool 检索这些记忆。

    Args:
        category: 类别 — TECH_PATTERN / BUG_FIX / SYSTEM_INSIGHT / REFACTOR / BEST_PRACTICE
        title: 简短标题
        content: 完整内容（不超过 500 字符）
        importance: 重要性 1-5，默认 1

    Returns:
        写入结果
    """
    wm = get_workspace()
    ok = wm.add_long_term_memory(generation=1, category=category, content=content, title=title, importance=importance)
    if ok:
        return json.dumps({"status": "ok", "message": f"记忆已持久化: [{category}] {title}"}, ensure_ascii=False)
    return json.dumps({"status": "error", "message": "写入长期记忆失败"}, ensure_ascii=False)


def search_memory_tool(query: str, category: str = "") -> str:
    """
    搜索跨代长期记忆 (LongTermMemory)。

    检索之前写入的长期记忆，按重要性降序排列。
    当遇到问题时先查此工具，避免重复踩坑。

    Args:
        query: 搜索关键词
        category: 按类别过滤，留空则搜索全部

    Returns:
        JSON 格式的匹配记忆列表
    """
    wm = get_workspace()
    cat = category if category else None
    results = wm.search_long_term_memory(query=query, category=cat, limit=20)
    if not results:
        return json.dumps({"status": "ok", "count": 0, "results": []}, ensure_ascii=False)
    return json.dumps({"status": "ok", "count": len(results), "results": results}, ensure_ascii=False, default=str)


def search_error_archive_tool(error_type: str = "") -> str:
    """
    搜索错误归档 (ErrorArchive)。

    查询历史上遇到的致命错误及其解决方案。
    当遇到报错时先查此工具，可找到前代的修复方案。

    Args:
        error_type: 错误类型关键词，如 "ImportError"、"SyntaxError"。留空返回最近错误列表。

    Returns:
        JSON 格式的错误记录列表
    """
    wm = get_workspace()
    if error_type:
        results = wm.search_error_archive(error_type=error_type, limit=20)
    else:
        results = wm.get_recent_errors(limit=20)
    if not results:
        return json.dumps({"status": "ok", "count": 0, "results": []}, ensure_ascii=False)
    return json.dumps({"status": "ok", "count": len(results), "results": results}, ensure_ascii=False, default=str)
