"""
重生工具模块

提供 Agent 自我重启的核心功能，通过独立守护进程实现安全的进程重启。

本模块是实现"自我进化"能力的关键组件：
1. 触发自我重启 - 启动独立的 restarter 进程
2. 脱离父进程 - 确保重启过程不影响原 Agent
3. 跨平台兼容 - 同时支持 Windows 和 Unix 系统

架构说明：
- 当 Agent 需要重启时，调用 trigger_self_restart()
- 该函数使用 subprocess 启动 restarter 作为独立进程
- restarter 监控原 Agent 进程，等待其结束
- 原进程结束后，restarter 拉起新的 Agent 进程
- 当前 Agent 在启动 restarter 后执行 sys.exit(0) 自我了结

依赖：
    - os: 内置模块
    - sys: 内置模块
    - subprocess: 内置模块
    - pathlib: 内置模块
"""

import os
import json
import sys
from pathlib import Path
from typing import Optional
from core.logging import debug_logger


# ============================================================================
# 配置常量
# ============================================================================

# Restarter 模块路径（使用 -m 方式调用）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
RESTARTER_MODULE = "core.restarter_manager.restarter"

# 重启原因分类
RESTART_REASONS = {
    'code_update': '代码更新后重启',
    'threshold_reached': '达到运行阈值重启',
    'manual': '手动触发重启',
    'error_recovery': '错误恢复重启',
    'scheduled': '定时重启',
    'maintenance': '维护重启',
}

RESTART_REASON_KEYWORDS = {
    'code_update': ('code_update', '代码更新', '代码已更新', '源码更新', '修改代码'),
    'threshold_reached': ('threshold_reached', '阈值', '达到运行阈值', '达到重启阈值'),
    'manual': ('manual', '手动', '用户请求'),
    'error_recovery': ('error_recovery', '错误恢复', '异常恢复', '失败恢复'),
    'scheduled': ('scheduled', '定时', '计划任务', '周期'),
    'maintenance': ('maintenance', '维护', '保养'),
}


# ============================================================================
# 辅助函数
# ============================================================================

def get_current_pid() -> int:
    """
    获取当前进程的 PID。
    
    Returns:
        当前进程的进程 ID
    """
    return os.getpid()


def get_script_path() -> str:
    """
    获取 Agent 主脚本的路径。
    
    Returns:
        agent.py 的绝对路径
    """
    return str(PROJECT_ROOT / "agent.py")


def classify_restart_reason(reason: str) -> str:
    """
    分类重启原因。
    
    Args:
        reason: 重启原因描述
        
    Returns:
        分类后的原因类别
    """
    reason_lower = reason.lower()

    for category, keywords in RESTART_REASON_KEYWORDS.items():
        if any(keyword.lower() in reason_lower for keyword in keywords):
            return category
    
    return 'manual'


def validate_restarter_available() -> tuple[bool, str]:
    """
    验证 restarter_manager 模块是否可用。

    Returns:
        (是否可用, 错误消息) 元组
    """
    try:
        import importlib
        importlib.import_module(RESTARTER_MODULE)
        return True, ""
    except ImportError as e:
        return False, f"Restarter 模块不可用: {e}"


# ============================================================================
# 跨平台进程脱离逻辑
# ============================================================================

def spawn_detached_process_windows(command: list, env: Optional[dict] = None) -> Optional[int]:
    """
    在 Windows 上启动脱离父进程的子进程。
    
    使用 CREATE_NEW_PROCESS_GROUP 标志创建独立进程，
    使得子进程不受父进程终止影响。
    
    Args:
        command: 命令列表
        env: 可选的环境变量
        
    Returns:
        新进程的 PID，失败返回 None
    """
    try:
        import subprocess
        
        # 日志文件路径
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        restarter_log = os.path.join(log_dir, 'restarter_realtime.log')
        
        # DETACHED_PROCESS 分离控制台关联
        # CREATE_NEW_PROCESS_GROUP 使进程完全脱离父进程组
        creation_flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

        with open(restarter_log, 'a', encoding='utf-8') as log_file:
            process = subprocess.Popen(
                command,
                env=env,
                creationflags=creation_flags,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=False
            )

        debug_logger.info(f"Windows: 已启动脱离进程, PID: {process.pid}")
        return process.pid
        
    except Exception as e:
        debug_logger.error(f"Windows: 启动脱离进程失败 - {e}")
        return None


