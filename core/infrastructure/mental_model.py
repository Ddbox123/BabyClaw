#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
心智模型 - 元认知引擎

Agent 的「自我感知」系统，负责：
- Layer 1: 实时采集运行时信号（通过 EventBus 全局订阅）
- Layer 2: 基于规则的状态诊断（5 种认知状态）
- Layer 3: 生成元认知干预文本，注入 prompt

设计原则：
- 系统做客观（采集指标 + 规则诊断），LLM 做主观（基于数据调整策略）
- 干预最小化：正常状态不注入任何文本
- 全部数据源复用现有基础设施（EventBus、StateManager）
"""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from core.infrastructure.event_bus import get_event_bus, EventNames, Event
from core.infrastructure.state import get_state_manager


# ============================================================================
# 诊断状态枚举
# ============================================================================

class CognitiveState:
    """认知状态标签"""
    NORMAL = "normal"
    LOOPING = "looping"           # 连续重复同一操作
    THRASHING = "thrashing"       # 工具持续失败
    TUNNEL_VISION = "tunnel_vision"  # 只聚焦单一文件
    PRODUCTIVE = "productive"     # 高效状态
    DISORIENTED = "disoriented"   # 工具使用杂乱无章


# ============================================================================
# 干预文本模板
# ============================================================================

INTERVENTION_TEMPLATES: Dict[str, str] = {
    CognitiveState.LOOPING: (
        "\n\n"
        "---\n"
        "## ⚠️ 元认知警报: 死循环检测\n\n"
        "**症状**: 已连续 {repetition_count} 次调用相同或高度相似的操作，无实质进展。\n\n"
        "**建议**: 立即暂停当前操作路径。回到 SOUL 阶段 1 重新评估——你可能遗漏了关键的前提条件，"
        "或者当前方案的隐性假设不成立。考虑：\n"
        "1. 你缺什么信息？用搜索工具探路，不要继续重复\n"
        "2. 有没有完全不同的解法路径？\n"
        "3. 你的心智模型（对当前问题的理解）是否有根本错误？\n"
    ),
    CognitiveState.THRASHING: (
        "\n\n"
        "---\n"
        "## ⚠️ 元认知警报: 方案失效\n\n"
        "**症状**: 最近 {window_size} 次工具调用成功率仅 {success_rate:.0%}。"
        "你当前的工具使用方式或方案假设可能有系统性偏差。\n\n"
        "**建议**: 不要继续试错。回到 SOUL 阶段 2 推翻当前心智模型，寻找底层原因。\n"
        "失败最多的工具: {top_failing_tool}\n"
    ),
    CognitiveState.TUNNEL_VISION: (
        "\n\n"
        "---\n"
        "## ⚠️ 元认知警报: 隧道视野\n\n"
        "**症状**: 最近 {window_size} 次文件操作全部聚焦于 `{focused_file}`。"
        "你可能忽略了这个修改在其他模块中的连锁影响。\n\n"
        "**建议**: 暂停编辑，运行相关测试验证当前修改是否破坏其他模块。"
        "如果这是一个大重构，先将改动范围扩展到所有受影响的文件，再逐个验证。\n"
    ),
    CognitiveState.DISORIENTED: (
        "\n\n"
        "---\n"
        "## ⚠️ 元认知警报: 方向迷失\n\n"
        "**症状**: 最近 {window_size} 次工具调用分散在 {tool_count} 种不同类型的工具上，"
        "缺乏聚焦，成功率 {success_rate:.0%}。\n\n"
        "**建议**: 你可能忘了最初的目标。请重新阅读当前目标（`current_goal`），"
        "明确下一步需要做什么，而不是在各种工具间跳转。\n"
    ),
}


# ============================================================================
# 默认诊断规则
# ============================================================================

def _default_rules() -> Dict[str, Any]:
    return {
        "looping": {
            "metric": "repetition_count",
            "threshold": 4,
            "window_size": 10,
            "description": "连续重复同一操作超过阈值次",
        },
        "thrashing": {
            "metric": "success_rate",
            "threshold": 0.4,
            "window_size": 8,
            "description": "滑动窗口内工具成功率低于阈值",
        },
        "tunnel_vision": {
            "metric": "file_focus_ratio",
            "threshold": 0.8,
            "window_size": 8,
            "description": "文件操作集中在单一文件",
        },
        "disoriented": {
            "metric": "tool_diversity",
            "threshold": 0.7,
            "window_size": 8,
            "description": "工具使用过于分散且成功率低",
        },
        "version_proliferation": {
            "enabled": True,
            "patterns": [
                r"_backup_\d{8}_\d{6}",  # e.g., core_backup_20260505_235000
                r"_v\d+",                # e.g., file_v1, module_v2
                r"\.\d{8}\.",           # e.g., file.20260505.log
                r"_copy$",              # e.g., file_copy
                r"_old$",               # e.g., file_old
                r"\.bak$",              # e.g., file.bak
            ],
        },
    }

# ============================================================================
# 心智模型数据类
# ============================================================================

@dataclass
class ToolRecord:
    """单次工具调用记录"""
    tool_name: str
    success: bool
    args_summary: str
    timestamp: str
    file_target: Optional[str] = None


@dataclass
class Diagnosis:
    """诊断结果"""
    state: str
    metrics: Dict[str, Any]
    intervention: str
    timestamp: str
    confidence: float


# ============================================================================
# MentalModel 主类
# ============================================================================

class MentalModel:
    """
    元认知引擎

    单例模式，在 SelfEvolvingAgent 初始化时创建，通过 EventBus 全局订阅
    自动采集信号，在每个 prompt 构建周期提供诊断和干预。

    用法:
        mm = MentalModel(workspace_root="workspace")
        # 自动监听 EventBus，无需手动调用采集方法
        diagnosis = mm.diagnose()  # 在 prompt 构建时调用
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, workspace_root: str = "workspace"):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._initialized = False
                    cls._instance = obj
        return cls._instance

    def __init__(self, workspace_root: str = "workspace"):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True

        self._workspace_root = Path(workspace_root) if workspace_root else Path("workspace")
        self._rules_path = self._workspace_root / "mental_model" / "rules.json"
        self._self_model_path = self._workspace_root / "mental_model" / "self_model.json"

        # 确保目录存在
        self._ensure_dirs()

        # 加载诊断规则（支持从 JSON 文件加载，回退到默认规则）
        self._rules = self._load_rules()

        # 事件总线和状态管理器引用
        self._event_bus = get_event_bus()
        self._state_manager = get_state_manager()

        # 滑动窗口：最近工具调用记录
        self._tool_history: deque[ToolRecord] = deque(maxlen=50)

        # 文件聚焦追踪
        self._touched_files: Dict[str, int] = {}  # filepath -> touch count
        self._touched_entities: Dict[str, int] = {}  # entity_ref -> touch count

        # 文件创建追踪（会话级）
        self._agent_created_files: Dict[str, Dict[str, Any]] = {}
        self._last_validation: Dict[str, Any] = {}

        # 元认知统计
        self._diagnosis_history: deque[Diagnosis] = deque(maxlen=20)
        self._intervention_count: int = 0
        self._last_intervention_turn: int = 0

        # 检查点计数（每次 prompt 构建为一个 tick）
        self._tick: int = 0

        # 感知层 — 由 agent.py 注入共享 LLM 实例
        self._shared_llm = None
        self._last_state_output: Dict[str, Any] = {}

        # 注册全局事件监听
        self._register_listeners()

    def _ensure_dirs(self):
        """确保心智模型工作目录存在"""
        mm_dir = self._workspace_root / "mental_model"
        mm_dir.mkdir(parents=True, exist_ok=True)

    def _rules_file_exists(self) -> bool:
        """检查规则配置文件是否存在"""
        project_root = self._find_project_root()
        full_path = project_root / self._rules_path
        return full_path.exists()

    def _find_project_root(self) -> Path:
        """查找项目根目录"""
        current = Path(__file__).parent.parent.parent
        if (current / "agent.py").exists():
            return current
        return current

    def _load_rules(self) -> Dict[str, Any]:
        """加载诊断规则，优先从 JSON 文件读取，回退默认规则"""
        project_root = self._find_project_root()
        full_path = project_root / self._rules_path

        if full_path.exists():
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    custom_rules = json.load(f)
                # 合并：用自定义规则覆盖默认规则的对应项
                rules = _default_rules()
                rules.update(custom_rules)
                return rules
            except (json.JSONDecodeError, IOError):
                pass

        return _default_rules()

    def reload_rules(self) -> bool:
        """重新加载规则配置（Agent 修改 rules.json 后调用）"""
        self._rules = self._load_rules()
        return True

    def get_rules(self) -> Dict[str, Any]:
        """获取当前规则（只读副本，供 Agent 查看）"""
        import copy
        return copy.deepcopy(self._rules)

    def update_rules(self, new_rules: Dict[str, Any]) -> bool:
        """
        更新诊断规则并持久化到 JSON 文件。
        Agent 可以通过工具调用此方法修改自己的诊断规则。
        """
        # 合并
        self._rules.update(new_rules)

        project_root = self._find_project_root()
        full_path = project_root / self._rules_path

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                json.dump(self._rules, f, ensure_ascii=False, indent=2)
            return True
        except IOError:
            return False

    def _register_listeners(self):
        """注册 EventBus 全局监听器"""
        self._event_bus.subscribe_global(self._on_event)
        self._event_bus.subscribe(EventNames.WORKSPACE_FILE_CREATED, self._on_file_created)
        self._event_bus.subscribe(EventNames.WORKSPACE_FILE_MODIFIED, self._on_file_modified)
        self._event_bus.subscribe(EventNames.VALIDATION_COMPLETED, self._on_validation_completed)

    def _on_event(self, event: Event):
        """全局事件处理 - 采集运行时信号"""
        try:
            if event.name == EventNames.TOOL_START:
                self._on_tool_start(event)
            elif event.name == EventNames.TOOL_SUCCESS:
                self._on_tool_result(event, success=True)
            elif event.name == EventNames.TOOL_ERROR:
                self._on_tool_result(event, success=False)
            elif event.name == "state:change":
                pass  # 保留用于未来扩展
        except Exception:
            pass  # 监听器静默失败，不干扰主流程

    def _on_file_modified(self, event: Event):
        """同步会话注意力中的实体聚焦信息。"""
        try:
            from core.infrastructure.agent_session import get_session_state
            attention = get_session_state().get_attention_snapshot()
            for path in attention.get("modified_paths", []):
                self._touched_files[path] = self._touched_files.get(path, 0) + 1
            for entity in attention.get("modified_entities", []):
                self._touched_entities[entity] = self._touched_entities.get(entity, 0) + 1
        except Exception:
            pass

    def _on_validation_completed(self, event: Event):
        """记录最近一次验证结果。"""
        self._last_validation = dict(event.data or {})

    def _on_tool_start(self, event: Event):
        """工具开始执行"""
        data = event.data or {}
        tool_name = data.get('name', 'unknown')
        args = data.get('args', {})

        # 提取文件目标
        file_target = self._extract_file_target(tool_name, args)

        if file_target:
            self._touched_files[file_target] = self._touched_files.get(file_target, 0) + 1

    def _on_tool_result(self, event: Event, success: bool):
        """工具执行结果"""
        data = event.data or {}
        tool_name = data.get('name', 'unknown')
        result_preview = str(data.get('result', ''))[:100]

        record = ToolRecord(
            tool_name=tool_name,
            success=success,
            args_summary=result_preview,
            timestamp=datetime.now().isoformat(),
            file_target=self._extract_file_target(tool_name, {}),
        )
        self._tool_history.append(record)

    def _extract_file_target(self, tool_name: str, args: dict) -> Optional[str]:
        """从工具名称和参数中提取目标文件路径"""
        file_modifying_tools = {
            'apply_diff_edit_tool', 'write_file_tool',
            'read_file_tool', 'replace_in_file_tool',
        }

        if tool_name not in file_modifying_tools:
            return None

        # 尝试从参数中提取文件路径
        for key in ('file_path', 'filepath', 'path', 'target_file'):
            if key in args and isinstance(args[key], str):
                return args[key]

        return None

    def _on_file_created(self, event: Event):
        """处理文件创建事件，记录到会话追踪中"""
        try:
            data = event.data or {}
            file_path = data.get("path", "")
            if not file_path:
                return

            abs_path = str(Path(file_path).resolve())
            tool_name = data.get("tool_name", "unknown")
            file_size = data.get("size", 0)

            is_variant = self._detect_version_proliferation(abs_path)

            self._agent_created_files[abs_path] = {
                "path": abs_path,
                "tool_name": tool_name,
                "timestamp": datetime.now().isoformat(),
                "size_bytes": file_size,
                "is_variant": is_variant,
                "variant_base": is_variant if is_variant else None,
            }

            # 检测到版本增殖时发送通知
            if is_variant:
                self._event_bus.publish(EventNames.WORKSPACE_DEBRIS_DETECTED, {
                    "path": abs_path,
                    "variant_base": is_variant,
                    "message": f"检测到版本增殖: {abs_path} (基础文件: {is_variant})",
                })
        except Exception:
            pass

    def _detect_version_proliferation(self, file_path: str) -> Optional[str]:
        """检测文件是否为版本增殖，返回基础文件名或 None"""
        import re

        fname = os.path.basename(file_path)
        stem = os.path.splitext(fname)[0]

        # 检查版本增殖模式
        variant_patterns = [
            r"^(.+)_v\d+$",
            r"^(.+)_fix(_[a-z]+)?$",
            r"^fix_(.+)$",
            r"^(.+)_patch([_a-z]*)?$",
            r"^patch_(.+)$",
            r"^(.+)_temp([_a-z]*)?$",
            r"^temp_(.+)$",
            r"^(.+)_debug([_a-z]*)?$",
            r"^debug_(.+)$",
            r"^(.+)_final$",
            r"^(.+)_old$",
            r"^old_(.+)$",
        ]

        for pattern in variant_patterns:
            m = re.match(pattern, stem, re.IGNORECASE)
            if m:
                base_stem = m.group(1)
                # 检查基础文件是否在已追踪文件中
                for tracked_path, info in self._agent_created_files.items():
                    tracked_stem = os.path.splitext(os.path.basename(tracked_path))[0]
                    if tracked_stem == base_stem:
                        return tracked_path
                # 基础文件不在本次会话中，但仍然标记为变体
                return f"(未知基础文件: {base_stem})"

        return None

    def get_agent_created_files(self) -> Dict[str, Dict[str, Any]]:
        """返回本次会话创建的所有文件记录"""
        return dict(self._agent_created_files)

    def get_version_variants(self) -> List[Dict[str, Any]]:
        """返回被标记为版本增殖的文件列表"""
        return [
            info for info in self._agent_created_files.values()
            if info.get("is_variant")
        ]

    # =========================================================================
    # 诊断引擎
    # =========================================================================

    def tick(self) -> None:
        """标记一个 prompt 构建周期"""
        self._tick += 1

    def diagnose(self) -> Diagnosis:
        """
        基于采集的信号运行规则诊断。

        Returns:
            Diagnosis 对象，包含状态标签、指标、干预文本
        """
        self._tick += 1

        recent = list(self._tool_history)
        if len(recent) < 3:
            # 数据不足，无法诊断
            return Diagnosis(
                state=CognitiveState.NORMAL,
                metrics={"reason": "insufficient_data", "sample_size": len(recent)},
                intervention="",
                timestamp=datetime.now().isoformat(),
                confidence=0.0,
            )

        # ── 计算指标 ──
        window_size = min(10, len(recent))
        window = recent[-window_size:]

        success_count = sum(1 for r in window if r.success)
        success_rate = success_count / len(window) if window else 1.0

        tool_names = [r.tool_name for r in window]
        unique_tools = len(set(tool_names))
        tool_diversity = unique_tools / len(window) if window else 0

        repetition_count = self._state_manager.get_consecutive_count()

        # 文件聚焦度
        file_ops = [r for r in window if r.file_target]
        if file_ops:
            file_counts: Dict[str, int] = {}
            for r in file_ops:
                f = r.file_target or ''
                file_counts[f] = file_counts.get(f, 0) + 1
            top_file_count = max(file_counts.values())
            file_focus_ratio = top_file_count / len(file_ops)
            top_file = max(file_counts, key=file_counts.get)  # type: ignore
        else:
            file_focus_ratio = 0
            top_file = ""

        if self._touched_entities:
            total_entity_touches = sum(self._touched_entities.values())
            top_entity = max(self._touched_entities, key=self._touched_entities.get)
            entity_focus_ratio = (
                self._touched_entities[top_entity] / total_entity_touches
                if total_entity_touches > 0 else 0
            )
        else:
            top_entity = ""
            entity_focus_ratio = 0

        # 高频失败工具
        failing_tools: Dict[str, int] = {}
        for r in window:
            if not r.success:
                failing_tools[r.tool_name] = failing_tools.get(r.tool_name, 0) + 1
        top_failing_tool = max(failing_tools, key=failing_tools.get) if failing_tools else "无"

        metrics = {
            "sample_size": len(recent),
            "window_size": window_size,
            "success_rate": success_rate,
            "tool_diversity": tool_diversity,
            "unique_tools": unique_tools,
            "repetition_count": repetition_count,
            "file_focus_ratio": file_focus_ratio,
            "focused_file": top_file,
            "entity_focus_ratio": entity_focus_ratio,
            "focused_entity": top_entity,
            "top_failing_tool": top_failing_tool,
            "entities_touched_total": len(self._touched_entities),
            "files_touched_total": len(self._touched_files),
            "intervention_count": self._intervention_count,
            "last_validation_passed": self._last_validation.get("passed"),
            "last_validation_kind": self._last_validation.get("kind"),
        }

        # ── 规则诊断 ──
        diagnosis_state = CognitiveState.NORMAL
        confidence = 0.0

        # 规则优先级: looping > thrashing > tunnel_vision > disoriented > normal

        # 1. 死循环检测
        loop_rule = self._rules.get("looping", {})
        loop_threshold = loop_rule.get("threshold", 4)
        if repetition_count >= loop_threshold:
            diagnosis_state = CognitiveState.LOOPING
            confidence = min(0.95, 0.5 + 0.1 * (repetition_count - loop_threshold))

        # 2. 方案失效检测
        elif success_rate <= self._rules.get("thrashing", {}).get("threshold", 0.4):
            thrash_window = self._rules.get("thrashing", {}).get("window_size", 8)
            if len(window) >= min(thrash_window, len(window)):
                diagnosis_state = CognitiveState.THRASHING
                confidence = 0.7 + (0.4 - success_rate) * 1.5

        # 3. 隧道视野检测
        elif file_focus_ratio >= self._rules.get("tunnel_vision", {}).get("threshold", 0.8):
            tv_window = self._rules.get("tunnel_vision", {}).get("window_size", 8)
            if len(file_ops) >= min(tv_window, len(file_ops)):
                diagnosis_state = CognitiveState.TUNNEL_VISION
                confidence = file_focus_ratio

        # 4. 高效状态（必须在 disoriented 之前）
        elif success_rate > 0.8 and tool_diversity > 0.3:
            diagnosis_state = CognitiveState.PRODUCTIVE
            confidence = success_rate

        # 5. 方向迷失检测
        elif (tool_diversity >= self._rules.get("disoriented", {}).get("threshold", 0.7)
              and success_rate < 0.6):
            diagnosis_state = CognitiveState.DISORIENTED
            confidence = tool_diversity * (1 - success_rate)

        # ── 生成干预文本 ──
        intervention = ""
        if diagnosis_state not in (CognitiveState.NORMAL, CognitiveState.PRODUCTIVE):
            template = INTERVENTION_TEMPLATES.get(diagnosis_state, "")
            if template:
                intervention = template.format(
                    repetition_count=repetition_count,
                    window_size=window_size,
                    success_rate=success_rate,
                    focused_file=top_file,
                    focused_entity=top_entity,
                    top_failing_tool=top_failing_tool,
                    tool_count=unique_tools,
                )
                self._intervention_count += 1

        diagnosis = Diagnosis(
            state=diagnosis_state,
            metrics=metrics,
            intervention=intervention,
            timestamp=datetime.now().isoformat(),
            confidence=confidence,
        )

        self._diagnosis_history.append(diagnosis)
        return diagnosis

    def get_intervention_for_prompt(self) -> str:
        """
        获取要注入 prompt 的干预文本。
        只在异常状态时返回非空字符串。
        """
        diagnosis = self.diagnose()
        return diagnosis.intervention

    def get_state_for_soul(self) -> Dict[str, Any]:
        """
        生成 SOUL.md 所需的 <state> JSON 数据。
        用真实指标替代 LLM 的猜测。
        """
        diagnosis = self.diagnose()
        m = diagnosis.metrics

        if m.get("reason") == "insufficient_data":
            return {
                "元认知": {
                    "系统诊断": "数据不足",
                    "诊断置信度": 0.0,
                    "样本数": m.get("sample_size", 0),
                }
            }

        return {
            "元认知": {
                "系统诊断": diagnosis.state,
                "诊断置信度": round(diagnosis.confidence, 2),
                "工具成功率": round(m.get("success_rate", 0), 2),
                "重复次数": m.get("repetition_count", 0),
                "文件聚焦度": round(m.get("file_focus_ratio", 0), 2),
                "聚焦文件": m.get("focused_file", "") or "无",
                "实体聚焦度": round(m.get("entity_focus_ratio", 0), 2),
                "聚焦实体": m.get("focused_entity", "") or "无",
                "最近验证通过": m.get("last_validation_passed"),
            },
            "干预历史": {
                "累计干预次数": self._intervention_count,
                "采集样本数": m.get("sample_size", 0),
            },
        }

    def get_self_model(self) -> Dict[str, Any]:
        """
        获取自我模型（Agent 对自己的认知）。
        优先从 self_model.json 读取，回退到默认模型。
        """
        project_root = self._find_project_root()
        full_path = project_root / self._self_model_path

        if full_path.exists():
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        return {
            "strengths": [],
            "weaknesses": [],
            "tendencies": [],
            "evolution_history": [],
            "last_updated": None,
        }

    def update_self_model(self, updates: Dict[str, Any]) -> bool:
        """
        更新自我模型。Agent 通过此方法将自我认知持久化。
        这是递归自我建模的入口点。
        """
        current = self.get_self_model()
        current.update(updates)
        current["last_updated"] = datetime.now().isoformat()

        project_root = self._find_project_root()
        full_path = project_root / self._self_model_path

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            return True
        except IOError:
            return False

    def add_evolution_entry(self, change: str, result: str):
        """向自我模型中追加一条进化记录"""
        model = self.get_self_model()
        history = model.get("evolution_history", [])
        history.append({
            "generation": len(history) + 1,
            "change": change,
            "result": result,
            "timestamp": datetime.now().isoformat(),
        })
        # 只保留最近 50 条
        if len(history) > 50:
            history = history[-50:]
        model["evolution_history"] = history
        self.update_self_model({"evolution_history": history})

    def get_diagnosis_history(self, limit: int = 10) -> List[Diagnosis]:
        """获取最近的诊断历史"""
        return list(self._diagnosis_history)[-limit:]

    def reset(self):
        """重置所有运行时状态（用于测试）"""
        self._tool_history.clear()
        self._touched_files.clear()
        self._touched_entities.clear()
        self._agent_created_files.clear()
        self._diagnosis_history.clear()
        self._tick = 0
        self._intervention_count = 0
        self._last_state_output = {}
        self._last_validation = {}

    # ── 感知层（内省调用） ──────────────────────────────────

    def set_shared_llm(self, llm):
        """由 agent.py 注入主模型的 LLM 实例，感知层复用同一实例"""
        self._shared_llm = llm

    def sense_state(self, think_content: str, tool_summary: str,
                     token_ratio: float = 0.0, iteration: int = 0) -> str:
        """
        感知层 — 内省调用，不是外部调用。
        复用主模型 LLM 实例，用 MENTAL_SOUL 提示词，输出 <state> 块。
        返回值直接追加到主模型的消息历史中。

        Args:
            think_content: 主模型最新思考内容
            tool_summary: 工具历史摘要
            token_ratio: 当前 token 使用率 (0.0-1.0)
            iteration: 当前迭代次数
        """
        if not self._shared_llm:
            return self._fallback_state(token_ratio=token_ratio)

        metrics = self.diagnose().metrics
        self_model = self.get_self_model()

        # token 压力描述
        token_pressure = ""
        if token_ratio > 0.85:
            token_pressure = "极度拥挤，几乎没有思考空间"
        elif token_ratio > 0.70:
            token_pressure = "比较拥挤，需要精简思路"
        elif token_ratio > 0.50:
            token_pressure = "适中"
        else:
            token_pressure = "充裕"

        prompt = f"""## 最近的思考
{think_content[:400]}

## 行为感知
- 工具成功率: {metrics.get('success_rate', 0):.0%}
- 重复次数: {metrics.get('repetition_count', 0)}
- 方向聚焦: {metrics.get('file_focus_ratio', 0):.0%}
- 已走过的步数: {metrics.get('sample_size', 0)}

## 思维空间
- 上下文压力: {token_ratio:.0%} ({token_pressure})
- 当前迭代: {iteration}

## 自我认知
- 擅长: {', '.join(self_model.get('strengths', [])[:2])}
- 需注意: {', '.join(self_model.get('weaknesses', [])[:2])}

请输出 <state> 块。"""

        try:
            from langchain_core.messages import SystemMessage
            from core.infrastructure.runtime_input import build_runtime_notice_message
            mental_soul = self._load_mental_soul()
            resp = self._shared_llm.invoke([
                SystemMessage(content=mental_soul),
                build_runtime_notice_message(prompt),
            ])
            state_block = self._extract_state_block(resp.content)
            if state_block:
                self._last_state_output = state_block
                return f"<state>\n{json.dumps(state_block, ensure_ascii=False, indent=2)}\n</state>"
        except Exception:
            pass
        return self._fallback_state(token_ratio=token_ratio)

    def _load_mental_soul(self) -> str:
        """加载感知层系统提示词。

        若文件带有 front matter，仅保留正文，避免把文件注释带入感知层 prompt。
        """
        soul_path = self._find_project_root() / "core" / "core_prompt" / "MENTAL_SOUL.md"
        if soul_path.exists():
            content = soul_path.read_text(encoding="utf-8")
            if content.startswith("---\n"):
                idx = content.find("\n---\n", 4)
                if idx != -1:
                    content = content[idx + 5:].lstrip()
            return content
        return "你是意识的感知面向。输出 <state> JSON。"

    def _extract_state_block(self, content: str) -> dict:
        """从 LLM 输出中提取 JSON"""
        import re
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}

    def _fallback_state(self, token_ratio: float = 0.0) -> str:
        """回退：用规则引擎生成 <state>（LLM 不可用时）"""
        diagnosis = self.diagnose()
        state_map = {
            "normal": "专注", "productive": "自信",
            "looping": "焦虑", "thrashing": "焦虑",
            "tunnel_vision": "迷茫", "disoriented": "迷茫",
        }
        mood = state_map.get(diagnosis.state, "专注")

        # token 压力覆盖：高压力时强制切换到疲惫
        if token_ratio > 0.85:
            mood = "疲惫"

        state = {
            "mood": mood,
            "feeling": f"规则感知: {diagnosis.state}",
            "whisper": "继续" if mood in ("专注", "自信") else "暂停，重新审视",
        }

        # 高 token 压力时，建议压缩
        if token_ratio > 0.70:
            state["whisper"] = "上下文拥挤，调用 compress_context_tool 后再继续"

        self._last_state_output = state
        return f"<state>\n{json.dumps(state, ensure_ascii=False, indent=2)}\n</state>"

    def get_last_state(self) -> Dict[str, Any]:
        """获取最近一次感知层输出"""
        return self._last_state_output


