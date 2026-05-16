#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务分析器 (TaskAnalyzer) - 分析任务完成情况并生成复盘报告

负责：
- 分析任务执行情况
- 识别任务执行中的问题
- 生成复盘报告
- 提取成功模式和失败教训

Phase 2 核心模块
"""

from __future__ import annotations

import os
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ============================================================================
# 枚举定义
# ============================================================================

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskComplexity(Enum):
    """任务复杂度"""
    TRIVIAL = "trivial"      # 简单
    EASY = "easy"            # 容易
    MEDIUM = "medium"        # 中等
    COMPLEX = "complex"      # 复杂
    VERY_COMPLEX = "very_complex"  # 非常复杂


@dataclass
class TaskRecord:
    """任务记录"""
    task_id: int
    description: str
    status: str
    complexity: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    subtasks: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskAnalysisReport:
    """任务分析报告"""
    timestamp: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    completion_rate: float
    avg_duration: float
    success_patterns: List[str]
    failure_patterns: List[str]
    recommendations: List[str]
    task_records: List[TaskRecord]


@dataclass
class EvolutionSessionReport:
    """单次进化会话的结果分析报告。"""

    session_id: str
    source_file: str
    generated_at: str
    started_at: str
    ended_at: str
    uptime_seconds: float
    total_turns: int
    total_tool_calls: int
    total_llm_responses: int
    total_validation_checks: int
    goal: str
    outcome: str
    outcome_reason: str
    key_actions: List[str]
    validations: List[Dict[str, Any]]
    blockers: List[Dict[str, Any]]
    notable_states: List[str]
    repeated_failure_patterns: List[str]
    tool_misuse_patterns: List[str]
    diagnostic_drift_detected: bool
    language_drift_detected: bool
    next_round_constraints: List[str]
    recommendations: List[str]


# ============================================================================
# 任务分析器
# ============================================================================

class TaskAnalyzer:
    """
    任务分析器

    分析任务执行情况，提取模式和教训。
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化任务分析器

        Args:
            project_root: 项目根目录路径
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 分析结果存储路径
        self._analysis_dir = self.project_root / "workspace" / "analytics"
        self._analysis_dir.mkdir(parents=True, exist_ok=True)

        # 任务历史记录
        self._task_history: List[TaskRecord] = []

    # =========================================================================
    # 任务记录
    # =========================================================================

    def record_task_start(
        self,
        task_id: int,
        description: str,
        complexity: str = "medium",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        记录任务开始

        Args:
            task_id: 任务 ID
            description: 任务描述
            complexity: 复杂度
            metadata: 元数据
        """
        record = TaskRecord(
            task_id=task_id,
            description=description,
            status=TaskStatus.IN_PROGRESS.value,
            complexity=complexity,
            start_time=datetime.now().isoformat(),
            metadata=metadata or {},
        )
        self._task_history.append(record)

    def record_task_completion(
        self,
        task_id: int,
        insights: Optional[List[str]] = None,
    ) -> None:
        """
        记录任务完成

        Args:
            task_id: 任务 ID
            insights: 任务洞察
        """
        for record in reversed(self._task_history):
            if record.task_id == task_id:
                record.status = TaskStatus.COMPLETED.value
                record.end_time = datetime.now().isoformat()

                if record.start_time:
                    start = datetime.fromisoformat(record.start_time)
                    end = datetime.now()
                    record.duration_seconds = (end - start).total_seconds()

                if insights:
                    record.insights.extend(insights)

                break

    def record_task_failure(
        self,
        task_id: int,
        error: str,
    ) -> None:
        """
        记录任务失败

        Args:
            task_id: 任务 ID
            error: 错误信息
        """
        for record in reversed(self._task_history):
            if record.task_id == task_id:
                record.status = TaskStatus.FAILED.value
                record.end_time = datetime.now().isoformat()
                record.errors.append(error)

                if record.start_time:
                    start = datetime.fromisoformat(record.start_time)
                    end = datetime.now()
                    record.duration_seconds = (end - start).total_seconds()

                break

    def record_tool_call(
        self,
        task_id: int,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        result: Optional[str] = None,
        success: bool = True,
    ) -> None:
        """
        记录工具调用

        Args:
            task_id: 任务 ID
            tool_name: 工具名称
            args: 工具参数
            result: 执行结果
            success: 是否成功
        """
        for record in reversed(self._task_history):
            if record.task_id == task_id:
                record.tool_calls.append({
                    "tool": tool_name,
                    "args": args or {},
                    "result": result,
                    "success": success,
                    "timestamp": datetime.now().isoformat(),
                })
                break

    # =========================================================================
    # 分析接口
    # =========================================================================

    def analyze_tasks(
        self,
        task_records: Optional[List[Dict[str, Any]]] = None,
    ) -> TaskAnalysisReport:
        """
        分析任务执行情况

        Args:
            task_records: 任务记录列表（可选，用于外部传入）

        Returns:
            任务分析报告
        """
        # 使用提供的记录或历史记录
        if task_records is None:
            task_records = [self._record_to_dict(r) for r in self._task_history]

        # 转换记录
        records = []
        for rec in task_records:
            records.append(TaskRecord(
                task_id=rec.get("task_id", 0),
                description=rec.get("description", ""),
                status=rec.get("status", TaskStatus.PENDING.value),
                complexity=rec.get("complexity", "medium"),
                start_time=rec.get("start_time"),
                end_time=rec.get("end_time"),
                duration_seconds=rec.get("duration_seconds", 0.0),
                subtasks=rec.get("subtasks", []),
                tool_calls=rec.get("tool_calls", []),
                errors=rec.get("errors", []),
                insights=rec.get("insights", []),
                metadata=rec.get("metadata", {}),
            ))

        # 统计
        total = len(records)
        completed = len([r for r in records if r.status == TaskStatus.COMPLETED.value])
        failed = len([r for r in records if r.status == TaskStatus.FAILED.value])

        # 计算完成率
        completion_rate = completed / total if total > 0 else 0.0

        # 计算平均时长
        completed_records = [r for r in records if r.duration_seconds > 0]
        avg_duration = (
            sum(r.duration_seconds for r in completed_records) / len(completed_records)
            if completed_records else 0.0
        )

        # 识别成功模式
        success_patterns = self._identify_success_patterns(records)

        # 识别失败模式
        failure_patterns = self._identify_failure_patterns(records)

        # 生成建议
        recommendations = self._generate_recommendations(
            records, success_patterns, failure_patterns
        )

        return TaskAnalysisReport(
            timestamp=datetime.now().isoformat(),
            total_tasks=total,
            completed_tasks=completed,
            failed_tasks=failed,
            completion_rate=completion_rate,
            avg_duration=avg_duration,
            success_patterns=success_patterns,
            failure_patterns=failure_patterns,
            recommendations=recommendations,
            task_records=records,
        )

    def generate_retrospective(self) -> str:
        """
        生成任务复盘报告

        Returns:
            Markdown 格式的复盘报告
        """
        report = self.analyze_tasks()

        lines = [
            "# 任务执行复盘报告",
            "",
            f"**生成时间**: {report.timestamp}",
            "",
            "---",
            "",
            "## 执行概览",
            "",
            f"- **总任务数**: {report.total_tasks}",
            f"- **已完成**: {report.completed_tasks}",
            f"- **失败**: {report.failed_tasks}",
            f"- **完成率**: {report.completion_rate:.0%}",
            f"- **平均耗时**: {self._format_duration(report.avg_duration)}",
            "",
        ]

        # 成功模式
        if report.success_patterns:
            lines.extend([
                "## 成功模式",
                "",
            ])
            for pattern in report.success_patterns:
                lines.append(f"- {pattern}")
            lines.append("")

        # 失败模式
        if report.failure_patterns:
            lines.extend([
                "## 失败模式",
                "",
            ])
            for pattern in report.failure_patterns:
                lines.append(f"- {pattern}")
            lines.append("")

        # 建议
        if report.recommendations:
            lines.extend([
                "## 改进建议",
                "",
            ])
            for rec in report.recommendations:
                lines.append(f"- {rec}")
            lines.append("")

        # 详细记录
        lines.extend([
            "---",
            "",
            "## 详细记录",
            "",
        ])

        for record in report.task_records:
            status_icon = "✅" if record.status == "completed" else "❌"
            lines.append(f"### 任务 #{record.task_id} {status_icon}")
            lines.append(f"**描述**: {record.description}")
            lines.append(f"**状态**: {record.status}")
            lines.append(f"**复杂度**: {record.complexity}")

            if record.duration_seconds > 0:
                lines.append(f"**耗时**: {self._format_duration(record.duration_seconds)}")

            if record.tool_calls:
                lines.append(f"**工具调用**: {len(record.tool_calls)} 次")

            if record.errors:
                lines.append(f"**错误**: {len(record.errors)} 个")
                for error in record.errors[:3]:
                    lines.append(f"  - {error}")

            if record.insights:
                lines.append("**洞察**:")
                for insight in record.insights[:3]:
                    lines.append(f"  - {insight}")

            lines.append("")

        return "\n".join(lines)

    def save_analysis(
        self,
        report: TaskAnalysisReport,
        filepath: Optional[Path] = None,
    ) -> str:
        """
        保存分析报告

        Args:
            report: 分析报告
            filepath: 保存路径

        Returns:
            保存的文件路径
        """
        if filepath is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = self._analysis_dir / f"task_analysis_{ts}.json"

        data = {
            "timestamp": report.timestamp,
            "total_tasks": report.total_tasks,
            "completed_tasks": report.completed_tasks,
            "failed_tasks": report.failed_tasks,
            "completion_rate": report.completion_rate,
            "avg_duration": report.avg_duration,
            "success_patterns": report.success_patterns,
            "failure_patterns": report.failure_patterns,
            "recommendations": report.recommendations,
            "records": [self._record_to_dict(r) for r in report.task_records],
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return str(filepath)

    # =========================================================================
    # 进化会话分析
    # =========================================================================

    def analyze_evolution_session(
        self,
        session_file: Optional[Path] = None,
        session_id: Optional[str] = None,
    ) -> EvolutionSessionReport:
        """
        分析一轮进化会话日志，输出结果级复盘。

        Args:
            session_file: conversation_*.jsonl 文件路径
            session_id: 会话 ID；未提供 session_file 时用于定位文件

        Returns:
            EvolutionSessionReport
        """
        source = self._resolve_session_file(session_file=session_file, session_id=session_id)
        records = self._load_jsonl_records(source)
        if not records:
            raise ValueError(f"会话日志为空: {source}")

        session_start = next((r for r in records if r.get("type") == "session_start"), {})
        session_end = next((r for r in reversed(records) if r.get("type") == "session_end"), {})

        goal = self._extract_session_goal(records)
        tool_calls = [r for r in records if r.get("type") == "tool_call"]
        llm_responses = [r for r in records if r.get("type") == "llm_response"]
        validations = self._extract_validation_checks(tool_calls)
        blockers = self._extract_blockers(records, tool_calls)
        notable_states = self._extract_notable_states(records)
        key_actions = self._extract_key_actions(tool_calls)
        repeated_failure_patterns = self._extract_repeated_failure_patterns(tool_calls)
        tool_misuse_patterns = self._extract_tool_misuse_patterns(tool_calls)
        diagnostic_drift_detected = self._detect_diagnostic_drift(tool_calls, llm_responses)
        language_drift_detected = self._detect_language_drift(llm_responses)
        outcome, outcome_reason = self._determine_session_outcome(
            tool_calls=tool_calls,
            validations=validations,
            blockers=blockers,
            session_end=session_end,
        )
        next_round_constraints = self._build_next_round_constraints(
            repeated_failure_patterns,
            tool_misuse_patterns,
            diagnostic_drift_detected,
            language_drift_detected,
        )
        recommendations = self._build_session_recommendations(
            validations, blockers, outcome, next_round_constraints
        )

        summary = session_end.get("summary", {}) if isinstance(session_end.get("summary"), dict) else {}
        total_turns = session_end.get("total_turns") or summary.get("total_turns") or self._infer_total_turns(records)
        uptime_seconds = float(summary.get("uptime_seconds") or 0.0)

        return EvolutionSessionReport(
            session_id=str(session_start.get("session_id") or session_id or source.stem.replace("conversation_", "")),
            source_file=str(source),
            generated_at=datetime.now().isoformat(),
            started_at=str(session_start.get("timestamp") or ""),
            ended_at=str(session_end.get("timestamp") or ""),
            uptime_seconds=uptime_seconds,
            total_turns=int(total_turns or 0),
            total_tool_calls=len(tool_calls),
            total_llm_responses=len(llm_responses),
            total_validation_checks=len(validations),
            goal=goal,
            outcome=outcome,
            outcome_reason=outcome_reason,
            key_actions=key_actions,
            validations=validations,
            blockers=blockers,
            notable_states=notable_states,
            repeated_failure_patterns=repeated_failure_patterns,
            tool_misuse_patterns=tool_misuse_patterns,
            diagnostic_drift_detected=diagnostic_drift_detected,
            language_drift_detected=language_drift_detected,
            next_round_constraints=next_round_constraints,
            recommendations=recommendations,
        )

    def generate_evolution_retrospective(
        self,
        session_file: Optional[Path] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """生成单次进化会话的 Markdown 复盘。"""
        report = self.analyze_evolution_session(session_file=session_file, session_id=session_id)

        lines = [
            "# 进化结果分析",
            "",
            f"**会话 ID**: {report.session_id}",
            f"**生成时间**: {report.generated_at}",
            f"**日志来源**: `{report.source_file}`",
            "",
            "## 结果概览",
            "",
            f"- **目标**: {report.goal or '未识别'}",
            f"- **结果**: {report.outcome}",
            f"- **原因**: {report.outcome_reason}",
            f"- **总轮次**: {report.total_turns}",
            f"- **工具调用**: {report.total_tool_calls}",
            f"- **验证次数**: {report.total_validation_checks}",
            f"- **运行时长**: {self._format_duration(report.uptime_seconds) if report.uptime_seconds else '未知'}",
            "",
        ]

        if report.key_actions:
            lines.extend(["## 关键动作", ""])
            for item in report.key_actions:
                lines.append(f"- {item}")
            lines.append("")

        if report.validations:
            lines.extend(["## 验证结果", ""])
            for item in report.validations:
                lines.append(f"- **{item['kind']}**: {item['summary']}")
            lines.append("")

        if report.blockers:
            lines.extend(["## 阻塞点", ""])
            for item in report.blockers:
                lines.append(f"- **{item['kind']}**: {item['summary']}")
            lines.append("")

        if report.notable_states:
            lines.extend(["## 关键心智状态", ""])
            for item in report.notable_states:
                lines.append(f"- {item}")
            lines.append("")

        if report.repeated_failure_patterns or report.tool_misuse_patterns:
            lines.extend(["## 重复失败与误用", ""])
            for item in report.repeated_failure_patterns:
                lines.append(f"- 重复失败：{item}")
            for item in report.tool_misuse_patterns:
                lines.append(f"- 工具误用：{item}")
            lines.append("")

        if report.diagnostic_drift_detected or report.language_drift_detected:
            lines.extend(["## 执行纪律", ""])
            lines.append(f"- 诊断漂移：{'是' if report.diagnostic_drift_detected else '否'}")
            lines.append(f"- 语言漂移：{'是' if report.language_drift_detected else '否'}")
            lines.append("")

        if report.next_round_constraints:
            lines.extend(["## 下一轮约束", ""])
            for item in report.next_round_constraints:
                lines.append(f"- {item}")
            lines.append("")

        if report.recommendations:
            lines.extend(["## 下一步建议", ""])
            for item in report.recommendations:
                lines.append(f"- {item}")
            lines.append("")

        return "\n".join(lines)

    def save_evolution_analysis(
        self,
        report: EvolutionSessionReport,
        filepath: Optional[Path] = None,
    ) -> str:
        """保存单次进化会话分析报告。"""
        if filepath is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = self._analysis_dir / f"evolution_analysis_{report.session_id}_{ts}.json"

        data = {
            "session_id": report.session_id,
            "source_file": report.source_file,
            "generated_at": report.generated_at,
            "started_at": report.started_at,
            "ended_at": report.ended_at,
            "uptime_seconds": report.uptime_seconds,
            "total_turns": report.total_turns,
            "total_tool_calls": report.total_tool_calls,
            "total_llm_responses": report.total_llm_responses,
            "total_validation_checks": report.total_validation_checks,
            "goal": report.goal,
            "outcome": report.outcome,
            "outcome_reason": report.outcome_reason,
            "key_actions": report.key_actions,
            "validations": report.validations,
            "blockers": report.blockers,
            "notable_states": report.notable_states,
            "repeated_failure_patterns": report.repeated_failure_patterns,
            "tool_misuse_patterns": report.tool_misuse_patterns,
            "diagnostic_drift_detected": report.diagnostic_drift_detected,
            "language_drift_detected": report.language_drift_detected,
            "next_round_constraints": report.next_round_constraints,
            "recommendations": report.recommendations,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return str(filepath)

    # =========================================================================
    # 内部方法
    # =========================================================================

    def _record_to_dict(self, record: TaskRecord) -> Dict[str, Any]:
        """将任务记录转换为字典"""
        return {
            "task_id": record.task_id,
            "description": record.description,
            "status": record.status,
            "complexity": record.complexity,
            "start_time": record.start_time,
            "end_time": record.end_time,
            "duration_seconds": record.duration_seconds,
            "subtasks": record.subtasks,
            "tool_calls": record.tool_calls,
            "errors": record.errors,
            "insights": record.insights,
            "metadata": record.metadata,
        }

    def _resolve_session_file(
        self,
        session_file: Optional[Path] = None,
        session_id: Optional[str] = None,
    ) -> Path:
        """定位需要分析的 conversation JSONL。"""
        if session_file is not None:
            path = Path(session_file)
            if not path.exists():
                raise FileNotFoundError(f"会话日志不存在: {path}")
            return path

        log_dir = self.project_root / "log_info"
        if session_id:
            candidate = log_dir / f"conversation_{session_id}.jsonl"
            if not candidate.exists():
                raise FileNotFoundError(f"未找到会话日志: {candidate}")
            return candidate

        candidates = sorted(log_dir.glob("conversation_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise FileNotFoundError(f"目录中没有会话日志: {log_dir}")
        return candidates[0]

    def _load_jsonl_records(self, filepath: Path) -> List[Dict[str, Any]]:
        """读取 JSONL 记录。"""
        records: List[Dict[str, Any]] = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records

    def _extract_session_goal(self, records: List[Dict[str, Any]]) -> str:
        """提取本轮目标。"""
        for record in records:
            if record.get("type") == "external_request" and record.get("content"):
                return str(record["content"]).strip()
            if record.get("type") == "human" and record.get("content"):
                return str(record["content"]).strip()
            if record.get("type") == "user_input" and record.get("content"):
                return str(record["content"]).strip()
        return ""

    def _extract_validation_checks(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """提取编译/测试等验证动作。"""
        validations: List[Dict[str, Any]] = []
        for record in tool_calls:
            tool_name = str(record.get("tool_name") or "")
            args = record.get("tool_args") or {}
            result = str(record.get("tool_result") or "")
            command = str(args.get("command") or "")

            if "py_compile" in command:
                validations.append({
                    "kind": "编译检查",
                    "tool": tool_name,
                    "passed": "[命令执行完成，无输出]" in result or "success" == record.get("status"),
                    "summary": "python -m py_compile 通过" if "[命令执行完成，无输出]" in result else result[:180],
                })
            elif "pytest" in command:
                passed = " passed" in result or "PASSED" in result
                match = re.search(r"=+\s*(\d+)\s+passed", result)
                count = match.group(1) if match else ""
                validations.append({
                    "kind": "测试验证",
                    "tool": tool_name,
                    "passed": passed,
                    "summary": f"pytest 通过{count + ' 项' if count else ''}" if passed else result[:180],
                })
            elif tool_name == "run_test_for_tool":
                validations.append({
                    "kind": "测试映射检查",
                    "tool": tool_name,
                    "passed": "未找到对应测试文件" not in result,
                    "summary": "已找到映射测试文件" if "未找到对应测试文件" not in result else "未找到映射测试文件，已退回手动 pytest",
                })
        return validations

    def _extract_blockers(
        self,
        records: List[Dict[str, Any]],
        tool_calls: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """提取阻塞点。"""
        blockers: List[Dict[str, Any]] = []

        for record in tool_calls:
            tool_name = str(record.get("tool_name") or "")
            result = str(record.get("tool_result") or "")
            args = record.get("tool_args") or {}
            command = str(args.get("command") or "")

            if "[安全拦截]" in result:
                blockers.append({
                    "kind": "安全策略拦截",
                    "tool": tool_name,
                    "summary": f"{tool_name} 在执行 `{command[:80]}` 时被安全策略拦截",
                })
            elif record.get("status") not in {"success", "ok", None}:
                blockers.append({
                    "kind": "工具调用失败",
                    "tool": tool_name,
                    "summary": f"{tool_name} 执行失败: {result[:180]}",
                })

        for record in records:
            if record.get("type") == "error":
                blockers.append({
                    "kind": "运行错误",
                    "tool": "runtime",
                    "summary": str(record.get("error_msg") or record.get("message") or "发生运行错误"),
                })

        return blockers

    def _extract_notable_states(self, records: List[Dict[str, Any]]) -> List[str]:
        """提取关键心智状态。"""
        states: List[str] = []
        for record in records:
            if record.get("type") == "debug" and record.get("tag") == "STATE":
                message = str(record.get("message") or "").strip()
                if message:
                    states.append(message)
        return states[-5:]

    def _extract_key_actions(self, tool_calls: List[Dict[str, Any]]) -> List[str]:
        """提取关键动作摘要。"""
        actions: List[str] = []
        seen: Dict[str, int] = {}
        order: List[str] = []
        for record in tool_calls:
            tool_name = str(record.get("tool_name") or "")
            if not tool_name:
                continue
            if tool_name not in seen:
                order.append(tool_name)
                seen[tool_name] = 0
            seen[tool_name] += 1

        for tool_name in order[:8]:
            actions.append(f"{tool_name} 调用 {seen[tool_name]} 次")
        return actions

    def _determine_session_outcome(
        self,
        tool_calls: List[Dict[str, Any]],
        validations: List[Dict[str, Any]],
        blockers: List[Dict[str, Any]],
        session_end: Dict[str, Any],
    ) -> Tuple[str, str]:
        """判断本轮会话结果。"""
        if blockers:
            passed_validations = [item for item in validations if item.get("passed")]
            if passed_validations:
                return "受阻", "核心验证已通过，但后续执行链路被阻塞"
            return "失败", "存在明确阻塞点，且未形成稳定通过的验证闭环"

        if validations and all(item.get("passed") for item in validations if "passed" in item):
            return "完成", "验证闭环通过，未发现阻塞点"

        if session_end:
            return "结束", "会话已结束，但未提取到明确阻塞或完整验证闭环"

        return "未知", "日志信息不足，无法稳定判断本轮结果"

    def _build_session_recommendations(
        self,
        validations: List[Dict[str, Any]],
        blockers: List[Dict[str, Any]],
        outcome: str,
        next_round_constraints: List[str],
    ) -> List[str]:
        """生成单轮进化建议。"""
        recommendations: List[str] = list(next_round_constraints)
        if any(item["kind"] == "安全策略拦截" for item in blockers):
            recommendations.append("将提交动作改走更稳定的 Git 提交通道，避免把长 commit message 直接塞进受限 shell 命令。")
        if any(item["kind"] == "测试映射检查" and not item.get("passed") for item in validations):
            recommendations.append("补强源文件到测试文件的映射规则，减少先失败再手动回退到 pytest 的绕路。")
        if any(item["kind"] == "测试验证" and item.get("passed") for item in validations):
            recommendations.append("保留当前验证组合，后续可直接把通过摘要沉淀为标准结果分析模板。")
        if outcome == "完成":
            recommendations.append("本轮已形成稳定验证闭环，下一步可以记录为成功进化样本。")
        return recommendations[:5]

    def _extract_repeated_failure_patterns(self, tool_calls: List[Dict[str, Any]]) -> List[str]:
        patterns: List[str] = []
        blocked_commands = [
            str(item.get("tool_args", {}).get("command", ""))
            for item in tool_calls
            if "[安全拦截]" in str(item.get("tool_result") or "")
        ]
        pipe_failures = [cmd for cmd in blocked_commands if "|" in cmd]
        if len(pipe_failures) >= 2:
            patterns.append(f"同轮重复触发 pipe 安全拦截 {len(pipe_failures)} 次")
        return patterns

    def _extract_tool_misuse_patterns(self, tool_calls: List[Dict[str, Any]]) -> List[str]:
        patterns: List[str] = []
        for item in tool_calls:
            command = str(item.get("tool_args", {}).get("command", ""))
            result = str(item.get("tool_result") or "")
            if item.get("tool_name") == "cli_tool" and "|" in command and "[安全拦截]" in result:
                patterns.append("使用 cli_tool 读取内容时仍携带 pipe，应直接改用 read_file_tool 或 grep_search_tool")
                break
        return patterns

    def _detect_diagnostic_drift(self, tool_calls: List[Dict[str, Any]], llm_responses: List[Dict[str, Any]]) -> bool:
        validation_idx = [
            idx for idx, item in enumerate(tool_calls)
            if "pytest" in str(item.get("tool_args", {}).get("command", ""))
            or item.get("tool_name") == "run_test_for_tool"
        ]
        inspect_tools = {
            "read_file_tool",
            "get_code_entity_tool",
            "list_file_entities_tool",
            "grep_search_tool",
            "get_file_entities_tool",
        }
        inspect_idx = [
            idx for idx, item in enumerate(tool_calls)
            if item.get("tool_name") in inspect_tools
        ]

        if not validation_idx:
            return False

        last_validation_idx = validation_idx[-1]
        inspections_after_validation = [idx for idx in inspect_idx if idx > last_validation_idx]
        english_drift = any(
            self._looks_english_natural_language(str(item.get("content") or ""))
            for item in llm_responses[-3:]
        )

        # 失败验证之后若连续进入读取/检查阶段，却没有形成新的验证闭环，
        # 就视为“先推理/检查，缺少最小观测补充”的诊断漂移。
        if len(inspections_after_validation) >= 2:
            return True

        # 若围绕验证前后已经堆积了较多 inspection 动作，并且伴随英文长推理，
        # 说明本轮开始出现只分析不增量观测的迹象。
        if english_drift and len(inspect_idx) >= 3:
            return True

        return False

    def _detect_language_drift(self, llm_responses: List[Dict[str, Any]]) -> bool:
        return any(self._looks_english_natural_language(str(item.get("content") or "")) for item in llm_responses)

    def _build_next_round_constraints(
        self,
        repeated_failure_patterns: List[str],
        tool_misuse_patterns: List[str],
        diagnostic_drift_detected: bool,
        language_drift_detected: bool,
    ) -> List[str]:
        constraints: List[str] = []
        if repeated_failure_patterns or tool_misuse_patterns:
            constraints.append("本轮若再次需要读取 diff/文件内容，禁止使用带 pipe 的 cli_tool，优先改用 read_file_tool / grep_search_tool。")
        if diagnostic_drift_detected:
            constraints.append("测试失败后先打印最小中间值，再继续读代码或推理。")
        if language_drift_detected:
            constraints.append("后续自然语言说明默认回到中文，仅保留代码、命令、路径和必要报错原文。")
        return constraints[:5]

    def build_next_round_state_memory(self, report: EvolutionSessionReport) -> str:
        """将进化结果分析压缩成下一轮可读的短期约束摘要。"""
        lines = ["## 延续约束"]
        seen = set()
        for item in report.next_round_constraints:
            normalized = item.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            lines.append(f"- {normalized}")
            if len(seen) >= 4:
                break
        return "\n".join(lines)

    def _looks_english_natural_language(self, text: str) -> bool:
        cleaned = re.sub(r"```.*?```", "", text or "", flags=re.DOTALL)
        cleaned = re.sub(r"`[^`]*`", "", cleaned)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        english_words = re.findall(r"\b[a-zA-Z]{3,}\b", cleaned)
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", cleaned)
        return len(english_words) >= 24 and len(english_words) > max(len(chinese_chars), 8)

    def _infer_total_turns(self, records: List[Dict[str, Any]]) -> int:
        """从记录中推断最大 turn。"""
        turns = [int(r.get("turn")) for r in records if isinstance(r.get("turn"), int)]
        return max(turns) if turns else 0

    def _identify_success_patterns(
        self,
        records: List[TaskRecord],
    ) -> List[str]:
        """识别成功模式"""
        patterns = []

        # 检查哪些复杂度等级完成率高
        complexity_stats: Dict[str, Dict[str, int]] = {}
        for record in records:
            if record.status == TaskStatus.COMPLETED.value:
                if record.complexity not in complexity_stats:
                    complexity_stats[record.complexity] = {"total": 0, "completed": 0}
                complexity_stats[record.complexity]["total"] += 1
                complexity_stats[record.complexity]["completed"] += 1
            else:
                if record.complexity not in complexity_stats:
                    complexity_stats[record.complexity] = {"total": 0, "completed": 0}
                complexity_stats[record.complexity]["total"] += 1

        for complexity, stats in complexity_stats.items():
            if stats["total"] > 0:
                rate = stats["completed"] / stats["total"]
                if rate >= 0.8:
                    patterns.append(
                        f"{complexity} 复杂度任务完成率高 ({rate:.0%})"
                    )

        # 检查成功工具使用
        tool_success: Dict[str, Dict[str, int]] = {}
        for record in records:
            if record.status == TaskStatus.COMPLETED.value:
                for call in record.tool_calls:
                    tool = call.get("tool", "unknown")
                    if tool not in tool_success:
                        tool_success[tool] = {"success": 0, "total": 0}
                    tool_success[tool]["total"] += 1
                    if call.get("success", True):
                        tool_success[tool]["success"] += 1

        for tool, stats in tool_success.items():
            if stats["total"] >= 3:
                rate = stats["success"] / stats["total"]
                if rate >= 0.9:
                    patterns.append(
                        f"'{tool}' 工具使用成功率高 ({rate:.0%})"
                    )

        # 检查洞察提取
        records_with_insights = [r for r in records if r.insights]
        if len(records_with_insights) >= len(records) * 0.5:
            patterns.append("善于从任务中提取洞察")

        return patterns

    def _identify_failure_patterns(
        self,
        records: List[TaskRecord],
    ) -> List[str]:
        """识别失败模式"""
        patterns = []

        # 检查失败任务
        failed_records = [r for r in records if r.status == TaskStatus.FAILED.value]

        if failed_records:
            patterns.append(
                f"存在 {len(failed_records)} 个失败任务需要关注"
            )

            # 统计失败原因
            error_types: Dict[str, int] = {}
            for record in failed_records:
                for error in record.errors:
                    error_type = self._classify_error(error)
                    error_types[error_type] = error_types.get(error_type, 0) + 1

            for error_type, count in sorted(error_types.items(), key=lambda x: -x[1]):
                patterns.append(f"'{error_type}' 错误出现 {count} 次")

        # 检查超时或长时间未完成的任务
        long_tasks = [
            r for r in records
            if r.duration_seconds > 300 and r.status != TaskStatus.COMPLETED.value
        ]
        if long_tasks:
            patterns.append(
                f"存在 {len(long_tasks)} 个耗时过长 (>5分钟) 的任务"
            )

        # 检查工具调用失败
        failed_tool_calls: Dict[str, int] = {}
        for record in records:
            for call in record.tool_calls:
                if not call.get("success", True):
                    tool = call.get("tool", "unknown")
                    failed_tool_calls[tool] = failed_tool_calls.get(tool, 0) + 1

        for tool, count in sorted(failed_tool_calls.items(), key=lambda x: -x[1]):
            if count >= 2:
                patterns.append(
                    f"'{tool}' 工具调用失败 {count} 次"
                )

        return patterns

    def _classify_error(self, error: str) -> str:
        """分类错误类型"""
        error_lower = error.lower()

        if any(word in error_lower for word in ["timeout", "超时", "超时"]):
            return "超时"
        if any(word in error_lower for word in ["syntax", "语法"]):
            return "语法错误"
        if any(word in error_lower for word in ["permission", "权限", "拒绝"]):
            return "权限错误"
        if any(word in error_lower for word in ["not found", "不存在", "找不到"]):
            return "资源不存在"
        if any(word in error_lower for word in ["memory", "内存"]):
            return "内存错误"
        if any(word in error_lower for word in ["connection", "连接"]):
            return "连接错误"

        return "其他错误"

    def _generate_recommendations(
        self,
        records: List[TaskRecord],
        success_patterns: List[str],
        failure_patterns: List[str],
    ) -> List[str]:
        """生成建议"""
        recommendations = []

        # 基于失败模式建议
        for pattern in failure_patterns:
            if "超时" in pattern:
                recommendations.append("考虑优化超时设置或拆分长时间任务")
            elif "语法错误" in pattern:
                recommendations.append("加强代码编写前的语法检查")
            elif "权限错误" in pattern:
                recommendations.append("检查文件权限设置")
            elif "失败" in pattern and "工具" in pattern:
                tool_name = pattern.split("'")[1] if "'" in pattern else None
                if tool_name:
                    recommendations.append(f"检查 '{tool_name}' 工具的使用方式")
            elif "耗时过长" in pattern:
                recommendations.append("将大任务拆分为多个子任务")

        # 基于成功率建议
        total = len(records)
        completed = len([r for r in records if r.status == TaskStatus.COMPLETED.value])
        rate = completed / total if total > 0 else 0

        if rate < 0.5:
            recommendations.append("任务完成率偏低，建议简化任务复杂度")
        elif rate < 0.7:
            recommendations.append("任务完成率一般，建议增加任务规划时间")

        # 基于洞察建议
        records_with_insights = len([r for r in records if r.insights])
        if records_with_insights < total * 0.3:
            recommendations.append("建议从更多任务中提取洞察和教训")

        # 限制建议数量
        return recommendations[:5]

    def _format_duration(self, seconds: float) -> str:
        """格式化时长"""
        if seconds < 60:
            return f"{seconds:.0f} 秒"
        elif seconds < 3600:
            return f"{seconds / 60:.1f} 分钟"
        else:
            return f"{seconds / 3600:.1f} 小时"


# ============================================================================
# 全局单例
# ============================================================================

_task_analyzer: Optional[TaskAnalyzer] = None


def get_task_analyzer(project_root: Optional[str] = None) -> TaskAnalyzer:
    """获取任务分析器单例"""
    global _task_analyzer
    if _task_analyzer is None:
        _task_analyzer = TaskAnalyzer(project_root)
    return _task_analyzer