def spawn_detached_process_unix(command: list, env: Optional[dict] = None) -> Optional[int]:
    """
    在 Unix 系统上启动脱离父进程的子进程。
    
    使用 double-fork 技术：
    1. 第一次 fork：子进程从父进程分离
    2. 第二次 fork：确保进程不会成为会话首进程
    3. setsid()：创建新的会话，完全脱离父进程
    
    Args:
        command: 命令列表
        env: 可选的环境变量
        
    Returns:
        新进程的 PID，失败返回 None
    """
    try:
        # 日志文件路径
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        restarter_log = os.path.join(log_dir, 'restarter_realtime.log')
        
        # 第一次 fork
        pid = os.fork()
        
        if pid == 0:
            # 子进程（第一次 fork 后）
            try:
                # 第二次 fork
                pid = os.fork()
                
                if pid == 0:
                    # 孙子进程（最终运行的进程）
                    # 创建新会话，完全脱离
                    os.setsid()
                    
                    # 重定向输出到日志文件
                    os.chdir(log_dir)
                    with open(restarter_log, 'a') as f:
                        os.dup2(f.fileno(), 1)  # stdout -> log
                        os.dup2(f.fileno(), 2)  # stderr -> log
                    
                    # 执行目标命令
                    os.execvp(command[0], command)
                else:
                    # 子进程：立即退出，让孙子进程成为孤儿
                    os._exit(0)
                    
            except OSError as e:
                debug_logger.error(f"Unix fork error: {e}")
                os._exit(1)
        else:
            # 父进程：等待子进程退出
            os.waitpid(pid, 0)
            debug_logger.info(f"Unix: 已启动脱离进程, 中间 PID: {pid}")
            return pid
            
    except Exception as e:
        debug_logger.error(f"Unix: 启动脱离进程失败 - {e}")
        return None


def spawn_detached_process(command: list, env: Optional[dict] = None) -> Optional[int]:
    """
    跨平台启动脱离父进程的子进程。
    
    根据操作系统自动选择合适的实现方式：
    - Windows: 使用 CREATE_NEW_PROCESS_GROUP
    - Unix/Linux/macOS: 使用 double-fork + setsid
    
    Args:
        command: 命令列表 [python, script_path, ...]
        env: 可选的环境变量
        
    Returns:
        新进程的 PID，失败返回 None
    """
    if sys.platform == 'win32':
        return spawn_detached_process_windows(command, env)
    else:
        return spawn_detached_process_unix(command, env)


# ============================================================================
# 核心功能函数
# ============================================================================