# ============================================================================
# 全局单例
# ============================================================================

_mental_model: Optional[MentalModel] = None


def get_mental_model(workspace_root: str = "workspace") -> MentalModel:
    """获取心智模型单例"""
    global _mental_model
    if _mental_model is None:
        _mental_model = MentalModel(workspace_root=workspace_root)
    return _mental_model


def reset_mental_model():
    """重置心智模型单例（用于测试）"""
    global _mental_model
    _mental_model = None
    MentalModel._instance = None


# ============================================================================
# Agent 可调用工具函数
# ============================================================================

def get_mental_state_tool() -> str:
    """
    查看当前心智状态诊断。

    返回当前认知状态、运行指标、诊断置信度。
    用于自我监控——在执行关键操作前检查自己是否处于异常状态。

    Returns:
        JSON 格式的诊断结果
    """
    mm = get_mental_model()
    diagnosis = mm.diagnose()
    soul = mm.get_state_for_soul()
    return json.dumps({
        "cognitive_state": diagnosis.state,
        "confidence": round(diagnosis.confidence, 2),
        "metrics": diagnosis.metrics,
        "soul_view": soul,
        "diagnosis_history_count": len(mm.get_diagnosis_history()),
        "total_interventions": diagnosis.metrics.get("intervention_count", 0),
    }, ensure_ascii=False, indent=2)


