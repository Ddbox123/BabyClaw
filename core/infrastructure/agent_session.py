#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent Session 状态管理模块

职责：
- 管理 Agent Session 级别的状态
- recent_actions: 最近N个动作
- consecutive_count: 连续动作计数
- self_modified: Agent是否自我修改
- start_time: 启动时间

使用方式：
    from core.infrastructure.agent_session import get_session_state, reset_session

    session = get_session_state()
    session.record_action("tool_call", tool_name)
"""

from __future__ import annotations

import threading
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Any, Dict

from core.infrastructure.tool_intents import (
    humanize_reading_task,
    humanize_tool_intent,
    humanize_tool_name,
    humanize_tool_chain,
)


@dataclass
class AgentSessionState:
    """Agent Session 状态"""
    recent_actions: List[str] = field(default_factory=list)
    consecutive_count: int = 0
    _self_modified: bool = False
    start_time: datetime = field(default_factory=datetime.now)
    modified_paths: List[str] = field(default_factory=list)
    modified_entities: Dict[str, List[str]] = field(default_factory=dict)
    dirty_since: Optional[str] = None
    active_git_base: Optional[str] = None
    last_git_scan_at: Optional[str] = None
    last_validation_summary: Optional[str] = None
    last_validation_passed: Optional[bool] = None
    active_evolution_txn_id: Optional[str] = None
    blocked_tool_patterns: Dict[str, Dict[str, str]] = field(default_factory=dict)
    recent_blockers: List[Dict[str, str]] = field(default_factory=list)
    recent_validation_results: List[Dict[str, Any]] = field(default_factory=list)
    language_drift_count: int = 0
    diagnostic_phase: str = "idle"
    diagnostic_observation_count: int = 0
    diagnostic_inference_count: int = 0
    feedback_loop_ready: bool = False
    feedback_loop_type: str = ""
    feedback_loop_target: str = ""
    feedback_loop_last_result: str = ""
    feedback_loop_last_updated_at: Optional[str] = None
    scope_frozen: bool = False
    scope_anchor: str = ""
    convergence_state: str = "open"
    stop_reason: str = ""
    expansion_denied_count: int = 0
    reading_task: str = "locate"
    reading_recommendation: str = ""
    reading_sufficiency: str = ""
    next_tool_intent: str = ""
    recommended_tools: List[str] = field(default_factory=list)
    avoid_tools: List[str] = field(default_factory=list)
    tool_deviations: List[Dict[str, str]] = field(default_factory=list)
    read_ranges: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    read_entities: Dict[str, List[str]] = field(default_factory=dict)
    read_searches: List[Dict[str, str]] = field(default_factory=list)
    pending_continuations: List[Dict[str, str]] = field(default_factory=list)
    active_delegation: Optional[Dict[str, Any]] = None
    delegation_history: List[Dict[str, Any]] = field(default_factory=list)
    delegation_findings: List[Dict[str, Any]] = field(default_factory=list)
    delegation_failures: List[Dict[str, Any]] = field(default_factory=list)
    delegation_evidence_digest: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_action(self, action_type: str, action_detail: str = ""):
        """记录一个动作"""
        with self._lock:
            action_str = f"{action_type}:{action_detail}" if action_detail else action_type
            self.recent_actions.append(action_str)
            if len(self.recent_actions) > 50:  # 保留最近50个
                self.recent_actions.pop(0)
            self.consecutive_count += 1

    def reset_consecutive(self):
        """重置连续计数"""
        with self._lock:
            self.consecutive_count = 0

    @property
    def self_modified(self) -> bool:
        """是否自我修改过"""
        return self._self_modified

    @self_modified.setter
    def self_modified(self, value: bool):
        """设置自我修改标志"""
        self._self_modified = value

    def mark_modified(self):
        """标记为已修改"""
        self._self_modified = True
        if self.dirty_since is None:
            self.dirty_since = datetime.now().isoformat()

    def clear_modified(self):
        """清除修改标志"""
        self._self_modified = False

    def get_uptime(self) -> float:
        """获取运行时长（秒）"""
        return (datetime.now() - self.start_time).total_seconds()

    def get_recent_history(self, count: int = 10) -> List[str]:
        """获取最近N个动作"""
        with self._lock:
            return self.recent_actions[-count:]

    def record_modified_path(self, path: str):
        """记录最近修改的路径。"""
        if not path:
            return
        with self._lock:
            normalized = path.replace("\\", "/")
            if normalized in self.modified_paths:
                self.modified_paths.remove(normalized)
            self.modified_paths.append(normalized)
            if len(self.modified_paths) > 20:
                self.modified_paths = self.modified_paths[-20:]
            if self.dirty_since is None:
                self.dirty_since = datetime.now().isoformat()
            self._self_modified = True

    def record_modified_entities(self, path: str, entities: List[str]):
        """记录某个文件最近关联的实体。"""
        if not path:
            return
        with self._lock:
            normalized = path.replace("\\", "/")
            self.modified_entities[normalized] = list(dict.fromkeys(entities or []))
            if len(self.modified_entities) > 20:
                oldest = next(iter(self.modified_entities.keys()))
                if oldest != normalized:
                    self.modified_entities.pop(oldest, None)

    def record_validation_result(self, summary: str, passed: bool, kind: str = "validation"):
        """记录最近一次验证结果。"""
        with self._lock:
            self.last_validation_summary = summary
            self.last_validation_passed = passed
            self.recent_validation_results.append({
                "kind": kind,
                "summary": summary,
                "passed": passed,
                "timestamp": datetime.now().isoformat(),
            })
            if len(self.recent_validation_results) > 10:
                self.recent_validation_results = self.recent_validation_results[-10:]
            self.diagnostic_phase = "observe"
            self.diagnostic_observation_count += 1

    def clear_attention_tracking(self, keep_validation: bool = True):
        """清除会话级修改注意力，避免干净工作区仍残留旧脏区信号。"""
        with self._lock:
            self.modified_paths.clear()
            self.modified_entities.clear()
            self.dirty_since = None
            self._self_modified = False
            if not keep_validation:
                self.last_validation_summary = None
                self.last_validation_passed = None

    def set_active_evolution_txn(self, txn_id: Optional[str]):
        """设置当前会话激活的演化事务。"""
        with self._lock:
            self.active_evolution_txn_id = txn_id

    def reset_runtime_constraints(self):
        """清空当前轮的短期运行时约束。"""
        with self._lock:
            self.blocked_tool_patterns.clear()
            self.recent_blockers.clear()
            self.recent_validation_results.clear()
            self.language_drift_count = 0
            self.diagnostic_phase = "idle"
            self.diagnostic_observation_count = 0
            self.diagnostic_inference_count = 0
            self.feedback_loop_ready = False
            self.feedback_loop_type = ""
            self.feedback_loop_target = ""
            self.feedback_loop_last_result = ""
            self.feedback_loop_last_updated_at = None
            self.scope_frozen = False
            self.scope_anchor = ""
            self.convergence_state = "open"
            self.stop_reason = ""
            self.expansion_denied_count = 0
            self.reading_task = "locate"
            self.reading_recommendation = ""
            self.reading_sufficiency = ""
            self.next_tool_intent = ""
            self.recommended_tools.clear()
            self.avoid_tools.clear()
            self.tool_deviations.clear()
            self.read_ranges.clear()
            self.read_entities.clear()
            self.read_searches.clear()
            self.pending_continuations.clear()
            self.active_delegation = None
            self.delegation_history.clear()
            self.delegation_findings.clear()
            self.delegation_failures.clear()
            self.delegation_evidence_digest = ""

    def set_reading_strategy(self, task: str, recommendation: str = ""):
        with self._lock:
            self.reading_task = task or "locate"
            self.reading_recommendation = recommendation or ""
            self.reading_sufficiency = ""

    def set_tool_decision(self, next_intent: str, recommended_tools: List[str], avoid_tools: List[str]):
        with self._lock:
            self.next_tool_intent = next_intent or ""
            self.recommended_tools = list(recommended_tools or [])
            self.avoid_tools = list(avoid_tools or [])

    def set_reading_sufficiency(self, summary: str = ""):
        with self._lock:
            self.reading_sufficiency = summary or ""

    def clear_reading_guidance(self, *, clear_decision: bool = False):
        with self._lock:
            self.reading_recommendation = ""
            self.reading_sufficiency = ""
            if clear_decision:
                self.next_tool_intent = ""
                self.recommended_tools = []
                self.avoid_tools = []

    def record_tool_deviation(self, tool_name: str, reason: str):
        if not tool_name:
            return
        with self._lock:
            self.tool_deviations.append({
                "tool_name": tool_name,
                "reason": reason,
                "timestamp": datetime.now().isoformat(),
            })
            if len(self.tool_deviations) > 10:
                self.tool_deviations = self.tool_deviations[-10:]

    def record_read_range(self, path: str, start_line: int, end_line: int, source: str = "read_file_tool"):
        """记录本轮已读取的文件区间。"""
        if not path:
            return
        with self._lock:
            normalized = path.replace("\\", "/")
            ranges = self.read_ranges.setdefault(normalized, [])
            record = {
                "start_line": max(1, int(start_line or 1)),
                "end_line": max(int(end_line or start_line or 1), int(start_line or 1)),
                "source": source,
            }
            if record not in ranges:
                ranges.append(record)
            if len(ranges) > 20:
                self.read_ranges[normalized] = ranges[-20:]

    def has_read_range_overlap(self, path: str, start_line: int, end_line: int) -> bool:
        if not path:
            return False
        with self._lock:
            normalized = path.replace("\\", "/")
            for item in self.read_ranges.get(normalized, []):
                existing_start = int(item.get("start_line", 0))
                existing_end = int(item.get("end_line", 0))
                if max(existing_start, start_line) <= min(existing_end, end_line):
                    return True
        return False

    def get_overlapping_read_ranges(self, path: str, start_line: int, end_line: int) -> List[Dict[str, Any]]:
        """返回与目标区间重叠的历史读取区间。"""
        if not path:
            return []
        overlaps: List[Dict[str, Any]] = []
        with self._lock:
            normalized = path.replace("\\", "/")
            for item in self.read_ranges.get(normalized, []):
                existing_start = int(item.get("start_line", 0))
                existing_end = int(item.get("end_line", 0))
                if max(existing_start, start_line) <= min(existing_end, end_line):
                    overlaps.append(dict(item))
        return overlaps

    def record_read_entity(self, path: str, entity_name: str):
        """记录本轮已读取的实体。"""
        if not path or not entity_name:
            return
        with self._lock:
            normalized = path.replace("\\", "/")
            entities = self.read_entities.setdefault(normalized, [])
            if entity_name not in entities:
                entities.append(entity_name)
            if len(entities) > 20:
                self.read_entities[normalized] = entities[-20:]

    def has_read_entity(self, path: str, entity_name: str) -> bool:
        if not path or not entity_name:
            return False
        with self._lock:
            normalized = path.replace("\\", "/")
            return entity_name in self.read_entities.get(normalized, [])

    def record_search_query(self, query: str, scope: str = ""):
        """记录本轮已执行的搜索。"""
        if not query:
            return
        with self._lock:
            item = {"query": query, "scope": scope}
            if item not in self.read_searches:
                self.read_searches.append(item)
            if len(self.read_searches) > 20:
                self.read_searches = self.read_searches[-20:]

    def record_pending_continuation(self, tool_name: str, hint: str, path: str = "", strength: str = "strong"):
        """记录最近一次未读完结果的续读提示。"""
        normalized_path = (path or "").replace("\\", "/")
        normalized_hint = (hint or "").strip()
        normalized_strength = "weak" if str(strength or "").strip().lower() == "weak" else "strong"
        if not tool_name or not normalized_hint:
            return
        with self._lock:
            entry = {
                "tool_name": tool_name,
                "hint": normalized_hint,
                "path": normalized_path,
                "strength": normalized_strength,
                "timestamp": datetime.now().isoformat(),
            }
            existing = [
                item for item in self.pending_continuations
                if item.get("tool_name") == tool_name
                and item.get("hint") == normalized_hint
                and item.get("path") == normalized_path
                and item.get("strength", "strong") == normalized_strength
            ]
            if not existing:
                self.pending_continuations.append(entry)
            if len(self.pending_continuations) > 6:
                self.pending_continuations = self.pending_continuations[-6:]

    def clear_pending_continuation(self, path: str = "", tool_name: str = ""):
        """清除已处理的续读提示。"""
        normalized_path = (path or "").replace("\\", "/")
        with self._lock:
            if not self.pending_continuations:
                return
            filtered = []
            for item in self.pending_continuations:
                same_path = normalized_path and item.get("path") == normalized_path
                same_tool = tool_name and item.get("tool_name") == tool_name
                if same_path or same_tool:
                    continue
                filtered.append(item)
            self.pending_continuations = filtered

    def get_latest_pending_continuation(self, path: str = "") -> Optional[Dict[str, str]]:
        """读取最近一条续读提示，可按路径过滤。"""
        normalized_path = (path or "").replace("\\", "/")
        with self._lock:
            candidates = list(self.pending_continuations)
        if normalized_path:
            candidates = [item for item in candidates if item.get("path") == normalized_path]
        return candidates[-1] if candidates else None

    def has_search_query(self, query: str, scope: str = "") -> bool:
        if not query:
            return False
        with self._lock:
            return {"query": query, "scope": scope} in self.read_searches

    def evaluate_reading_sufficiency(self) -> str:
        with self._lock:
            total_ranges = sum(len(v) for v in self.read_ranges.values())
            total_entities = sum(len(v) for v in self.read_entities.values())
            total_searches = len(self.read_searches)
            task = self.reading_task
            last_validation = self.last_validation_summary or ""

        if task == "locate":
            if total_searches >= 1 and (total_ranges >= 1 or total_entities >= 1):
                return "定位证据已初步足够，可转入实体精读或修改。"
            if total_searches >= 1:
                return "已完成首轮定位，下一步应精读目标文件或实体。"
            return "定位证据不足，先执行一次搜索或符号查询。"
        if task == "understand":
            if total_entities >= 1 or total_ranges >= 2:
                return "理解上下文已基本够用，可开始归纳实现或准备修改。"
            return "理解证据不足，先补一个实体或相邻区间。"
        if task == "modify":
            if total_entities >= 1 and total_ranges >= 1:
                return "修改上下文已足够，可开始动手并保留验证闭环。"
            return "修改前证据还不够，至少补一个目标实体和一段局部上下文。"
        if task == "verify":
            if last_validation and (total_ranges >= 1 or total_searches >= 1):
                return "验证证据已具备，可继续修复或复测。"
            return "验证证据不足，先读取失败输出或相关命中片段。"
        if task == "analyze":
            if total_searches >= 1 and (total_ranges >= 1 or total_entities >= 1):
                return "归因证据已初步够用，可形成分析结论。"
            return "归因证据不足，先补搜索结果和局部上下文。"
        return ""

    def record_blocked_tool_pattern(self, pattern: str, reason: str, hint: str = ""):
        """记录同轮内应避免重复尝试的工具模式。"""
        if not pattern:
            return
        with self._lock:
            self.blocked_tool_patterns[pattern] = {
                "reason": reason,
                "hint": hint,
                "recorded_at": datetime.now().isoformat(),
            }

    def get_blocked_tool_pattern(self, pattern: str) -> Optional[Dict[str, str]]:
        """读取已记录的阻塞工具模式。"""
        if not pattern:
            return None
        with self._lock:
            return self.blocked_tool_patterns.get(pattern)

    def record_blocker(self, kind: str, summary: str, hint: str = "", severity: str = "block"):
        """记录最近阻塞点或运行提示。"""
        normalized_severity = "hint" if str(severity or "").strip().lower() == "hint" else "block"
        with self._lock:
            self.recent_blockers.append({
                "kind": kind,
                "summary": summary,
                "hint": hint,
                "severity": normalized_severity,
                "timestamp": datetime.now().isoformat(),
            })
            if len(self.recent_blockers) > 10:
                self.recent_blockers = self.recent_blockers[-10:]

    def set_diagnostic_phase(self, phase: str):
        """设置当前诊断阶段。"""
        if not phase:
            return
        with self._lock:
            self.diagnostic_phase = phase
            if phase == "idle":
                self.convergence_state = "open"
            elif phase in {"build_loop", "reproduce", "observe"} and self.convergence_state == "open":
                self.convergence_state = "narrowing"
            elif phase in {"inspect", "infer"} and self.convergence_state in {"open", "narrowing"}:
                self.convergence_state = "narrowing"
            elif phase == "fix":
                self.convergence_state = "ready_to_fix"
            elif phase == "verify":
                self.convergence_state = "ready_to_verify"

    def note_diagnostic_observation(self, summary: str = ""):
        """记录新增观测。"""
        with self._lock:
            self.diagnostic_observation_count += 1
            if summary:
                self.recent_blockers.append({
                    "kind": "observation",
                    "summary": summary,
                    "hint": "",
                    "timestamp": datetime.now().isoformat(),
                })
                if len(self.recent_blockers) > 10:
                    self.recent_blockers = self.recent_blockers[-10:]
            if self.diagnostic_phase in {"reproduce", "idle"}:
                self.diagnostic_phase = "observe"
            if self.convergence_state in {"open", "narrowing"}:
                self.convergence_state = "narrowing"

    def note_diagnostic_inspection(self):
        """记录进入代码/实体检查阶段。"""
        with self._lock:
            self.diagnostic_phase = "inspect"

    def note_diagnostic_inference(self):
        """记录一次推理动作。"""
        with self._lock:
            self.diagnostic_inference_count += 1
            if self.diagnostic_phase in {"observe", "inspect", "reproduce"}:
                self.diagnostic_phase = "infer"
            if (
                self.scope_frozen
                and self.feedback_loop_ready
                and self.diagnostic_observation_count >= 1
                and self.convergence_state in {"open", "narrowing"}
            ):
                self.convergence_state = "ready_to_fix"

    def _has_diagnostic_drift_unlocked(self) -> bool:
        """在已持锁上下文中判断是否进入诊断漂移。"""
        return self.diagnostic_inference_count >= 2 and self.diagnostic_observation_count == 0

    def has_diagnostic_drift(self) -> bool:
        """判断是否进入“只推理不新增观测”的漂移状态。"""
        with self._lock:
            return self._has_diagnostic_drift_unlocked()

    def note_feedback_loop(
        self,
        *,
        loop_type: str,
        target: str,
        result: str = "",
        phase: str = "reproduce",
    ):
        """记录当前轮已形成的最小反馈环。"""
        with self._lock:
            self.feedback_loop_ready = True
            self.feedback_loop_type = (loop_type or "").strip()
            self.feedback_loop_target = (target or "").strip()
            self.feedback_loop_last_result = (result or "").strip()
            self.feedback_loop_last_updated_at = datetime.now().isoformat()
            if phase:
                self.diagnostic_phase = phase
            if self.convergence_state == "open":
                self.convergence_state = "narrowing"

    def freeze_scope(self, anchor: str, reason: str = ""):
        """冻结当前分析范围，避免本轮继续横向扩散。"""
        normalized_anchor = (anchor or "").strip()
        normalized_reason = (reason or "").strip()
        if not normalized_anchor and not normalized_reason:
            return
        with self._lock:
            if normalized_anchor:
                if self.scope_anchor and self.scope_anchor != normalized_anchor:
                    self.expansion_denied_count += 1
                self.scope_anchor = normalized_anchor
            self.scope_frozen = True
            if normalized_reason:
                self.stop_reason = normalized_reason
            if self.convergence_state in {"open", "narrowing"}:
                self.convergence_state = "ready_to_fix"

    def mark_scope_expansion_denied(self, summary: str = ""):
        """记录一次已被拒绝的范围扩张。"""
        with self._lock:
            self.expansion_denied_count += 1
            if summary:
                self.recent_blockers.append({
                    "kind": "scope_frozen",
                    "summary": summary,
                    "hint": "保持单一问题锚点，先完成当前闭环",
                    "timestamp": datetime.now().isoformat(),
                })
                if len(self.recent_blockers) > 10:
                    self.recent_blockers = self.recent_blockers[-10:]

    def set_convergence_state(self, state: str, stop_reason: str = ""):
        if not state:
            return
        with self._lock:
            self.convergence_state = state
            if stop_reason:
                self.stop_reason = stop_reason

    def note_scope_completion(self, reason: str = ""):
        """标记本轮已具备停止条件。"""
        with self._lock:
            self.convergence_state = "ready_to_stop"
            if reason:
                self.stop_reason = reason

    def increment_language_drift(self) -> int:
        """记录一次语言漂移。"""
        with self._lock:
            self.language_drift_count += 1
            return self.language_drift_count

    @staticmethod
    def _normalize_scope_signature(scope: Any) -> str:
        if scope is None:
            return ""
        if isinstance(scope, (list, tuple, set)):
            parts = [str(item).strip().replace("\\", "/") for item in scope if str(item).strip()]
            return " | ".join(parts[:8])
        if isinstance(scope, dict):
            parts = []
            for key in sorted(scope.keys()):
                value = scope.get(key)
                if value in (None, "", [], {}):
                    continue
                parts.append(f"{key}={value}")
            return " | ".join(parts[:8])
        return str(scope).strip().replace("\\", "/")

    def has_recent_delegation(self, task_type: str, goal: str, scope: Any) -> bool:
        goal_key = (goal or "").strip()
        scope_key = self._normalize_scope_signature(scope)
        with self._lock:
            for item in reversed(self.delegation_history):
                if (
                    item.get("task_type") == task_type
                    and item.get("goal") == goal_key
                    and item.get("scope_signature") == scope_key
                    and item.get("status") == "completed"
                ):
                    return True
        return False

    def record_delegation_start(self, task_type: str, goal: str, scope: Any):
        entry = {
            "task_type": task_type or "inspect",
            "goal": (goal or "").strip(),
            "scope_signature": self._normalize_scope_signature(scope),
            "status": "running",
            "started_at": datetime.now().isoformat(),
        }
        with self._lock:
            self.active_delegation = dict(entry)
            self.delegation_history.append(dict(entry))
            if len(self.delegation_history) > 12:
                self.delegation_history = self.delegation_history[-12:]

    def record_delegation_result(
        self,
        task_type: str,
        goal: str,
        scope: Any,
        summary: str,
        findings: Optional[List[str]] = None,
        confidence: str = "",
        recommended_next_action: str = "",
    ):
        scope_key = self._normalize_scope_signature(scope)
        normalized_summary = (summary or "").strip()
        finding_lines = [str(item).strip() for item in (findings or []) if str(item).strip()]
        digest_parts = [normalized_summary] + finding_lines[:2]
        digest = "\n".join(part for part in digest_parts if part).strip()
        with self._lock:
            entry = {
                "task_type": task_type or "inspect",
                "goal": (goal or "").strip(),
                "scope_signature": scope_key,
                "status": "completed",
                "summary": normalized_summary,
                "findings": finding_lines,
                "confidence": confidence or "",
                "recommended_next_action": recommended_next_action or "",
                "completed_at": datetime.now().isoformat(),
            }
            self.active_delegation = None
            self.delegation_history.append(dict(entry))
            self.delegation_findings.append(dict(entry))
            if len(self.delegation_history) > 12:
                self.delegation_history = self.delegation_history[-12:]
            if len(self.delegation_findings) > 8:
                self.delegation_findings = self.delegation_findings[-8:]
            self.delegation_evidence_digest = digest[:600]

    def record_delegation_failure(self, task_type: str, goal: str, scope: Any, reason: str):
        scope_key = self._normalize_scope_signature(scope)
        with self._lock:
            entry = {
                "task_type": task_type or "inspect",
                "goal": (goal or "").strip(),
                "scope_signature": scope_key,
                "status": "failed",
                "reason": (reason or "").strip(),
                "failed_at": datetime.now().isoformat(),
            }
            self.active_delegation = None
            self.delegation_history.append(dict(entry))
            self.delegation_failures.append(dict(entry))
            if len(self.delegation_history) > 12:
                self.delegation_history = self.delegation_history[-12:]
            if len(self.delegation_failures) > 8:
                self.delegation_failures = self.delegation_failures[-8:]

    def render_delegation_rules(self) -> str:
        with self._lock:
            lines = [
                "## 委派规则",
                "- 主 agent 优先负责目标裁决、任务拆分、结果验收与最终决策。",
                "- 子 agent 第一版仅用于只读分析：日志、单文件、配置、prompt、测试归因、循环诊断。",
                "- 子 agent 禁止写文件、改 prompt、改 memory、做 git 操作、触发重启。",
                "- 子 agent 输出必须是结构化摘要；原始长输出不能直接回灌主上下文。",
                "- 子 agent 失败后由主 agent 接管，不自动重试，不级联委派。",
            ]
            if self.active_delegation:
                lines.append("- 当前委派中:")
                lines.append(
                    f"  - {self.active_delegation.get('task_type', 'inspect')} | "
                    f"{self.active_delegation.get('goal', '')} | "
                    f"{self.active_delegation.get('scope_signature', '')}"
                )
            if self.delegation_findings:
                latest = self.delegation_findings[-1]
                lines.append("- 最近已回收证据:")
                lines.append(f"  - {latest.get('summary', '')}")
                if latest.get("recommended_next_action"):
                    lines.append(f"  - 下一步: {latest.get('recommended_next_action')}")
            elif self.delegation_failures:
                latest_failure = self.delegation_failures[-1]
                lines.append("- 最近委派失败:")
                lines.append(f"  - {latest_failure.get('reason', '')}")
        return "\n".join(lines)

    def render_runtime_constraints(self) -> str:
        """生成当前轮短期约束摘要。"""
        with self._lock:
            lines: List[str] = []
            phase_label = {
                "idle": "空闲",
                "reproduce": "复现",
                "observe": "观测",
                "inspect": "读代码",
                "infer": "归因推理",
            }.get(self.diagnostic_phase, self.diagnostic_phase)

            if self.blocked_tool_patterns:
                lines.append("### 当前轮强约束")
                for pattern, meta in self.blocked_tool_patterns.items():
                    hint = f"；改用 {meta['hint']}" if meta.get("hint") else ""
                    lines.append(f"- `{pattern}` 已被阻塞：{meta.get('reason', '')}{hint}")
            if self.pending_continuations:
                latest = self.pending_continuations[-1]
                target = latest.get("path") or latest.get("hint") or "上一段未读完结果"
                if "### 当前轮强约束" not in lines:
                    lines.append("### 当前轮强约束")
                lines.append(f"- 存在未完成续读：先补读 `{target}`，暂不重新搜索、暂不直接归因。")
            if self.diagnostic_phase != "idle":
                lines.append("### 当前诊断纪律")
                lines.append(f"- 当前阶段：{phase_label}")
                if self.feedback_loop_ready:
                    target = self.feedback_loop_target or "待补充"
                    loop_type = self.feedback_loop_type or "unknown"
                    lines.append(f"- 反馈环：{loop_type} | {target}")
                if self._has_diagnostic_drift_unlocked():
                    lines.append("- 已出现诊断漂移：请先新增观测，再继续推理。")
            if self.scope_frozen or self.convergence_state != "open":
                lines.append("### 收束状态")
                state_label = {
                    "open": "开放",
                    "narrowing": "收窄中",
                    "ready_to_fix": "准备修复",
                    "ready_to_verify": "准备验证",
                    "ready_to_stop": "准备停止",
                    "stopped": "已停止",
                }.get(self.convergence_state, self.convergence_state)
                lines.append(f"- 当前状态：{state_label}")
                if self.scope_frozen:
                    lines.append(f"- 范围已冻结：{self.scope_anchor or '当前锚点待补充'}")
                if self.expansion_denied_count > 0:
                    lines.append(f"- 已拒绝扩散：{self.expansion_denied_count} 次")
                if self.stop_reason:
                    lines.append(f"- 收束原因：{self.stop_reason}")
            if self.reading_recommendation or self.reading_task != "locate":
                lines.append("### 阅读策略")
                lines.append(f"- 当前任务：{humanize_reading_task(self.reading_task)}")
                if self.reading_recommendation:
                    raw_tools = [part.strip() for part in self.reading_recommendation.split("->") if part.strip()]
                    lines.append(f"- 推荐路径：{humanize_tool_chain(raw_tools)}")
                if self.reading_sufficiency:
                    lines.append(f"- 充分性：{self.reading_sufficiency}")
            if self.pending_continuations:
                latest = self.pending_continuations[-1]
                lines.append("### 续读提示")
                target = f"（{latest.get('path')}）" if latest.get("path") else ""
                lines.append(f"- {humanize_tool_name(latest.get('tool_name', ''))}{target}：{latest.get('hint', '')}")
            if self.active_delegation or self.delegation_findings or self.delegation_failures:
                lines.append("### 委派状态")
                if self.active_delegation:
                    lines.append(
                        f"- 进行中：{self.active_delegation.get('task_type', 'inspect')} | "
                        f"{self.active_delegation.get('goal', '')}"
                    )
                if self.delegation_findings:
                    latest = self.delegation_findings[-1]
                    lines.append(f"- 最近证据：{latest.get('summary', '')}")
                if self.delegation_failures:
                    latest_failure = self.delegation_failures[-1]
                    lines.append(f"- 最近失败：{latest_failure.get('reason', '')}")
            if self.next_tool_intent or self.recommended_tools:
                lines.append("### 工具决策")
                if self.next_tool_intent:
                    lines.append(f"- 下一步意图：{humanize_tool_intent(self.next_tool_intent)}")
                if self.recommended_tools:
                    lines.append(f"- 推荐工具：{humanize_tool_chain(self.recommended_tools)}")
                if self.avoid_tools:
                    lines.append(f"- 避免工具：{' / '.join(humanize_tool_name(name) for name in self.avoid_tools)}")
            if self.tool_deviations:
                latest = self.tool_deviations[-1]
                lines.append("### 工具偏离")
                lines.append(f"- {humanize_tool_name(latest.get('tool_name', ''))}: {latest.get('reason', '')}")
            if self.recent_validation_results:
                lines.append("### 最近验证")
                for item in self.recent_validation_results[-2:]:
                    verdict = "通过" if item.get("passed") else "失败"
                    lines.append(f"- {item.get('kind', 'validation')}: {verdict} | {item.get('summary', '')}")
            if self.recent_blockers:
                lines.append("### 最近阻塞")
                recent_unique: List[str] = []
                seen = set()
                for item in reversed(self.recent_blockers):
                    summary = f"- {item.get('kind', 'blocker')}: {item.get('summary', '')}"
                    if summary in seen:
                        continue
                    recent_unique.append(summary)
                    seen.add(summary)
                    if len(recent_unique) >= 2:
                        break
                for line in reversed(recent_unique):
                    lines.append(line)
            rendered = "\n".join(lines).strip()
            if len(rendered) > 900:
                rendered = rendered[:897].rstrip() + "..."
            return rendered

    def get_active_evolution_txn(self) -> Optional[str]:
        """读取当前会话激活的演化事务。"""
        with self._lock:
            return self.active_evolution_txn_id

    def get_attention_snapshot(self) -> Dict[str, Any]:
        """获取当前会话的短期注意力快照。"""
        with self._lock:
            entity_list: List[str] = []
            for entities in self.modified_entities.values():
                entity_list.extend(entities)
            return {
                "modified_paths": list(self.modified_paths),
                "modified_entities": list(dict.fromkeys(entity_list)),
                "dirty_since": self.dirty_since,
                "active_git_base": self.active_git_base,
                "last_git_scan_at": self.last_git_scan_at,
                "last_validation_summary": self.last_validation_summary,
                "last_validation_passed": self.last_validation_passed,
                "active_evolution_txn_id": self.active_evolution_txn_id,
                "blocked_tool_patterns": dict(self.blocked_tool_patterns),
                "recent_blockers": list(self.recent_blockers),
                "recent_validation_results": list(self.recent_validation_results),
                "language_drift_count": self.language_drift_count,
                "diagnostic_phase": self.diagnostic_phase,
                "diagnostic_drift": self._has_diagnostic_drift_unlocked(),
                "feedback_loop_ready": self.feedback_loop_ready,
                "feedback_loop_type": self.feedback_loop_type,
                "feedback_loop_target": self.feedback_loop_target,
                "feedback_loop_last_result": self.feedback_loop_last_result,
                "scope_frozen": self.scope_frozen,
                "scope_anchor": self.scope_anchor,
                "convergence_state": self.convergence_state,
                "stop_reason": self.stop_reason,
                "expansion_denied_count": self.expansion_denied_count,
                "dirty_summary": f"最近修改 {len(self.modified_paths)} 个路径" if self.modified_paths else "",
                "reading_task": self.reading_task,
                "reading_recommendation": self.reading_recommendation,
                "reading_sufficiency": self.reading_sufficiency,
                "next_tool_intent": self.next_tool_intent,
                "recommended_tools": list(self.recommended_tools),
                "avoid_tools": list(self.avoid_tools),
                "tool_deviations": list(self.tool_deviations),
                "read_ranges": dict(self.read_ranges),
                "read_entities": dict(self.read_entities),
                "read_searches": list(self.read_searches),
                "pending_continuations": list(self.pending_continuations),
                "active_delegation": dict(self.active_delegation) if self.active_delegation else None,
                "delegation_history": list(self.delegation_history),
                "delegation_findings": list(self.delegation_findings),
                "delegation_failures": list(self.delegation_failures),
                "delegation_evidence_digest": self.delegation_evidence_digest,
            }


def is_probable_language_drift(text: str) -> bool:
    """轻量启发式：判断自然语言是否明显漂向英文。

    检测两种模式：
    1. 大段英文漂移（>=24个英文单词，英文占比超过中文）
    2. 中英混合段落（中文主体中混入多个英文单词，英文占比 > 30%）
    """
    if not text:
        return False
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"`[^`]*`", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    english_words = re.findall(r"\b[a-zA-Z]{3,}\b", cleaned)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", cleaned)

    # 模式 1: 大段英文漂移（原有逻辑）
    if len(english_words) >= 24:
        if len(english_words) > max(len(chinese_chars), 8):
            return True

    # 模式 2: 中英混合段落检测
    # 如果中文字符 >= 10 且英文单词 >= 4，检测英文占比
    if len(chinese_chars) >= 10 and len(english_words) >= 4:
        # 排除纯技术性内容（如代码路径、命令、文件扩展名）
        code_pattern = re.compile(
            r'^[a-zA-Z][\w./\\-]*\.(py|md|toml|json|yaml|yml|txt|csv)$'
            r'|^\d+[KMGT]?$'
            r'|^\w+/\w+$'
        )
        non_code_words = [w for w in english_words if not code_pattern.match(w)]
        if len(non_code_words) >= 4:
            # 计算英文单词在总单词中的占比（简化：总词数约等于中文字符/2 + 非代码英文单词）
            total_estimate = len(chinese_chars) / 2 + len(non_code_words)
            english_ratio = len(non_code_words) / max(total_estimate, 1)
            # 如果英文单词占比超过 30%，认为是语言漂移
            if english_ratio > 0.30:
                return True

    return False

# 单例实例
_agent_session: Optional[AgentSessionState] = None
_session_lock = threading.Lock()


def get_session_state() -> AgentSessionState:
    """获取全局 Session 状态单例"""
    global _agent_session
    if _agent_session is None:
        with _session_lock:
            if _agent_session is None:
                _agent_session = AgentSessionState()
    return _agent_session


def reset_session_state() -> AgentSessionState:
    """重置全局 Session 单例，供测试或新轮次使用。"""
    global _agent_session
    with _session_lock:
        _agent_session = AgentSessionState()
        return _agent_session


__all__ = [
    "AgentSessionState",
    "get_session_state",
    "reset_session_state",
    "is_probable_language_drift",
]
