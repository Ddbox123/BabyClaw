# -*- coding: utf-8 -*-
"""
core/infrastructure/cli_utils.py — CLI 辅助工具

职责：
- 命令行参数解析

从 agent.py 下沉，遵循 Core First 原则。
"""

from __future__ import annotations

import argparse
import os
from typing import Any, Dict

from config import AppConfig
from config.settings import Settings


def parse_args():
    """解析命令行参数。

    Returns:
        argparse.Namespace: 解析后的参数
    """
    parser = argparse.ArgumentParser(description="自我进化 Agent")
    parser.add_argument('-c', '--config', dest='config_path', help='配置文件路径')
    parser.add_argument('--awake-interval', type=int, dest='awake_interval', help='苏醒间隔（秒）')
    parser.add_argument('--model', dest='model_name', help='模型名称')
    parser.add_argument('--temperature', type=float, help='温度参数')
    parser.add_argument('--log-level', dest='log_level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='日志级别')
    parser.add_argument('--name', help='Agent 名称')
    parser.add_argument('--max-iterations', type=int, dest='max_iterations', help='单轮最大迭代步数')
    parser.add_argument('--profile', choices=['safe_local', 'safe_remote', 'debug', 'ci'], help='稳定运行档案')
    parser.add_argument('--skip-doctor', action='store_true', help='跳过启动前 doctor 自检')
    parser.add_argument('--test', action='store_true', help='运行首次进化测试')
    parser.add_argument('--prompt', type=str, default=None, help='初始任务提示')
    parser.add_argument('--auto', action='store_true', help='自动模式（无交互）')
    parser.add_argument('--single-turn', action='store_true', help='仅执行一轮 think_and_act 后退出')
    parser.add_argument('--subagent-json', action='store_true', help='子代理模式：单轮执行后输出结构化 JSON 标记')
    parser.add_argument('--shell', action='store_true', help='进入统一工作台')
    parser.add_argument('--no-shell', action='store_true', help='跳过统一工作台，直接运行 agent')
    parser.add_argument('--supervised-evolution', action='store_true', help='从统一入口运行监督进化')
    parser.add_argument('--post-restart-observe-seconds', type=int, default=20, help='harness 重启后观察秒数')
    parser.add_argument('--bundle', default=None, help='监督进化 bundle 名称')
    parser.add_argument('--dataset', default=None, help='监督进化数据集名称')
    parser.add_argument('--choose-dataset', action='store_true', help='在统一入口中交互选择监督进化数据集')
    parser.add_argument('--dataset-limit', type=int, default=None, help='物化数据集时最多导入多少条 case')
    parser.add_argument('--list-datasets', action='store_true', help='列出监督进化可选数据集')
    parser.add_argument('--keep-worktree', action='store_true', help='监督进化运行后保留 harness worktree')
    parser.add_argument('--supervised-dashboard', action='store_true', help='生成监督进化进展页面')
    return parser.parse_args()


def build_config_kwargs(args) -> Dict[str, Any]:
    """从命令行参数构建配置覆盖。"""
    config_kwargs = {}
    if getattr(args, "model_name", None) is not None:
        config_kwargs["llm.profiles.primary.model"] = args.model_name
    if getattr(args, "temperature", None) is not None:
        config_kwargs["llm.profiles.primary.temperature"] = args.temperature
    if getattr(args, "awake_interval", None) is not None:
        config_kwargs["agent.awake_interval"] = args.awake_interval
    if getattr(args, "max_iterations", None) is not None:
        config_kwargs["agent.max_iterations"] = args.max_iterations
    if getattr(args, "name", None) is not None:
        config_kwargs["agent.name"] = args.name
    if getattr(args, "log_level", None) is not None:
        config_kwargs["log.level"] = args.log_level
    if getattr(args, "profile", None) is not None:
        config_kwargs["runtime.profile"] = args.profile
    if getattr(args, "skip_doctor", False):
        config_kwargs["runtime.preflight_doctor"] = False
    return config_kwargs


def create_config_from_args(args) -> AppConfig:
    """基于解析后的参数创建配置对象。"""
    return Settings(
        config_path=getattr(args, "config_path", None),
        **build_config_kwargs(args),
    ).config


def should_launch_workbench(args, initial_prompt: str | None) -> bool:
    """判断是否进入统一工作台。"""
    if getattr(args, "test", False):
        return False
    if getattr(args, "supervised_evolution", False):
        return False
    if (
        getattr(args, "dataset", None)
        or getattr(args, "choose_dataset", False)
        or getattr(args, "list_datasets", False)
        or getattr(args, "supervised_dashboard", False)
    ):
        return False
    if getattr(args, "auto", False):
        return False
    if os.getenv("AGENT_RESTART_REASON"):
        return False
    if initial_prompt:
        return False
    if getattr(args, "no_shell", False):
        return False
    if getattr(args, "shell", False):
        return True
    return True
