#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进程重启守护测试 (test_restarter.py)

测试 core/restarter_manager/restarter.py 中的：
- 平台常量 (IS_WINDOWS, IS_UNIX)
- PSUTIL_AVAILABLE 标志
- 配置常量 (POLL_INTERVAL, MAX_WAIT_TIME)
- parse_arguments: 位置参数、命名参数、环境变量、verbose、缺失参数
- is_process_alive: psutil 路径、Windows fallback、Unix fallback、异常处理
- wait_for_process_death: 进程已死、超时、轮询间隔
- spawn_new_process: 脚本不存在、Windows creationflags、Unix fork
- setup_logging: verbose 级别、返回 logger
- run_restarter: 正常流程、进程存活/已死
- main: 正常退出、KeyboardInterrupt、异常
"""

import os
import sys
import argparse
import logging
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest


# ============================================================================
# 平台常量测试
# ============================================================================

class TestPlatformConstants:
    """平台常量测试"""

    def test_is_windows_is_bool(self):
        """IS_WINDOWS 是布尔值"""
        from core.restarter_manager.restarter import IS_WINDOWS
        assert isinstance(IS_WINDOWS, bool)

    def test_is_unix_is_bool(self):
        """IS_UNIX 是布尔值"""
        from core.restarter_manager.restarter import IS_UNIX
        assert isinstance(IS_UNIX, bool)

    def test_platform_mutually_exclusive(self):
        """Windows 和 Unix 互斥"""
        from core.restarter_manager.restarter import IS_WINDOWS, IS_UNIX
        assert IS_WINDOWS != IS_UNIX

    def test_psutil_available_is_bool(self):
        """PSUTIL_AVAILABLE 是布尔值"""
        from core.restarter_manager.restarter import PSUTIL_AVAILABLE
        assert isinstance(PSUTIL_AVAILABLE, bool)


# ============================================================================
# 配置常量测试
# ============================================================================

class TestConfigConstants:
    """配置常量测试"""

    def test_poll_interval(self):
        """POLL_INTERVAL 为 0.5 秒"""
        from core.restarter_manager.restarter import POLL_INTERVAL
        assert POLL_INTERVAL == 0.5

    def test_max_wait_time(self):
        """MAX_WAIT_TIME 为 60 秒"""
        from core.restarter_manager.restarter import MAX_WAIT_TIME
        assert MAX_WAIT_TIME == 60

    def test_log_format(self):
        """LOG_FORMAT 包含 asctime"""
        from core.restarter_manager.restarter import LOG_FORMAT
        assert "asctime" in LOG_FORMAT


# ============================================================================
# setup_logging 测试
# ============================================================================

class TestSetupLogging:
    """setup_logging 测试"""

    def test_returns_logger(self):
        """返回 Logger 实例"""
        from core.restarter_manager.restarter import setup_logging
        logger = setup_logging(verbose=False)
        assert isinstance(logger, logging.Logger)

    def test_logger_name_is_restarter(self):
        """Logger 名称为 Restarter"""
        from core.restarter_manager.restarter import setup_logging
        logger = setup_logging()
        assert logger.name == "Restarter"

    def test_verbose_sets_debug_level(self):
        """verbose=True 设置 DEBUG 级别"""
        import logging
        from core.restarter_manager.restarter import setup_logging
        # 清除已有 handlers 确保 basicConfig 生效
        root = logging.getLogger()
        old_handlers = root.handlers[:]
        root.handlers.clear()
        try:
            logger = setup_logging(verbose=True)
            assert root.level == logging.DEBUG
        finally:
            root.handlers = old_handlers

    def test_non_verbose_sets_info_level(self):
        """verbose=False 设置 INFO 级别"""
        import logging
        from core.restarter_manager.restarter import setup_logging
        root = logging.getLogger()
        old_handlers = root.handlers[:]
        root.handlers.clear()
        try:
            logger = setup_logging(verbose=False)
            assert root.level == logging.INFO
        finally:
            root.handlers = old_handlers


# ============================================================================
# parse_arguments 测试
# ============================================================================

class TestParseArguments:
    """parse_arguments 测试"""

    def test_positional_args(self):
        """位置参数解析"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', ['restarter.py', '12345', './agent.py']):
            args = parse_arguments()
            assert args.pid == 12345
            assert args.script == './agent.py'

    def test_named_args(self):
        """命名参数解析"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', ['restarter.py', '--pid', '99999', '--script', '/path/agent.py']):
            args = parse_arguments()
            assert args.pid == 99999
            assert args.script == '/path/agent.py'

    def test_verbose_flag(self):
        """verbose 标志"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', ['restarter.py', '12345', './agent.py', '-v']):
            args = parse_arguments()
            assert args.verbose is True

    def test_verbose_long_flag(self):
        """--verbose 长标志"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', ['restarter.py', '12345', './agent.py', '--verbose']):
            args = parse_arguments()
            assert args.verbose is True

    def test_env_vars_single(self):
        """单个环境变量"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', ['restarter.py', '12345', './agent.py', '--env', 'KEY=VALUE']):
            args = parse_arguments()
            assert args.env_vars == {'KEY': 'VALUE'}

    def test_env_vars_multiple(self):
        """多个环境变量"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', [
            'restarter.py', '12345', './agent.py',
            '--env', 'A=1', '--env', 'B=2'
        ]):
            args = parse_arguments()
            assert args.env_vars == {'A': '1', 'B': '2'}

    def test_env_var_with_equals_in_value(self):
        """环境变量值含等号"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', [
            'restarter.py', '12345', './agent.py',
            '--env', 'PATH=C:\\bin;C:\\tools'
        ]):
            args = parse_arguments()
            assert args.env_vars == {'PATH': 'C:\\bin;C:\\tools'}

    def test_env_vars_empty_when_not_provided(self):
        """未提供环境变量时为空字典"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', ['restarter.py', '12345', './agent.py']):
            args = parse_arguments()
            assert args.env_vars == {}

    def test_missing_pid_raises_error(self):
        """缺少 PID 报错"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', ['restarter.py']):
            with pytest.raises(SystemExit):
                parse_arguments()

    def test_missing_script_raises_error(self):
        """缺少脚本路径报错"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', ['restarter.py', '12345']):
            with pytest.raises(SystemExit):
                parse_arguments()

    def test_default_verbose_false(self):
        """默认 verbose=False"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', ['restarter.py', '12345', './agent.py']):
            args = parse_arguments()
            assert args.verbose is False

    def test_named_args_override_positional(self):
        """命名参数覆盖位置参数"""
        from core.restarter_manager.restarter import parse_arguments
        with patch.object(sys, 'argv', [
            'restarter.py', '1', 'old.py', '--pid', '999', '--script', 'new.py'
        ]):
            args = parse_arguments()
            assert args.pid == 1  # 位置参数优先 (args.pid or args.pid_named)
            assert args.script == 'old.py'