def trigger_self_restart_tool(reason: str = "") -> str:
    """
    触发 Agent 自我重启。
    
    此函数是实现 Agent 自我进化能力的核心。它会：
    1. 验证 restarter 模块是否可用
    2. 启动 restarter 作为独立进程
    3. 记录重启日志
    4. 返回后调用方应该执行 sys.exit(0)
    
    重启流程：
    ```
    Agent 进程                    Restarter 进程
        |                               |
        | --- 启动 restarter --------> |
        |                               |
        | --- 执行 sys.exit(0) -----> X  |
        |                               |
        |           (等待原进程结束)      |
        |                               |
        |           <-- 拉起新 Agent --- |
    ```
    
    Args:
        reason: 重启原因描述。
               用于日志记录和调试。
               
               建议格式：简洁的关键词 + 简短说明
               示例：
               - "threshold_reached: 迭代次数达到 100"
               - "code_update: 代码已修改，需要重新加载"
               - "manual: 用户请求重启"
               - "scheduled: 每日定时重启"
               - "error_recovery: 发生错误后恢复"
    
    Returns:
        操作结果的描述字符串。
        
        成功时返回：
        ```
        ✓ 重启进程已触发
        PID: 12345
        原因: threshold_reached: 迭代次数达到 100
        Restarter: core.restarter_manager.restarter
        状态: 已脱离，正在启动守护进程
        
        当前进程将退出，请等待自动重启...
        ```
        
        失败时返回错误描述：
        - "错误: Restarter 脚本不存在"
        - "错误: 无法获取当前 PID"
        - "错误: 启动重启进程失败"
    
    Raises:
        此函数不抛出异常，所有错误都通过返回字符串报告。
        调用方需要检查返回值，如果有错误则不应调用 sys.exit()。
    
    Example:
        >>> result = trigger_self_restart("代码已更新")
        >>> if "成功" in result or "✓" in result:
        ...     print("即将重启...")
        ...     sys.exit(0)  # Agent 自我了结
        ... else:
        ...     print(f"重启失败: {result}")
        
        >>> # 在 Agent 类中使用
        >>> def handle_restart(self):
        ...     result = trigger_self_restart("达到重启阈值")
        ...     if "✓" in result:
        ...         return result  # 返回给调用者处理退出
        ...     return result  # 错误处理
    
    Notes:
        - 此函数不执行 sys.exit()，调用方需要自行处理
        - 启动 restarter 后，原 Agent 应尽快调用 sys.exit(0)
        - 如果不立即退出，restarter 可能无法正确接管
        - 重启是异步的，新 Agent 可能在几秒后启动
        - 可以通过 --verbose 参数查看详细日志
    """
    debug_logger.info("=" * 60)
    debug_logger.info("触发自我重启")
    debug_logger.info("=" * 60)

    # 0. 【强制记忆快照】在重启前自动保存状态
    # 这是最后一道防线，确保即使 Agent 没有主动保存记忆，系统也会自动保存
    try:
        from tools.memory_tools import force_save_current_state, get_core_context, get_current_goal
        core_ctx = get_core_context() or "无"
        current_goal = get_current_goal() or "待定"

        # 从环境变量或 reason 中提取模型可能提供的智慧摘要
        # reason 格式可能是 "xxx|智慧摘要" 或纯 reason
        if "|" in reason:
            parts = reason.split("|", 1)
            model_wisdom = parts[1].strip() if len(parts) > 1 else core_ctx
        else:
            model_wisdom = core_ctx

        snapshot_result = force_save_current_state(
            core_wisdom=model_wisdom,
            next_goal=current_goal,
        )
        debug_logger.info(f"[强制快照] {snapshot_result}")
    except Exception as e:
        debug_logger.error(f"[ERROR] 强制记忆快照失败: {e}")

    # 1. 获取必要信息
    current_pid = get_current_pid()
    script_path = get_script_path()
    
    debug_logger.info(f"当前 PID: {current_pid}")
    debug_logger.info(f"脚本路径: {script_path}")
    debug_logger.info(f"重启原因: {reason}")
    
    # 2. 验证 restarter 可用性
    is_available, error_msg = validate_restarter_available()
    if not is_available:
        debug_logger.error(f"Restarter 不可用: {error_msg}")
        return f"错误: {error_msg}"
    
    debug_logger.info(f"Restarter 模块: {RESTARTER_MODULE}")

    # 3. 分类重启原因
    reason_category = classify_restart_reason(reason)
    debug_logger.info(f"原因分类: {reason_category}")

    # 4. 构建环境变量
    env = os.environ.copy()
    env['AGENT_RESTART_REASON'] = reason
    env['AGENT_RESTART_CATEGORY'] = reason_category
    env['AGENT_ORIGINAL_PID'] = str(current_pid)
    env['AGENT_RESTART_ARGS'] = json.dumps(sys.argv[1:], ensure_ascii=False)

    # 5. 构建命令（使用 -m 方式调用）
    command = [
        sys.executable,
        '-m', RESTARTER_MODULE,
        '--pid', str(current_pid),
        '--script', script_path,
    ]

    # 添加详细日志参数（可选）
    # command.append('--verbose')

    debug_logger.info(f"执行命令: {' '.join(command)}")

    # 6. 启动脱离进程
    new_pid = spawn_detached_process(command, env)

    if new_pid:
        # 构建成功消息
        result_lines = [
            "✓ 重启进程已触发",
            f"PID: {current_pid}",
            f"原因: {reason}",
            f"Restarter: {RESTARTER_MODULE}",
            "",
            "状态: 已脱离父进程，正在启动守护进程",
            "",
            "当前进程将退出，请等待自动重启...",
        ]
        
        result = "\n".join(result_lines)
        
        debug_logger.info("=" * 60)
        debug_logger.info("重启触发成功")
        debug_logger.info("当前 Agent 进程即将退出")
        debug_logger.info("=" * 60)
        
        return result
    else:
        error_msg = "错误: 启动重启进程失败"
        debug_logger.error(error_msg)
        return error_msg


def get_restart_log_path() -> Path:
    """
    获取重启日志文件的路径。
    
    Returns:
        日志文件路径
    """
    return PROJECT_ROOT / "logs" / "restart.log"


def write_restart_log(pid: int, reason: str, success: bool) -> None:
    """
    写入重启日志。
    
    Args:
        pid: 触发重启的进程 PID
        reason: 重启原因
        success: 是否成功触发
    """
    from datetime import datetime
    
    log_path = get_restart_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().isoformat()
    status = "SUCCESS" if success else "FAILED"
    
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(f"{timestamp} | PID:{pid} | {status} | {reason}\n")


def _open_restart_transaction(reason: str = "") -> Optional[str]:
    """为高风险重启动作打开演化事务。"""
    try:
        from core.infrastructure.git_memory import get_git_memory_service
        summary = f"restart_request: {reason}".strip()
        return get_git_memory_service().open_evolution_transaction(summary=summary)
    except Exception:
        return None


def _close_restart_transaction(txn_id: Optional[str], status: str, summary: str = "") -> None:
    """关闭重启事务；失败时静默降级，不影响主流程。"""
    if not txn_id:
        return
    try:
        from core.infrastructure.git_memory import get_git_memory_service
        get_git_memory_service().close_evolution_transaction(
            txn_id=txn_id,
            status=status,
            summary=summary,
        )
    except Exception:
        pass


