"""
进程重启守护进程 - core/restarter_manager/restarter.py

此模块作为独立进程运行，负责管理 Agent 的重启生命周期。

工作流程：
1. 接收原 Agent 的 PID 和脚本路径作为命令行参数
2. 使用 psutil 轮询等待原进程结束
3. 原进程死亡后，使用 subprocess 拉起新的 Agent 进程
4. 支持 Windows 和 Unix 系统
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

# 跨平台支持
PLATFORM = sys.platform
IS_WINDOWS = PLATFORM == "win32"
IS_UNIX = PLATFORM in ("darwin", "linux", "freebsd")

# 尝试导入 psutil
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("警告: psutil 未安装，restarter 功能将受限")
    print("请运行: pip install psutil")


# ============================================================================
# 配置常量
# ============================================================================

# 轮询间隔（秒）
POLL_INTERVAL = 0.5

# 等待进程结束的最大超时时间（秒）
MAX_WAIT_TIME = 60

# 日志格式
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_console_encoding() -> None:
    """仅在真实 CLI 启动路径修复 Windows 控制台编码。"""
    if sys.platform != "win32":
        return

    import io

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue
        wrapped = io.TextIOWrapper(buffer, encoding="utf-8", errors="replace")
        setattr(sys, stream_name, wrapped)


# ============================================================================
# 日志配置
# ============================================================================

def setup_logging(verbose: bool = False) -> logging.Logger:
    """配置日志系统"""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        stream=sys.stdout
    )

    return logging.getLogger("Restarter")


# ============================================================================
# 核心功能函数
# ============================================================================

def parse_arguments() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Agent 进程重启守护进程",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m core.restarter_manager.restarter --pid 12345 --script ./agent.py
  python -m core.restarter_manager.restarter 12345 ./agent.py --verbose
        """
    )

    parser.add_argument('pid', nargs='?', type=int, help='要监控的原始 Agent 进程的 PID')
    parser.add_argument('script', nargs='?', type=str, help='Agent 脚本的路径')
    parser.add_argument('--pid', dest='pid_named', type=int, help='PID (命名参数)')
    parser.add_argument('--script', dest='script_named', type=str, help='脚本路径 (命名参数)')
    parser.add_argument('--env', dest='env_vars', action='append', help='环境变量 KEY=VALUE')
    parser.add_argument('-v', '--verbose', action='store_true', help='详细日志')

    args = parser.parse_args()

    # 合并位置参数和命名参数
    pid = args.pid or args.pid_named
    script = args.script or args.script_named

    if pid is None:
        parser.error("必须提供 PID")
    if script is None:
        parser.error("必须提供脚本路径")

    # 构建环境变��字典
    env_dict = {}
    if args.env_vars:
        for env_str in args.env_vars:
            if '=' in env_str:
                key, value = env_str.split('=', 1)
                env_dict[key] = value

    return argparse.Namespace(
        pid=pid,
        script=script,
        env_vars=env_dict,
        verbose=args.verbose
    )


def is_process_alive(pid: int) -> bool:
    """检查指定 PID 的进程是否仍在运行"""
    if not PSUTIL_AVAILABLE:
        if IS_WINDOWS:
            import subprocess
            try:
                result = subprocess.run(
                    ['taskkill', '/FI', f'PID eq {pid}', '/NR', 'FALSE'],
                    capture_output=True, text=True
                )
                return 'SUCCESS' in result.stdout or result.returncode == 0
            except Exception:
                return False
        else:
            import subprocess
            try:
                result = subprocess.run(['kill', '-0', str(pid)], capture_output=True, check=False)
                return result.returncode == 0
            except Exception:
                return False

    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def wait_for_process_death(
    pid: int,
    timeout: float = MAX_WAIT_TIME,
    poll_interval: float = POLL_INTERVAL,
    logger: Optional[logging.Logger] = None
) -> bool:
    """等待指定进程结束"""
    start_time = time.time()
    last_log_time = start_time

    while time.time() - start_time < timeout:
        if not is_process_alive(pid):
            elapsed = time.time() - start_time
            msg = f"进程 {pid} 已结束 (耗时 {elapsed:.2f} 秒)"
            if logger:
                logger.info(msg)
            else:
                print(msg)
            return True

        current_time = time.time()
        if current_time - last_log_time >= 5:
            elapsed = current_time - start_time
            msg = f"等待进程 {pid} 结束... (已等待 {elapsed:.1f} 秒)"
            if logger:
                logger.debug(msg)
            last_log_time = current_time

        time.sleep(poll_interval)

    msg = f"等待进程 {pid} 结束超时 ({timeout} 秒)"
    if logger:
        logger.warning(msg)
    else:
        print(f"警告: {msg}")
    return False


# 日志过滤：过滤 Rich UI 帧噪音，只保留有意义的日志行
_BOX_CHARS = set('─│┌┐└┘├┤┬┴┼═╬▀▄█▌▐░▒▓━┃┏┓┗┛┣┫┳┻╋')

_MAX_LOG_SIZE = 10 * 1024 * 1024  # 10MB