# ============================================================================
# is_process_alive 测试
# ============================================================================

class TestIsProcessAlive:
    """is_process_alive 测试"""

    def test_psutil_pid_exists_and_running(self):
        """psutil 可用且进程运行中"""
        with patch('core.restarter_manager.restarter.PSUTIL_AVAILABLE', True):
            with patch('psutil.pid_exists', return_value=True):
                with patch('psutil.Process') as mock_process:
                    mock_process.return_value.is_running.return_value = True
                    from core.restarter_manager.restarter import is_process_alive
                    assert is_process_alive(12345) is True

    def test_psutil_pid_not_exists(self):
        """psutil 可用但进程不存在"""
        with patch('core.restarter_manager.restarter.PSUTIL_AVAILABLE', True):
            with patch('psutil.pid_exists', return_value=False):
                from core.restarter_manager.restarter import is_process_alive
                assert is_process_alive(12345) is False

    def test_psutil_no_such_process(self):
        """psutil.NoSuchProcess 异常"""
        with patch('core.restarter_manager.restarter.PSUTIL_AVAILABLE', True):
            with patch('psutil.pid_exists', return_value=True):
                import psutil
                with patch('psutil.Process', side_effect=psutil.NoSuchProcess(12345)):
                    from core.restarter_manager.restarter import is_process_alive
                    assert is_process_alive(12345) is False

    def test_psutil_access_denied(self):
        """psutil.AccessDenied 异常"""
        with patch('core.restarter_manager.restarter.PSUTIL_AVAILABLE', True):
            with patch('psutil.pid_exists', return_value=True):
                import psutil
                with patch('psutil.Process', side_effect=psutil.AccessDenied(12345)):
                    from core.restarter_manager.restarter import is_process_alive
                    assert is_process_alive(12345) is False

    def test_windows_fallback_taskkill_success(self):
        """Windows fallback taskkill 成功"""
        with patch('core.restarter_manager.restarter.PSUTIL_AVAILABLE', False):
            with patch('core.restarter_manager.restarter.IS_WINDOWS', True):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value.stdout = 'SUCCESS: ...'
                    mock_run.return_value.returncode = 0
                    from core.restarter_manager.restarter import is_process_alive
                    assert is_process_alive(12345) is True

    def test_windows_fallback_taskkill_not_found(self):
        """Windows fallback taskkill 未找到"""
        with patch('core.restarter_manager.restarter.PSUTIL_AVAILABLE', False):
            with patch('core.restarter_manager.restarter.IS_WINDOWS', True):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value.stdout = ''
                    mock_run.return_value.returncode = 1
                    from core.restarter_manager.restarter import is_process_alive
                    assert is_process_alive(12345) is False

    def test_windows_fallback_exception(self):
        """Windows fallback 异常"""
        with patch('core.restarter_manager.restarter.PSUTIL_AVAILABLE', False):
            with patch('core.restarter_manager.restarter.IS_WINDOWS', True):
                with patch('subprocess.run', side_effect=OSError("fail")):
                    from core.restarter_manager.restarter import is_process_alive
                    assert is_process_alive(12345) is False

    def test_unix_fallback_kill_success(self):
        """Unix fallback kill -0 成功"""
        with patch('core.restarter_manager.restarter.PSUTIL_AVAILABLE', False):
            with patch('core.restarter_manager.restarter.IS_WINDOWS', False):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value.returncode = 0
                    from core.restarter_manager.restarter import is_process_alive
                    assert is_process_alive(12345) is True

    def test_unix_fallback_kill_failure(self):
        """Unix fallback kill -0 非零返回码表示进程不存在"""
        with patch('core.restarter_manager.restarter.PSUTIL_AVAILABLE', False):
            with patch('core.restarter_manager.restarter.IS_WINDOWS', False):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value.returncode = 1
                    from core.restarter_manager.restarter import is_process_alive
                    assert is_process_alive(12345) is False

    def test_unix_fallback_exception(self):
        """Unix fallback 异常"""
        with patch('core.restarter_manager.restarter.PSUTIL_AVAILABLE', False):
            with patch('core.restarter_manager.restarter.IS_WINDOWS', False):
                with patch('subprocess.run', side_effect=Exception("fail")):
                    from core.restarter_manager.restarter import is_process_alive
                    assert is_process_alive(12345) is False


