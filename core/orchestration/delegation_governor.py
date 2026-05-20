# -*- coding: utf-8 -*-
"""委派治理器。

把子 agent 的委派判定、派发、结果回收从 agent.py 主循环中抽离，
让主循环只保留是否委派以及如何继续推进的高层调度职责。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.infrastructure.agent_session import get_session_state
from core.infrastructure.runtime_input import (
    build_delegation_evidence_message,
    build_delegation_failure_message,
)
from core.logging.logger import debug as _debug_logger
from core.orchestration.subagent_roles import (
    ALLOWED_SUBAGENT_TASK_TYPES,
    SubagentRoleNeed,
    get_subagent_role_spec,
)
from core.ui.cli_ui import get_ui
from tools.agent_tools import set_subagent_stream_sink


SpawnExecuteFn = Callable[[str, dict], Tuple[Any, Optional[str]]]
SyncStateMemoryFn = Callable[[], None]
UIGetterFn = Callable[[], Any]
SessionGetterFn = Callable[[], Any]
TurnStopCheckerFn = Callable[[], str]


class DelegationGovernor:
    """负责委派请求构建、子 agent 派发与结果回收。"""

    ALLOWED_TASK_TYPES = ALLOWED_SUBAGENT_TASK_TYPES

    def __init__(
        self,
        *,
        spawn_execute: SpawnExecuteFn,
        sync_runtime_state_memory: SyncStateMemoryFn,
        ui_getter: UIGetterFn = get_ui,
        session_getter: SessionGetterFn = get_session_state,
        turn_stop_checker: Optional[TurnStopCheckerFn] = None,
    ) -> None:
        self._spawn_execute = spawn_execute
        self._sync_runtime_state_memory = sync_runtime_state_memory
        self._ui_getter = ui_getter
        self._session_getter = session_getter
        self._turn_stop_checker = turn_stop_checker

    @staticmethod
    def contains_any(text: str, keywords: List[str]) -> bool:
        lowered = (text or "").lower()
        return any(keyword.lower() in lowered for keyword in keywords)

    @classmethod
    def should_stop_after_useful_delegation(
        cls,
        *,
        task_type: str,
        goal: str,
    ) -> bool:
        normalized_goal = (goal or "").strip().lower()
        if task_type not in {"inspect", "diagnose", "verify", "summarize"}:
            return False
        readonly_markers = [
            "只做诊断",
            "只做分析",
            "仅分析",
            "只读",
            "不要修改代码",
            "不要改代码",
            "不要落地",
            "不要实现",
            "不要修改",
            "do not modify code",
            "read-only",
        ]
        if not cls.contains_any(normalized_goal, readonly_markers):
            return False
        positive_mutate_markers = [
            "然后修改代码",
            "再修改代码",
            "并修改代码",
            "开始修改代码",
            "继续修改代码",
            "修复代码并",
            "实现并",
            "落地修复",
            "apply patch",
            "写入文件",
            "提交 git",
        ]
        return not cls.contains_any(normalized_goal, positive_mutate_markers)

    @classmethod
    def is_readonly_diagnostic_goal(cls, goal: str) -> bool:
        normalized_goal = (goal or "").strip().lower()
        if not normalized_goal:
            return False
        diagnostic_markers = [
            "诊断",
            "分析",
            "归因",
            "日志",
            "log",
            "超时",
            "timeout",
            "只读",
            "read-only",
        ]
        if not cls.contains_any(normalized_goal, diagnostic_markers):
            return False
        return cls.should_stop_after_useful_delegation(task_type="diagnose", goal=goal)

    @classmethod
    def is_readonly_summary_goal(cls, goal: str) -> bool:
        normalized_goal = (goal or "").strip().lower()
        if not normalized_goal:
            return False
        summary_markers = [
            "总结",
            "汇总",
            "摘要",
            "归纳",
            "整理结论",
            "收束结论",
            "总结一下",
            "summarize",
            "summary",
            "wrap up",
        ]
        if not cls.contains_any(normalized_goal, summary_markers):
            return False
        return cls.should_stop_after_useful_delegation(task_type="summarize", goal=goal)

    @classmethod
    def is_explicit_inspect_goal(cls, goal: str) -> bool:
        normalized_goal = (goal or "").strip().lower()
        if not normalized_goal:
            return False
        inspect_markers = [
            "检查",
            "看看",
            "查看",
            "审查",
            "inspect",
            "review",
            "配置",
            "config",
            "prompt",
            "单文件",
            "当前修改链路",
        ]
        if not cls.contains_any(normalized_goal, inspect_markers):
            return False
        diagnostic_markers = [
            "诊断",
            "归因",
            "超时",
            "timeout",
            "重复",
            "循环",
            "失败",
            "报错",
            "traceback",
            "error",
        ]
        return not cls.contains_any(normalized_goal, diagnostic_markers)

    @staticmethod
    def has_delegation_reading_load(snapshot: Dict[str, Any]) -> bool:
        modified_paths = snapshot.get("modified_paths", []) or []
        recent_blockers = snapshot.get("recent_blockers", []) or []
        blocker_with_anchor = sum(
            1
            for item in recent_blockers
            if DelegationGovernor.has_textual_delegation_anchor(str(item.get("summary") or "").strip())
        )
        return bool(
            len(modified_paths) >= 2
            or len(recent_blockers) >= 3
            or blocker_with_anchor >= 1
        )

    @staticmethod
    def is_unhelpful_terminal_delegation(entry: Dict[str, Any]) -> bool:
        status = str(entry.get("status") or "").strip().lower()
        if status == "failed":
            return True
        if status != "completed":
            return False
        confidence = str(entry.get("confidence") or "").strip().lower()
        findings = entry.get("findings") or []
        summary = str(entry.get("summary") or "").strip()
        if confidence == "low" and not findings:
            return True
        return not summary and not findings

    @classmethod
    def should_cooldown_delegation(
        cls,
        snapshot: Dict[str, Any],
        task_type: str,
    ) -> bool:
        terminal_entries = [
            item
            for item in (snapshot.get("delegation_history", []) or [])
            if str(item.get("task_type") or "") == (task_type or "")
            and str(item.get("status") or "").strip().lower() in {"completed", "failed"}
        ]
        if len(terminal_entries) < 2:
            return False
        recent = terminal_entries[-2:]
        return all(cls.is_unhelpful_terminal_delegation(item) for item in recent)

    @staticmethod
    def is_readonly_subagent_process() -> bool:
        return os.environ.get("VIBELUTION_SUBAGENT_MODE", "").strip().lower() == "readonly"

    @staticmethod
    def is_broad_autonomous_goal(goal: str) -> bool:
        text = (goal or "").strip().lower()
        if not text:
            return False
        broad_markers = [
            "开始自主进化",
            "自主进化",
            "开始进化",
            "检查当前项目状态",
            "查看当前状态",
            "了解当前状态",
            "start self evolution",
            "self evolve",
            "self-evolve",
        ]
        return any(marker in text for marker in broad_markers)

    @staticmethod
    def is_restart_focused_goal(goal: str) -> bool:
        text = (goal or "").strip().lower()
        if not text:
            return False
        negative_markers = [
            "不要调用 trigger_self_restart_tool",
            "不调用 trigger_self_restart_tool",
            "禁止调用 trigger_self_restart_tool",
            "不要触发重启",
            "不触发重启",
            "禁止重启",
            "不要重启",
            "不重启",
            "do not call trigger_self_restart_tool",
            "don't call trigger_self_restart_tool",
            "do not restart",
            "don't restart",
            "without restart",
            "non-restart",
        ]
        if any(marker in text for marker in negative_markers):
            return False
        restart_markers = [
            "trigger_self_restart_tool",
            "重启你自己",
            "重启自己",
            "完成重启",
            "触发重启",
            "执行重启",
            "restart yourself",
            "self restart",
            "self-restart",
        ]
        return any(marker in text for marker in restart_markers)

    @staticmethod
    def is_full_evolution_goal(goal: str) -> bool:
        """识别需要先关账、再触发自我重启的完整进化闭环目标。"""
        text = (goal or "").strip().lower()
        if not text:
            return False
        if not DelegationGovernor.is_restart_focused_goal(text):
            return False
        close_markers = [
            "close_evolution_transaction_tool",
            "关账",
            "关闭演化事务",
            "close transaction",
            "close evolution transaction",
        ]
        return any(marker in text for marker in close_markers)

    @staticmethod
    def is_harness_probe_goal(goal: str) -> bool:
        text = (goal or "").strip().lower()
        if not text:
            return False
        probe_markers = [
            "harness transaction probe",
            "harness safe modify probe",
            "gym probe",
            "coordination workflow gym probe",
            "local transaction closing gym probe",
            "安全修改/回滚演化探针",
            "非重启演化事务探针",
            "safe_modify_probe.py",
            "do not call spawn_agent_tool",
            "do not delegate",
        ]
        return any(marker in text for marker in probe_markers)

    @staticmethod
    def has_textual_delegation_anchor(text: str) -> bool:
        return bool(
            re.search(
                r"(log_info[\\/].+\.(jsonl|log))|([\w./\\-]+\.(py|md|toml|json|yaml|yml))|(tests?[/\\][\w./\\-]+)",
                (text or "").strip(),
                re.IGNORECASE,
            )
        )

    @staticmethod
    def is_success_validation_summary(summary: str, passed: bool) -> bool:
        text = (summary or "").strip().lower()
        if not text:
            return bool(passed)
        if passed:
            return True
        success_markers = (
            "pytest 通过",
            "ruff lint 通过",
            "python -m py_compile 通过",
            " passed",
            "passed ",
            "::passed",
            "== passed",
        )
        return any(marker in text for marker in success_markers)

    @classmethod
    def narrow_delegation_goal_from_snapshot(
        cls,
        snapshot: Dict[str, Any],
        *,
        allow_modified_paths: bool = True,
    ) -> str:
        blockers = snapshot.get("recent_blockers", []) or []
        for item in reversed(blockers):
            kind = str(item.get("kind") or "")
            summary = str(item.get("summary") or "").strip()
            if (
                kind in {"duplicate_search", "duplicate_read", "duplicate_read_guard", "diagnostic_drift"}
                and summary
                and cls.has_textual_delegation_anchor(summary)
            ):
                return f"分析当前轮为什么出现：{summary}"

        validation_summary = str(snapshot.get("last_validation_summary") or "").strip()
        if validation_summary and not cls.is_success_validation_summary(
            validation_summary,
            bool(snapshot.get("last_validation_passed")),
        ):
            return f"分析最近验证失败的根因：{validation_summary}"

        modified_paths = snapshot.get("modified_paths", []) or []
        if allow_modified_paths and modified_paths:
            target = str(modified_paths[-1]).strip()
            if target:
                return f"检查当前修改链路是否已具备收束条件：{target}"
        return ""

    @classmethod
    def has_concrete_delegation_anchor(cls, goal: str, snapshot: Dict[str, Any]) -> bool:
        text = (goal or "").strip()
        if cls.has_textual_delegation_anchor(text):
            return True

        validation_summary = str(snapshot.get("last_validation_summary") or "").strip()
        if validation_summary and not cls.is_success_validation_summary(
            validation_summary,
            bool(snapshot.get("last_validation_passed")),
        ):
            return True

        for item in snapshot.get("recent_blockers", []) or []:
            summary = str(item.get("summary") or "").strip()
            if cls.has_textual_delegation_anchor(summary):
                return True
        return False

    @staticmethod
    def is_same_delegation_failure_class(
        *,
        task_type: str,
        goal: str,
        failed_item: Dict[str, Any],
    ) -> bool:
        if str(failed_item.get("task_type") or "") != (task_type or ""):
            return False
        normalized_goal = (goal or "").strip()
        failed_goal = str(failed_item.get("goal") or "").strip()
        if not normalized_goal or not failed_goal:
            return False

        drift_marker = "连续进行推理但没有新增观测"
        if drift_marker in normalized_goal and drift_marker in failed_goal:
            return True
        if normalized_goal == failed_goal:
            return True
        if normalized_goal.startswith("分析当前轮为什么出现：") and failed_goal.startswith("分析当前轮为什么出现："):
            return True
        return False

    def build_delegation_context_pack(self, goal: str) -> str:
        session = self._session_getter()
        snapshot = session.get_attention_snapshot()
        parts: List[str] = []

        if goal:
            parts.append(f"- 当前问题摘要: {goal}")
        if snapshot.get("recent_blockers"):
            parts.append("- 最近阻塞:")
            for item in snapshot["recent_blockers"][-3:]:
                parts.append(f"  - {item.get('kind', 'blocker')}: {item.get('summary', '')}")
        if snapshot.get("last_validation_summary"):
            verdict = "通过" if snapshot.get("last_validation_passed") else "失败"
            parts.append(f"- 最近验证: {verdict} | {snapshot.get('last_validation_summary')}")
        if snapshot.get("modified_paths"):
            parts.append("- 最近修改路径:")
            for path in snapshot["modified_paths"][-4:]:
                parts.append(f"  - {path}")
        if snapshot.get("delegation_evidence_digest"):
            parts.append("- 既有委派证据摘要:")
            parts.append(snapshot["delegation_evidence_digest"])
        return "\n".join(parts).strip()

    @staticmethod
    def extract_live_thought_from_subagent_output(buffer: str) -> str:
        text = buffer or ""
        matches = re.findall(r"<think>([\s\S]*?)</think>", text, flags=re.IGNORECASE)
        if matches:
            return matches[-1].strip()
        open_match = re.search(r"<think>([\s\S]*)$", text, flags=re.IGNORECASE)
        if open_match:
            return open_match.group(1).strip()
        return ""

    def infer_role_need(
        self,
        *,
        goal: str,
        snapshot: Dict[str, Any],
        iteration: int,
        total_tool_calls: int,
        readonly_diagnostic_goal: bool,
        readonly_summary_goal: bool,
        explicit_inspect_goal: bool,
        summary_goal_requested: bool,
        summary_evidence_ready: bool,
        reading_load_ready: bool,
        last_validation_summary: str,
    ) -> Optional[SubagentRoleNeed]:
        normalized_goal = (goal or "").strip()
        lowered_goal = normalized_goal.lower()
        analyze_keywords = ["日志", "log", "配置", "config", "prompt", "测试", "循环", "重复", "归因", "诊断"]
        mutate_keywords = ["修改", "实现", "重构", "提交", "写入", "落地", "修复代码"]

        if (
            iteration == 1
            and self.contains_any(lowered_goal, analyze_keywords)
            and (readonly_diagnostic_goal or not self.contains_any(lowered_goal, mutate_keywords))
        ):
            task_type = "diagnose" if self.contains_any(lowered_goal, ["循环", "重复", "归因", "诊断", "日志", "测试"]) else "inspect"
            return SubagentRoleNeed(
                task_type=task_type,
                trigger_reason="explicit_readonly_goal",
                why_now="用户已经明确提出只读分析目标，适合先隔离局部认知负担。",
            )
        if readonly_summary_goal and summary_goal_requested and summary_evidence_ready and (total_tool_calls >= 3 or iteration >= 2):
            return SubagentRoleNeed(
                task_type="summarize",
                trigger_reason="evidence_compression_needed",
                why_now="现场已有足够证据，当前更缺的是低熵压缩而不是继续探查。",
            )
        if snapshot.get("diagnostic_drift") or any(
            item.get("kind") in {"duplicate_search", "duplicate_read", "duplicate_read_guard", "diagnostic_drift"}
            for item in (snapshot.get("recent_blockers", []) or [])
        ):
            return SubagentRoleNeed(
                task_type="diagnose",
                trigger_reason="failure_attribution_needed",
                why_now="主流程已经出现漂移或重复读取，更缺的是局部故障归因证据。",
            )
        if (
            explicit_inspect_goal
            and not readonly_diagnostic_goal
            and not snapshot.get("diagnostic_drift")
            and not last_validation_summary
            and reading_load_ready
            and (
                self.has_concrete_delegation_anchor(normalized_goal, snapshot)
                or bool(snapshot.get("modified_paths"))
            )
            and (total_tool_calls >= 2 or iteration >= 2)
        ):
            return SubagentRoleNeed(
                task_type="inspect",
                trigger_reason="local_state_probe_needed",
                why_now="当前缺的是局部静态状态核查，而不是继续全局推理。",
            )
        return None

    def build_request(
        self,
        *,
        goal: str,
        iteration: int,
        total_tool_calls: int,
    ) -> Optional[Dict[str, Any]]:
        if self.is_readonly_subagent_process():
            return None
        session = self._session_getter()
        snapshot = session.get_attention_snapshot()
        normalized_goal = (goal or "").strip()
        lowered_goal = normalized_goal.lower()
        readonly_diagnostic_goal = self.is_readonly_diagnostic_goal(normalized_goal)
        readonly_summary_goal = self.is_readonly_summary_goal(normalized_goal)
        broad_autonomous_goal = self.is_broad_autonomous_goal(normalized_goal)
        last_validation_summary = str(snapshot.get("last_validation_summary") or "").strip()
        last_validation_passed = bool(snapshot.get("last_validation_passed"))
        validation_success = self.is_success_validation_summary(
            last_validation_summary,
            last_validation_passed,
        )
        recent_blockers = snapshot.get("recent_blockers", []) or []
        modified_paths = snapshot.get("modified_paths", []) or []
        delegation_evidence_digest = str(snapshot.get("delegation_evidence_digest") or "").strip()
        if not normalized_goal:
            return None
        if self.is_restart_focused_goal(normalized_goal):
            return None
        if self.is_harness_probe_goal(normalized_goal):
            return None
        if snapshot.get("active_evolution_txn_id") and not readonly_diagnostic_goal and not readonly_summary_goal:
            return None
        if readonly_diagnostic_goal:
            if snapshot.get("delegation_history") or snapshot.get("delegation_failures"):
                return None
        if readonly_summary_goal and snapshot.get("delegation_history"):
            return None

        readonly_constraints = {
            "readonly": True,
            "max_steps": 3 if readonly_diagnostic_goal else 6,
            "max_output_chars": 2400 if readonly_diagnostic_goal else 3200,
            "stop_rule": "找到足够证据就停止；若证据不足，明确返回缺口，不扩散任务。",
        }
        deliverables = [
            "status",
            "summary",
            "findings",
            "evidence",
            "recommended_next_action",
            "confidence",
        ]
        summary_keywords = ["总结", "汇总", "摘要", "归纳", "收束", "总结一下", "summarize", "summary", "wrap up"]

        task_type = ""
        scope: Any = {}
        delegation_goal = normalized_goal
        summary_evidence_ready = bool(
            last_validation_summary
            or recent_blockers
            or modified_paths
            or delegation_evidence_digest
        )
        summary_goal_requested = self.contains_any(lowered_goal, summary_keywords)
        explicit_inspect_goal = self.is_explicit_inspect_goal(normalized_goal)
        reading_load_ready = self.has_delegation_reading_load(snapshot)
        if summary_goal_requested and not readonly_summary_goal:
            return None
        if readonly_summary_goal and summary_goal_requested and not summary_evidence_ready:
            return None
        role_need = self.infer_role_need(
            goal=normalized_goal,
            snapshot=snapshot,
            iteration=iteration,
            total_tool_calls=total_tool_calls,
            readonly_diagnostic_goal=readonly_diagnostic_goal,
            readonly_summary_goal=readonly_summary_goal,
            explicit_inspect_goal=explicit_inspect_goal,
            summary_goal_requested=summary_goal_requested,
            summary_evidence_ready=summary_evidence_ready,
            reading_load_ready=reading_load_ready,
            last_validation_summary=last_validation_summary,
        )
        if not role_need:
            return None
        task_type = role_need.task_type
        if role_need.trigger_reason == "explicit_readonly_goal":
            scope = {
                "goal": normalized_goal,
                "modified_paths": modified_paths[-4:],
                "recent_blockers": [item.get("kind", "") for item in recent_blockers[-4:]],
            }
        elif role_need.trigger_reason == "evidence_compression_needed":
            readonly_constraints = {
                "readonly": True,
                "max_steps": 3,
                "max_output_chars": 2200,
                "stop_rule": "只压缩已有证据并返回结论，不新增探查链路；若证据不足，明确指出缺口并停止。",
            }
            scope = {
                "goal": normalized_goal,
                "last_validation_summary": last_validation_summary,
                "recent_blockers": [item.get("summary", "") for item in recent_blockers[-4:]],
                "modified_paths": modified_paths[-4:],
                "delegation_evidence_digest": delegation_evidence_digest[:400],
            }
        elif role_need.trigger_reason == "failure_attribution_needed":
            if broad_autonomous_goal and any(
                str(item.get("task_type") or "") == "diagnose"
                for item in snapshot.get("delegation_failures", []) or []
            ):
                return None
            scope = {
                "goal": normalized_goal,
                "recent_blockers": [item.get("summary", "") for item in recent_blockers[-4:]],
            }
            narrowed = self.narrow_delegation_goal_from_snapshot(snapshot, allow_modified_paths=False)
            if narrowed:
                delegation_goal = narrowed
            if broad_autonomous_goal and not self.has_concrete_delegation_anchor(delegation_goal, snapshot):
                return None
        elif role_need.trigger_reason == "local_state_probe_needed":
            scope = {
                "goal": normalized_goal,
                "modified_paths": modified_paths[-4:],
            }
            narrowed = self.narrow_delegation_goal_from_snapshot(snapshot)
            if narrowed:
                delegation_goal = narrowed

        if not task_type:
            return None
        if task_type not in self.ALLOWED_TASK_TYPES:
            return None
        if (
            self.should_cooldown_delegation(snapshot, task_type)
            and not readonly_diagnostic_goal
            and not readonly_summary_goal
            and not explicit_inspect_goal
        ):
            return None
        if task_type == "diagnose" and validation_success and "验证失败" in delegation_goal:
            return None
        if broad_autonomous_goal and delegation_goal == normalized_goal:
            return None
        if session.has_recent_delegation(task_type, delegation_goal, scope):
            return None
        for item in snapshot.get("delegation_failures", []):
            if self.is_same_delegation_failure_class(
                task_type=task_type,
                goal=delegation_goal,
                failed_item=item,
            ):
                return None
        for item in snapshot.get("delegation_history", []):
            if (
                item.get("task_type") == task_type
                and item.get("goal") == delegation_goal
                and item.get("scope_signature") == session._normalize_scope_signature(scope)
            ):
                return None

        role_spec = get_subagent_role_spec(task_type)
        return {
            "task_type": task_type,
            "role_name": role_spec.role_name,
            "role_purpose": role_spec.system_purpose,
            "role_need": {
                "trigger_reason": role_need.trigger_reason,
                "why_now": role_need.why_now,
            },
            "goal": delegation_goal,
            "root_goal": normalized_goal,
            "scope": scope,
            "constraints": readonly_constraints,
            "deliverables": deliverables,
            "context_pack": self.build_delegation_context_pack(delegation_goal),
            "timeout": 120,
        }

    def apply_result(
        self,
        payload: Dict[str, Any],
        result_text: str,
        messages: list,
    ) -> Dict[str, Any]:
        ui = self._ui_getter()
        session = self._session_getter()
        try:
            result = json.loads(result_text or "{}")
        except Exception:
            fallback_text = str(result_text or "").strip()
            if fallback_text.startswith("[超时]"):
                result = {
                    "status": "timeout",
                    "summary": fallback_text,
                    "recommended_next_action": "主 agent 接管",
                    "confidence": "low",
                    "raw_output": fallback_text[:2000],
                    "process_output": fallback_text[:2000],
                }
            else:
                result = {
                    "status": "failed",
                    "summary": "子 agent 返回了不可解析结果",
                    "recommended_next_action": "主 agent 接管",
                    "confidence": "low",
                    "raw_output": fallback_text[:2000],
                    "process_output": fallback_text[:2000],
                }

        summary = str(result.get("summary") or "").strip()
        findings = result.get("findings") or []
        if not isinstance(findings, list):
            findings = [str(findings)]
        recommended_next = str(result.get("recommended_next_action") or "").strip()
        confidence = str(result.get("confidence") or "").strip()
        status = str(result.get("status") or "").strip().lower()
        evidence = result.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = [str(evidence)]
        process_output = str(result.get("process_output") or "").strip()
        raw_output = str(result.get("raw_output") or "").strip()
        fast_path = str(result.get("fast_path") or "").strip()
        scope = payload.get("scope")

        thought_parts: List[str] = []
        if findings:
            thought_parts.append("发现:")
            thought_parts.extend(f"- {str(item).strip()}" for item in findings[:4] if str(item).strip())
        if evidence:
            thought_parts.append("证据:")
            thought_parts.extend(f"- {str(item).strip()}" for item in evidence[:3] if str(item).strip())
        if process_output:
            thought_parts.append("过程:")
            thought_parts.append(process_output[:1200].strip())
        elif raw_output and raw_output != summary:
            thought_parts.append("补充:")
            thought_parts.append(raw_output[:1200].strip())
        thought_text = "\n".join(part for part in thought_parts if part).strip()

        debug_scope = json.dumps(scope, ensure_ascii=False) if scope is not None else ""
        if process_output:
            _debug_logger.info(
                "[Delegation] process "
                f"status={status or 'unknown'} | "
                f"goal={payload.get('goal', '')} | "
                f"scope={debug_scope}\n{process_output[:4000]}",
                tag="SUBAGENT",
            )
        if raw_output and raw_output != process_output:
            log_fn = _debug_logger.warning if status in {"timeout", "failed", "error"} else _debug_logger.info
            log_fn(
                "[Delegation] raw "
                f"status={status or 'unknown'} | "
                f"goal={payload.get('goal', '')} | "
                f"scope={debug_scope}\n{raw_output[:4000]}",
                tag="SUBAGENT",
            )

        useful_statuses = {"completed", "success", "ok", "partial"}
        summary_is_think_only = bool(summary) and summary.strip().lower().startswith("<think>")
        summary_effective = "" if summary_is_think_only else summary
        if status in useful_statuses and summary_effective:
            should_stop_round = self.should_stop_after_useful_delegation(
                task_type=str(payload.get("task_type") or "inspect"),
                goal=str(payload.get("root_goal") or payload.get("goal") or ""),
            )
            session.record_delegation_result(
                payload.get("task_type", "inspect"),
                payload.get("goal", ""),
                scope,
                summary_effective,
                findings=findings,
                confidence=confidence,
                recommended_next_action=recommended_next,
            )
            if should_stop_round:
                session.note_scope_completion(
                    recommended_next
                    or "子 agent 已返回足够证据，主 agent 应直接收束。"
                )
            ui.add_log(f"委派完成: {summary_effective}", "INFO")
            ui.add_content(f"[bold cyan]子 agent 证据[/bold cyan] {summary_effective}")
            ui.add_delegation_evidence(summary_effective, next_action=recommended_next, confidence=confidence)
            ui.finish_subagent_activity(
                status=status,
                summary=summary_effective,
                findings=findings,
                evidence=evidence,
                next_action=recommended_next,
                process=process_output or raw_output,
                thought=thought_text,
                mode_hint=(
                    "快速日志诊断，未启动真实子 agent"
                    if fast_path == "conversation_log_scan"
                    else ""
                ),
            )
            if recommended_next:
                ui.add_content(f"[dim]下一步建议:[/dim] {recommended_next}")
            messages.append(build_delegation_evidence_message(
                f"{summary_effective}\n下一步建议: {recommended_next or '主 agent 自行裁决'}"
            ))
            outcome = {
                "delegated": True,
                "useful": True,
                "summary": summary_effective,
                "break_round": should_stop_round,
            }
        else:
            reason = summary or str(result.get("message") or "子 agent 未返回可用结论").strip()
            session.record_delegation_failure(
                payload.get("task_type", "inspect"),
                payload.get("goal", ""),
                scope,
                reason,
            )
            ui.add_log(f"委派失败: {reason}", "WARN")
            ui.finish_subagent_activity(
                status=status or "failed",
                summary=(
                    f"子 agent 执行超时: {reason}"
                    if (status or "").lower() == "timeout" and "超时" not in reason
                    else reason
                ),
                findings=findings,
                evidence=evidence,
                next_action="主 agent 接管",
                process=process_output or raw_output,
                thought=thought_text or process_output or raw_output,
                mode_hint=(
                    "快速日志诊断，未启动真实子 agent"
                    if fast_path == "conversation_log_scan"
                    else ""
                ),
            )
            messages.append(build_delegation_failure_message(
                f"{reason}\n请主 agent 接管并直接收束。"
            ))
            outcome = {"delegated": True, "useful": False, "summary": reason}

        self._sync_runtime_state_memory()
        return outcome

    def maybe_delegate(
        self,
        *,
        goal: str,
        iteration: int,
        total_tool_calls: int,
        messages: list,
    ) -> Optional[Dict[str, Any]]:
        payload = self.build_request(
            goal=goal,
            iteration=iteration,
            total_tool_calls=total_tool_calls,
        )
        if not payload:
            return None

        ui = self._ui_getter()
        session = self._session_getter()
        session.record_delegation_start(
            payload.get("task_type", "inspect"),
            payload.get("goal", ""),
            payload.get("scope"),
        )
        self._sync_runtime_state_memory()
        ui.add_log(
            f"委派子 agent: {payload.get('task_type', 'inspect')} | {payload.get('goal', '')}",
            "INFO",
        )
        _debug_logger.info(
            "[Delegation] start "
            f"task_type={payload.get('task_type', 'inspect')} | "
            f"goal={payload.get('goal', '')} | "
            f"scope={json.dumps(payload.get('scope'), ensure_ascii=False)} | "
            f"timeout={payload.get('timeout', 120)}",
            tag="AGENT",
        )
        ui.start_subagent_activity(
            payload.get("task_type", "inspect"),
            payload.get("goal", ""),
            payload.get("scope"),
        )
        try:
            from core.logging.unified_logger import logger as unified_logger

            conversation_logger = unified_logger.conversation
        except Exception:
            conversation_logger = None

        live_stdout_chunks: List[str] = []

        def _handle_subagent_stream(event: Dict[str, str]) -> None:
            stream_name = str((event or {}).get("stream") or "").strip().lower()
            text = str((event or {}).get("text") or "")
            if not text:
                return
            if conversation_logger is not None:
                try:
                    conversation_logger.log_subagent_stream(
                        stream_name,
                        text,
                        task_type=payload.get("task_type", "inspect"),
                        goal=payload.get("goal", ""),
                    )
                except Exception:
                    pass
            if stream_name == "stderr":
                ui.add_subagent_process(f"[red]stderr[/red] {text}")
                return

            ui.add_subagent_process(text)
            live_stdout_chunks.append(text)
            thought = self.extract_live_thought_from_subagent_output("\n".join(live_stdout_chunks))
            if thought:
                ui.stream_subagent_thought(thought, done=False)

        set_subagent_stream_sink(_handle_subagent_stream)
        try:
            tool_args = {
                "task_type": payload.get("task_type", "inspect"),
                "goal": payload.get("goal", ""),
                "scope": json.dumps(payload.get("scope"), ensure_ascii=False),
                "constraints": json.dumps(payload.get("constraints"), ensure_ascii=False),
                "deliverables": json.dumps(payload.get("deliverables"), ensure_ascii=False),
                "context_pack": payload.get("context_pack", ""),
                "timeout": payload.get("timeout", 120),
                "_internal_delegate": True,
            }
            if callable(self._turn_stop_checker):
                tool_args["_cancel_checker"] = self._turn_stop_checker
            result, _ = self._spawn_execute(
                "spawn_agent_tool",
                tool_args,
            )
        finally:
            set_subagent_stream_sink(None)
        return self.apply_result(payload, str(result or ""), messages)