class _LogFilter:
    """过滤 Rich UI 帧，只写入有意义的日志行到日志文件"""

    def __init__(self, fp):
        self._fp = fp
        self._in_frame = False

    def write(self, s):
        if not s:
            return
        for line in s.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            # Rich 帧: 以 box-drawing 字符开头的行
            if stripped[0] in _BOX_CHARS:
                self._in_frame = True
                continue
            # Rich 帧内的状态行（非 [TAG] 开头）跳过
            if self._in_frame and not stripped.startswith('['):
                continue
            self._in_frame = False
            self._fp.write(line + '\n')
        self._fp.flush()

    def flush(self):
        self._fp.flush()


def _rotate_log_if_needed(log_path: str):
    """日志超过 10MB 时轮转: .log -> .log.1"""
    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > _MAX_LOG_SIZE:
            rotated = log_path + '.1'
            if os.path.exists(rotated):
                os.remove(rotated)
            os.rename(log_path, rotated)
    except OSError:
        pass


def spawn_new_process(
    script_path: str,
    env: Optional[dict] = None,
    logger: Optional[logging.Logger] = None
) -> Optional[int]:
    """启动新的 Agent 进程"""
    script_abs = os.path.abspath(script_path)

    if not os.path.exists(script_abs):
        msg = f"脚本文件不存在: {script_abs}"
        if logger:
            logger.error(msg)
        else:
            print(f"错误: {msg}")
        return None

    msg = f"启动新进程: {script_abs}"
    if logger:
        logger.info(msg)
    else:
        print(msg)

    try:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        restart_args: list[str] = []
        raw_restart_args = process_env.get("AGENT_RESTART_ARGS", "")
        if raw_restart_args:
            try:
                parsed = json.loads(raw_restart_args)
                if isinstance(parsed, list):
                    restart_args = [str(item) for item in parsed]
            except Exception:
                restart_args = []

        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'agent_realtime.log')

        _rotate_log_if_needed(log_file)

        import subprocess

        if IS_WINDOWS:
            creation_flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            with open(log_file, 'a', encoding='utf-8') as f:
                process = subprocess.Popen(
                    [sys.executable, script_abs, *restart_args],
                    env=process_env,
                    creationflags=creation_flags,
                    stdout=f,
                    stderr=subprocess.STDOUT
                )
            new_pid = process.pid
            logger.info(f"新进程已启动，PID: {new_pid}") if logger else print(f"新进程已启动，PID: {new_pid}")
            return new_pid
        else:
            # Unix: double-fork 守护进程化，完全脱离父进程
            pid = os.fork()
            if pid == 0:
                try:
                    pid = os.fork()
                    if pid == 0:
                        os.setsid()
                        os.chdir(log_dir)
                        with open(log_file, 'a') as f:
                            os.dup2(f.fileno(), 1)
                            os.dup2(f.fileno(), 2)
                        os.execvp(sys.executable, [sys.executable, script_abs, *restart_args])
                    else:
                        os._exit(0)
                except OSError as e:
                    os._exit(1)  # Fork failed, exit with error code 1
            else:
                os.waitpid(pid, 0)
                return None

    except Exception as e:
        msg = f"启动新进程失败: {e}"
        if logger:
            logger.error(msg)
        else:
            print(f"错误: {msg}")
        return None


def run_restarter(
    pid: int,
    script_path: str,
    env_vars: Optional[dict] = None,
    verbose: bool = False
) -> int:
    """运行重启守护进程的主要逻辑"""
    logger = setup_logging(verbose)

    logger.info("=" * 60)
    logger.info("Restarter 守护进程启动")
    logger.info("=" * 60)
    logger.info(f"监控进程 PID: {pid}")
    logger.info(f"目标脚本: {script_path}")

    if env_vars:
        logger.info(f"环境变量: {env_vars}")

    if is_process_alive(pid):
        logger.info(f"进程 {pid} 仍在运行，等待其结束...")
        if not wait_for_process_death(pid, logger=logger):
            logger.warning("等待超时，但将继续启动新进程")
    else:
        logger.info(f"进程 {pid} 已经不存在")

    logger.info("等待进程资源释放...")
    time.sleep(1)

    logger.info("-" * 40)
    new_pid = spawn_new_process(script_path, env_vars, logger)

    if new_pid:
        logger.info("-" * 40)
        logger.info(f"重启完成！新进程 PID: {new_pid}")
        logger.info("=" * 60)
        return 0
    else:
        logger.error("重启失败")
        logger.info("=" * 60)
        return 1


def main() -> int:
    """程序主入口点"""
    try:
        args = parse_arguments()
        return run_restarter(
            pid=args.pid,
            script_path=args.script,
            env_vars=args.env_vars,
            verbose=args.verbose
        )
    except KeyboardInterrupt:
        print("\n收到中断信号，守护进程退出")
        return 130
    except Exception as e:
        print(f"守护进程异常: {e}")
        return 1


if __name__ == "__main__":
    configure_console_encoding()
    sys.exit(main())