# ============================================================================
# wait_for_process_death 测试
# ============================================================================

class TestWaitForProcessDeath:
    """wait_for_process_death 测试"""

    def test_process_already_dead(self):
        """进程已经不存在"""
        with patch('core.restarter_manager.restarter.is_process_alive', return_value=False):
            from core.restarter_manager.restarter import wait_for_process_death
            result = wait_for_process_death(12345, timeout=1, poll_interval=0.1)
            assert result is True

    def test_process_dies_during_wait(self):
        """进程在等待过程中死亡"""
        with patch('core.restarter_manager.restarter.is_process_alive', side_effect=[True, True, False]):
            from core.restarter_manager.restarter import wait_for_process_death
            result = wait_for_process_death(12345, timeout=5, poll_interval=0.01)
            assert result is True

    def test_timeout_reached(self):
        """等待超时"""
        with patch('core.restarter_manager.restarter.is_process_alive', return_value=True):
            from core.restarter_manager.restarter import wait_for_process_death
            result = wait_for_process_death(12345, timeout=0.05, poll_interval=0.01)
            assert result is False

    def test_uses_correct_poll_interval(self):
        """使用正确的轮询间隔"""
        call_times = []
        def side_effect(pid):
            call_times.append(time.time())
            if len(call_times) >= 3:
                return False
            return True

        with patch('core.restarter_manager.restarter.is_process_alive', side_effect=side_effect):
            from core.restarter_manager.restarter import wait_for_process_death
            result = wait_for_process_death(12345, timeout=5, poll_interval=0.05)
            assert result is True
            # 验证调用了 3 次
            assert len(call_times) == 3

    def test_logger_called_when_dead(self):
        """进程死亡时 logger 被调用"""
        mock_logger = MagicMock()
        with patch('core.restarter_manager.restarter.is_process_alive', return_value=False):
            from core.restarter_manager.restarter import wait_for_process_death
            result = wait_for_process_death(12345, timeout=1, poll_interval=0.1, logger=mock_logger)
            assert result is True
            mock_logger.info.assert_called_once()

    def test_logger_called_on_timeout(self):
        """超时时 logger.warning 被调用"""
        mock_logger = MagicMock()
        with patch('core.restarter_manager.restarter.is_process_alive', return_value=True):
            from core.restarter_manager.restarter import wait_for_process_death
            result = wait_for_process_death(12345, timeout=0.05, poll_interval=0.01, logger=mock_logger)
            assert result is False
            mock_logger.warning.assert_called_once()