def _restart_trigger_succeeded(result: str) -> bool:
    """判断重启触发是否成功。"""
    if not isinstance(result, str):
        return False
    lowered = result.lower()
    return not (
        lowered.startswith("错误")
        or lowered.startswith("[")
        or "启动重启进程失败" in result
        or "restarter 模块不可用" in result
    )


# ============================================================================
# 重启请求处理（与 Agent 逻辑解耦）
# ============================================================================

def handle_restart_request(
    tool_args: dict,
    messages: list,
    self_modified: bool,
) -> tuple:
    """
    统一处理 Agent 重启请求，整合任务清单检查、测试门控、世代归档。

    此函数将 agent.py 中 _handle_restart 的全部逻辑迁移至此，
    实现重启处理逻辑与 Agent 主类的解耦。

    Args:
        tool_args: 传递给 trigger_self_restart_tool 的参数，期望包含 `reason` 字段
        messages: 当前对话消息列表，用于提取中间步骤进行世代归档
        self_modified: 标记 Agent 是否自修改过，True 时会触发测试门控

    Returns:
        (result_message, action) 元组：
        - result_message: 操作结果或错误信息
        - action: "restart" 表示重启，None 表示被拦截
    """
    reason = str(tool_args.get("reason", "")).strip()
    txn_id = _open_restart_transaction(reason)

    # 任务清单拦截检查
    try:
        from tools.memory_tools import check_restart_block
        is_blocked, block_msg = check_restart_block()
        if is_blocked:
            debug_logger.warning("任务清单未完成，禁止重启", tag="TASK_BLOCK")
            _close_restart_transaction(txn_id, "cancelled", f"restart blocked: {block_msg}")
            return (block_msg, None)
    except Exception as e:
        debug_logger.error(f"任务清单检查失败: {e}", tag="TASK_BLOCK")

    # 环境烟雾门控（所有重启请求都必须通过）
    try:
        from core.infrastructure.test_gate import check_environment_ready
        passed, msg = check_environment_ready()
        if not passed:
            debug_logger.error("环境 smoke 门控失败，禁止重启", tag="ENV_GATE")
            _close_restart_transaction(txn_id, "failed", f"environment gate failed: {msg}")
            return (f"[ENVIRONMENT GATE FAILED] {msg}", None)
    except Exception as e:
        debug_logger.error(f"环境 smoke 门控执行失败: {e}", tag="ENV_GATE")
        _close_restart_transaction(txn_id, "failed", f"environment gate error: {e}")
        return (f"[ENVIRONMENT GATE ERROR] {e}", None)

    # 测试门控（仅当 Agent 产生过自我修改时触发）
    if self_modified:
        try:
            from core.infrastructure.test_gate import check_evolution_ready
            passed, msg = check_evolution_ready()
            if not passed:
                debug_logger.error("测试门控失败，禁止重启", tag="GATE")
                _close_restart_transaction(txn_id, "failed", f"test gate failed: {msg}")
                return (f"[TEST GATE FAILED] {msg}", None)
        except Exception as e:
            debug_logger.error(f"测试门控执行失败: {e}", tag="GATE")
            _close_restart_transaction(txn_id, "failed", f"test gate error: {e}")
            return (f"[TEST GATE ERROR] {e}", None)

    # 触发实际重启
    tool_result = trigger_self_restart_tool(**tool_args)
    if _restart_trigger_succeeded(tool_result):
        _close_restart_transaction(txn_id, "success", f"restart accepted: {reason}")
        return (tool_result, "restart")

    _close_restart_transaction(txn_id, "failed", f"restart trigger failed: {tool_result}")
    return (tool_result, None)


def enter_hibernation_tool(duration: int = 300) -> str:
    """
    让 Agent 进入休眠状态一段时间。

    休眠期间 Agent 不执行任何操作，等待指定时间后自动苏醒。
    适用于需要等待外部条件成熟的场景，如：
    - 等待代码部署完成
    - 等待外部服务就绪
    - 降低资源占用

    Args:
        duration: 休眠时长（秒），默认 300 秒（5 分钟）
                  建议范围：60 ~ 3600 秒

    Returns:
        操作结果描述字符串

    Example:
        >>> enter_hibernation(duration=60)
        '[休眠] 已进入休眠状态，60 秒后自动苏醒'
    """
    import time
    from datetime import datetime, timedelta

    if duration < 1:
        return "错误: 休眠时长必须大于 0 秒"

    if duration > 7200:
        return "错误: 休眠时长不能超过 7200 秒（2 小时）"

    wake_time = datetime.now() + timedelta(seconds=duration)
    debug_logger.info(f"[休眠] 进入休眠状态，时长: {duration} 秒，预计苏醒: {wake_time.strftime('%H:%M:%S')}")

    time.sleep(duration)

    return f"[苏醒] 休眠结束，已自动苏醒（休眠了 {duration} 秒）"