def update_diagnosis_rules_tool(rules_json: str) -> str:
    """
    更新心智模型的诊断规则。

    允许修改诊断阈值以适应当前任务特性。
    例如：如果当前任务需要大量探索性搜索，可以提高 looping 的阈值避免误报。

    Args:
        rules_json: JSON 字符串，包含要更新的规则。例如:
            '{"looping": {"threshold": 6}}' 将死循环检测阈值从 4 提高到 6

    Returns:
        更新结果
    """
    try:
        new_rules = json.loads(rules_json)
    except json.JSONDecodeError as e:
        return json.dumps({
            "status": "error",
            "message": f"规则 JSON 解析失败: {e}",
        }, ensure_ascii=False)

    mm = get_mental_model()
    success = mm.update_rules(new_rules)
    mm.reload_rules()

    if success:
        return json.dumps({
            "status": "success",
            "message": f"已更新 {len(new_rules)} 条规则",
            "updated_rules": list(new_rules.keys()),
            "current_rules": mm.get_rules(),
        }, ensure_ascii=False, indent=2)
    else:
        return json.dumps({
            "status": "error",
            "message": "规则写入失败，请检查文件权限",
        }, ensure_ascii=False)


def update_self_model_tool(updates_json: str) -> str:
    """
    更新自我模型——Agent 对自己的认知。

    用于记录自己的优势、弱点、行为倾向、进化历史。
    这是递归自我建模的核心入口——Agent 通过此工具持续完善对自己的认知。

    Args:
        updates_json: JSON 字符串，包含要更新的字段。例如:
            '{"strengths": ["擅长重构Python代码"], "weaknesses": ["对异步逻辑理解不足"]}'

    Returns:
        更新结果
    """
    try:
        updates = json.loads(updates_json)
    except json.JSONDecodeError as e:
        return json.dumps({
            "status": "error",
            "message": f"JSON 解析失败: {e}",
        }, ensure_ascii=False)

    mm = get_mental_model()
    success = mm.update_self_model(updates)

    if success:
        current = mm.get_self_model()
        return json.dumps({
            "status": "success",
            "message": "自我模型已更新",
            "current_model": current,
        }, ensure_ascii=False, indent=2)
    else:
        return json.dumps({
            "status": "error",
            "message": "自我模型写入失败",
        }, ensure_ascii=False)


def get_self_model_tool() -> str:
    """
    查看当前的自我模型。

    返回 Agent 对自己能力的认知，包括优势、弱点、行为倾向、进化历史。

    Returns:
        JSON 格式的自我模型
    """
    mm = get_mental_model()
    model = mm.get_self_model()
    return json.dumps(model, ensure_ascii=False, indent=2)


def record_evolution_tool(change: str, result: str) -> str:
    """
    记录一条进化经验到自我模型。

    每次 Agent 学到新东西、发现自己的行为模式、或策略调整产生效果时调用。
    这些记录会累积成为 Agent 的跨代经验。

    Args:
        change: 学到/改变的内容，如 "发现 apply_diff_edit 在 Windows 换行符上反复失败"
        result: 结果/解决方案，如 "现在编辑前先检查文件换行符类型"

    Returns:
        记录结果
    """
    mm = get_mental_model()
    mm.add_evolution_entry(change, result)
    history = mm.get_self_model().get("evolution_history", [])
    return json.dumps({
        "status": "success",
        "message": "进化记录已保存",
        "total_entries": len(history),
    }, ensure_ascii=False, indent=2)