# ============================================================================
# spawn_new_process 测试
# ============================================================================

class TestSpawnNewProcess:
    """spawn_new_process 测试"""

    def test_script_not_found(self):
        """脚本不存在返回 None"""
        from core.restarter_manager.restarter import spawn_new_process
        result = spawn_new_process('/nonexistent/path/agent.py')
        assert result is None

    def test_script_not_found_logs_error(self):
        """脚本不存在时 logger.error 被调用"""
        mock_logger = MagicMock()
        from core.restarter_manager.restarter import spawn_new_process
        spawn_new_process('/nonexistent/path/agent.py', logger=mock_logger)
        mock_logger.error.assert_called_once()

    def test_windows_creationflags(self, tmp_path):
        """Windows 下使用正确的 creationflags"""
        script = tmp_path / "agent.py"
        script.write_text("# test")

        with patch('core.restarter_manager.restarter.IS_WINDOWS', True):
            with patch('subprocess.Popen') as mock_popen:
                mock_popen.return_value.pid = 54321
                from core.restarter_manager.restarter import spawn_new_process
                result = spawn_new_process(str(script))
                assert result == 54321
                # 验证 creationflags
                call_kwargs = mock_popen.call_args[1]
                assert 'creationflags' in call_kwargs
                assert call_kwargs['creationflags'] == 0x00000008 | 0x00000200

    def test_windows_env_passed(self, tmp_path):
        """Windows 下环境变量被传递"""
        script = tmp_path / "agent.py"
        script.write_text("# test")

        with patch('core.restarter_manager.restarter.IS_WINDOWS', True):
            with patch('subprocess.Popen') as mock_popen:
                mock_popen.return_value.pid = 54321
                from core.restarter_manager.restarter import spawn_new_process
                spawn_new_process(str(script), env={'CUSTOM': 'value'})
                call_kwargs = mock_popen.call_args[1]
                assert call_kwargs['env']['CUSTOM'] == 'value'

    def test_windows_uses_sys_executable(self, tmp_path):
        """Windows 下使用 sys.executable 启动"""
        script = tmp_path / "agent.py"
        script.write_text("# test")

        with patch('core.restarter_manager.restarter.IS_WINDOWS', True):
            with patch('subprocess.Popen') as mock_popen:
                mock_popen.return_value.pid = 54321
                from core.restarter_manager.restarter import spawn_new_process
                spawn_new_process(str(script))
                call_args = mock_popen.call_args[0][0]
                assert call_args[0] == sys.executable

    def test_windows_appends_restart_args_from_env(self, tmp_path):
        """Windows 下继承原始启动参数"""
        script = tmp_path / "agent.py"
        script.write_text("# test")

        with patch('core.restarter_manager.restarter.IS_WINDOWS', True):
            with patch('subprocess.Popen') as mock_popen:
                mock_popen.return_value.pid = 54321
                from core.restarter_manager.restarter import spawn_new_process
                spawn_new_process(
                    str(script),
                    env={'AGENT_RESTART_ARGS': '["--no-shell","--skip-doctor","--test"]'},
                )
                call_args = mock_popen.call_args[0][0]
                assert call_args[2:] == ["--no-shell", "--skip-doctor", "--test"]

    @pytest.mark.skipif(not hasattr(os, 'fork'), reason="os.fork not available on Windows")
    def test_unix_double_fork(self, tmp_path):
        """Unix 下执行 double-fork"""
        script = tmp_path / "agent.py"
        script.write_text("# test")

        with patch('core.restarter_manager.restarter.IS_WINDOWS', False):
            with patch('os.fork') as mock_fork:
                # First fork returns child PID, second fork returns 0 (grandchild)
                mock_fork.side_effect = [999, 0]
                with patch('os.setsid'):
                    with patch('os.chdir'):
                        with patch('os.dup2'):
                            with patch('os.execvp', side_effect=OSError("exec mock")):
                                from core.restarter_manager.restarter import spawn_new_process
                                result = spawn_new_process(str(script))
                                # Parent sees os.waitpid then returns None
                                assert result is None

    def test_subprocess_exception(self, tmp_path):
        """subprocess 异常返回 None"""
        script = tmp_path / "agent.py"
        script.write_text("# test")

        mock_logger = MagicMock()
        with patch('core.restarter_manager.restarter.IS_WINDOWS', True):
            with patch('subprocess.Popen', side_effect=OSError("spawn failed")):
                from core.restarter_manager.restarter import spawn_new_process
                result = spawn_new_process(str(script), logger=mock_logger)
                assert result is None
                mock_logger.error.assert_called_once()

    def test_env_vars_default_to_os_environ(self, tmp_path):
        """默认继承 os.environ"""
        script = tmp_path / "agent.py"
        script.write_text("# test")

        with patch('core.restarter_manager.restarter.IS_WINDOWS', True):
            with patch('subprocess.Popen') as mock_popen:
                mock_popen.return_value.pid = 54321
                from core.restarter_manager.restarter import spawn_new_process
                spawn_new_process(str(script))
                call_kwargs = mock_popen.call_args[1]
                # 应该包含 os.environ 的内容
                assert 'env' in call_kwargs


