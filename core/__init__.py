"""
core - 核心模块包

目录结构 (当前):
- infrastructure/   : 基础设施 (工具执行、状态、事件、安全、模型发现、工作区)
- orchestration/    : 任务编排 (TaskManager)
- logging/          : 日志系统 (调试日志、统一日志、转录日志、工具追踪)
- ui/               : 交互界面 (ASCII 艺术、CLI UI、交互式 CLI、主题)
- pet_system/       : 宠物系统 (心情、饥饿、心跳、梦境等子系统)
- core_prompt/      : 核心提示词 (双轨加载: 静态 SOUL/SPEC + 动态 workspace 覆盖)
- prompt_manager/   : 提示词管理器 (动态拼装、任务分析、代码库地图)
- restarter_manager/: 重启守护进程

"""

# 标记重组版本
__version__ = "4.4"
CORE_REORGANIZED = True
CORE_REORGANIZE_DATE = "2026-04-18"