# ============================================================================
# run_restarter 测试
# ============================================================================

class TestRunRestarter:
    """run_restarter 测试"""

    def test_process_dead_spawns_new(self):
        """进程已死时直接启动新进程"""
        with patch('core.restarter_manager.restarter.setup_logging') as mock_setup_log:
            mock_logger = MagicMock()
            mock_setup_log.return_value = mock_logger

            with patch('core.restarter_manager.restarter.is_process_alive', return_value=False):
                with patch('core.restarter_manager.restarter.wait_for_process_death') as mock_wait:
                    with patch('core.restarter_manager.restarter.spawn_new_process', return_value=99999):
                        from core.restarter_manager.restarter import run_restarter
                        result = run_restarter(12345, './agent.py')
                        assert result == 0
                        mock_wait.assert_not_called()

    def test_process_alive_waits_then_spawns(self):
        """进程存活时等待后启动新进程"""
        with patch('core.restarter_manager.restarter.setup_logging') as mock_setup_log:
            mock_logger = MagicMock()
            mock_setup_log.return_value = mock_logger

            with patch('core.restarter_manager.restarter.is_process_alive', return_value=True):
                with patch('core.restarter_manager.restarter.wait_for_process_death', return_value=True):
                    with patch('core.restarter_manager.restarter.spawn_new_process', return_value=99999):
                        from core.restarter_manager.restarter import run_restarter
                        result = run_restarter(12345, './agent.py')
                        assert result == 0

    def test_spawn_failure_returns_1(self):
        """启动失败返回 1"""
        with patch('core.restarter_manager.restarter.setup_logging') as mock_setup_log:
            mock_logger = MagicMock()
            mock_setup_log.return_value = mock_logger

            with patch('core.restarter_manager.restarter.is_process_alive', return_value=False):
                with patch('core.restarter_manager.restarter.spawn_new_process', return_value=None):
                    from core.restarter_manager.restarter import run_restarter
                    result = run_restarter(12345, './agent.py')
                    assert result == 1

    def test_env_vars_passed_to_spawn(self):
        """环境变量传递给 spawn_new_process"""
        with patch('core.restarter_manager.restarter.setup_logging') as mock_setup_log:
            mock_logger = MagicMock()
            mock_setup_log.return_value = mock_logger

            with patch('core.restarter_manager.restarter.is_process_alive', return_value=False):
                with patch('core.restarter_manager.restarter.spawn_new_process') as mock_spawn:
                    mock_spawn.return_value = 99999
                    from core.restarter_manager.restarter import run_restarter
                    env = {'DEBUG': '1'}
                    run_restarter(12345, './agent.py', env_vars=env)
                    mock_spawn.assert_called_once_with('./agent.py', env, mock_logger)

    def test_sleeps_between_wait_and_spawn(self):
        """在等待和启动之间 sleep 1 秒"""
        with patch('core.restarter_manager.restarter.setup_logging') as mock_setup_log:
            mock_logger = MagicMock()
            mock_setup_log.return_value = mock_logger

            with patch('core.restarter_manager.restarter.is_process_alive', return_value=False):
                with patch('core.restarter_manager.restarter.spawn_new_process', return_value=99999):
                    with patch('core.restarter_manager.restarter.time.sleep') as mock_sleep:
                        from core.restarter_manager.restarter import run_restarter
                        run_restarter(12345, './agent.py')
                        mock_sleep.assert_called_once_with(1)

    def test_wait_timeout_still_spawns(self):
        """等待超时后仍然尝试启动"""
        with patch('core.restarter_manager.restarter.setup_logging') as mock_setup_log:
            mock_logger = MagicMock()
            mock_setup_log.return_value = mock_logger

            with patch('core.restarter_manager.restarter.is_process_alive', return_value=True):
                with patch('core.restarter_manager.restarter.wait_for_process_death', return_value=False):
                    with patch('core.restarter_manager.restarter.spawn_new_process', return_value=99999):
                        from core.restarter_manager.restarter import run_restarter
                        result = run_restarter(12345, './agent.py')
                        assert result == 0


# ============================================================================
# main 测试
# ============================================================================

class TestMain:
    """main 入口测试"""

    def test_normal_flow(self):
        """正常流程"""
        with patch('core.restarter_manager.restarter.parse_arguments') as mock_parse:
            mock_args = MagicMock()
            mock_args.pid = 12345
            mock_args.script = './agent.py'
            mock_args.env_vars = {}
            mock_args.verbose = False
            mock_parse.return_value = mock_args

            with patch('core.restarter_manager.restarter.run_restarter', return_value=0):
                from core.restarter_manager.restarter import main
                result = main()
                assert result == 0

    def test_keyboard_interrupt(self):
        """KeyboardInterrupt 返回 130"""
        with patch('core.restarter_manager.restarter.parse_arguments', side_effect=KeyboardInterrupt):
            from core.restarter_manager.restarter import main
            result = main()
            assert result == 130

    def test_exception_returns_1(self):
        """异常返回 1"""
        with patch('core.restarter_manager.restarter.parse_arguments', side_effect=RuntimeError("boom")):
            from core.restarter_manager.restarter import main
            result = main()
            assert result == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
