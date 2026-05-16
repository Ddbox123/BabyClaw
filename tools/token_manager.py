#!/usr/bin/env python3
"""
增强型 Token 压缩与记忆管理模块

在 OpenCLAW 风格基础上进行优化：

核心优化：
1. 预压缩机制 - 在 Token 耗尽前主动压缩
2. 消息优先级 - 区分不同类型消息的重要性
3. 智能截断 - 根据消息类型采用不同策略
4. 动态阈值 - 根据对话阶段调整压缩时机
5. 层级摘要 - 多级压缩，保留关键信息
6. 预算感知 - 实时追踪 Token 消耗

设计原则：
- 预防优于治疗：在接近限制前就压缩
- 保留决策上下文：压缩时保留意图而非细节
- 渐进式压缩：分多次小压缩而非一次性大压缩
"""

import json
import logging
import os
import time
from typing import Optional, List, Dict, Any, Tuple, Callable
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime
from enum import IntEnum

from core.infrastructure.runtime_input import (
    build_runtime_notice_message,
    is_external_request_message,
)


# ============================================================================
# 配置常量 - 从配置文件加载
# ============================================================================


def _load_token_defaults() -> dict:
    """从配置加载默认常量"""
    try:
        from config import get_config
        cfg = get_config()
        return {
            "DEFAULT_TOKEN_BUDGET": cfg.context_compression.max_token_limit,
            "MAX_SYSTEM_PROMPT_TOKENS": 2000,
            "MAX_TOOL_RESULT_TOKENS": 400,
            "MAX_HISTORY_PAIRS": cfg.context_compression.keep_recent_steps,
            "MAX_AI_RESPONSE_CHARS": 300,
            "MAX_TOOL_NAME_CHARS": 40,
            "MAX_EXTERNAL_REQUEST_CHARS": 400,
            "COMPRESSION_TRIGGER_RATIO": cfg.context_compression.levels.light,
            "COMPRESSION_WARNING_RATIO": 0.5,
            "COMPRESSION_CRITICAL_RATIO": cfg.context_compression.levels.standard,
            "COMPRESSION_TARGET_RATIO": 0.45,
            "LIGHT_SUMMARY_CHARS": cfg.context_compression.summary_chars.light,
            "STANDARD_SUMMARY_CHARS": cfg.context_compression.summary_chars.standard,
            "DEEP_SUMMARY_CHARS": cfg.context_compression.summary_chars.deep,
        }
    except Exception:
        return {}


_token_defaults = _load_token_defaults()

# Token 预算配置
DEFAULT_TOKEN_BUDGET = _token_defaults.get("DEFAULT_TOKEN_BUDGET", 8000)
MAX_SYSTEM_PROMPT_TOKENS = _token_defaults.get("MAX_SYSTEM_PROMPT_TOKENS", 2000)
MAX_TOOL_RESULT_TOKENS = _token_defaults.get("MAX_TOOL_RESULT_TOKENS", 400)
MAX_HISTORY_PAIRS = _token_defaults.get("MAX_HISTORY_PAIRS", 3)

# 压缩阈值（优化 - 更激进的阈值以避免超限）
# 基于模型 32768 context window，配置 max_token_limit = 16000
COMPRESSION_TRIGGER_RATIO = _token_defaults.get("COMPRESSION_TRIGGER_RATIO", 0.60)
COMPRESSION_WARNING_RATIO = _token_defaults.get("COMPRESSION_WARNING_RATIO", 0.50)
COMPRESSION_CRITICAL_RATIO = _token_defaults.get("COMPRESSION_CRITICAL_RATIO", 0.80)
COMPRESSION_TARGET_RATIO = _token_defaults.get("COMPRESSION_TARGET_RATIO", 0.45)

# 摘要配置
MINIMAL_SUMMARY_CHARS = 80
CORE_SUMMARY_CHARS = 200
DETAILED_SUMMARY_CHARS = 500
LIGHT_SUMMARY_CHARS = _token_defaults.get("LIGHT_SUMMARY_CHARS", 500)
STANDARD_SUMMARY_CHARS = _token_defaults.get("STANDARD_SUMMARY_CHARS", 1000)
DEEP_SUMMARY_CHARS = _token_defaults.get("DEEP_SUMMARY_CHARS", 2000)

# 截断配置
MAX_AI_RESPONSE_CHARS = _token_defaults.get("MAX_AI_RESPONSE_CHARS", 300)
MAX_TOOL_NAME_CHARS = _token_defaults.get("MAX_TOOL_NAME_CHARS", 40)
MAX_EXTERNAL_REQUEST_CHARS = _token_defaults.get("MAX_EXTERNAL_REQUEST_CHARS", 400)

# 预压缩 Buffer（百分比）
PRECOMPRESSION_BUFFER = 0.10


# ============================================================================
# 消息优先级枚举
# ============================================================================

class MessagePriority(IntEnum):
    """消息优先级（数值越低越重要）"""
    CRITICAL = 1      # 系统提示词、记忆
    HIGH = 2          # 最近的工具结果
    MEDIUM = 3        # AI 思考过程
    LOW = 4           # 早期历史（可压缩）
    TRIVIAL = 5       # 重复的搜索结果等


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class TokenBudget:
    """Token 预算追踪器（增强版）"""
    total_budget: int = 8000
    system_prompt_tokens: int = 0
    reserved_tokens: int = 0  # 预留空间
    
    @property
    def effective_budget(self) -> int:
        """有效预算（减去预留）"""
        return self.total_budget - self.reserved_tokens
    
    @property
    def available_tokens(self) -> int:
        """可用 Token"""
        return self.effective_budget - self.system_prompt_tokens

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self.total_budget == other
        return super().__eq__(other)

    def __gt__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self.total_budget > other
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self.total_budget < other
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self.total_budget >= other
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self.total_budget <= other
        return NotImplemented


@dataclass
class CompressionRecord:
    """压缩记录"""
    timestamp: float
    before_tokens: int
    after_tokens: int
    compression_ratio: float
    pairs_compressed: int
    summary_preview: str
    compression_type: str = "incremental"  # incremental, forced, emergency

    def __post_init__(self) -> None:
        self.compression_ratio = (
            (self.before_tokens - self.after_tokens) / max(self.before_tokens, 1)
        )


@dataclass
class CompressionResult:
    """单次压缩结果；兼容旧调用方把它当摘要字符串使用。"""
    summary: str
    tokens_before: int
    tokens_after: int
    pairs_compressed: int = 0
    compression_type: str = "none"

    @property
    def tokens_saved(self) -> int:
        return self.tokens_before - self.tokens_after

    @property
    def compression_ratio(self) -> float:
        return self.tokens_saved / max(self.tokens_before, 1)

    def __str__(self) -> str:
        return self.summary

    def __bool__(self) -> bool:
        return bool(self.summary)

    def __contains__(self, item: object) -> bool:
        return item in self.summary

    def __len__(self) -> int:
        return len(self.summary)


@dataclass
class CompressionOutput:
    """压缩返回值；支持 `(messages, stats)` 解包，也支持直接读取统计字段。"""
    messages: List[Any]
    result: CompressionResult

    def __iter__(self):
        yield self.messages
        yield self.result

    def __getitem__(self, index: int):
        return (self.messages, self.result)[index]

    def __len__(self) -> int:
        return 2

    @property
    def tokens_before(self) -> int:
        return self.result.tokens_before

    @property
    def tokens_after(self) -> int:
        return self.result.tokens_after

    @property
    def tokens_saved(self) -> int:
        return self.result.tokens_saved

    @property
    def compression_ratio(self) -> float:
        return self.result.compression_ratio

    @property
    def summary(self) -> str:
        return self.result.summary


@dataclass
class MessageMeta:
    """消息元数据"""
    priority: MessagePriority = MessagePriority.MEDIUM
    is_essential: bool = False      # 是否必须保留
    can_truncate: bool = True       # 是否可截断
    token_cost: int = 0             # Token 消耗估算
    content_preview: str = ""       # 内容预览


class TokenCompressionStats:
    """Token 压缩统计（增强版）"""
    def __init__(self):
        self.compressions: List[CompressionRecord] = []
        self.total_tokens_saved = 0
        self.compression_count = 0
        self.last_compression_time = None
        self.emergency_compressions = 0
        self.preemptive_compressions = 0
        
        # Token 使用趋势
        self.token_history: deque = deque(maxlen=50)
        self.peak_tokens = 0
    
    def record(self, before: int, after: int, pairs: int, summary: str, 
               compression_type: str = "incremental") -> None:
        """记录一次压缩"""
        ratio = (before - after) / max(before, 1)
        record = CompressionRecord(
            timestamp=time.time(),
            before_tokens=before,
            after_tokens=after,
            compression_ratio=ratio,
            pairs_compressed=pairs,
            summary_preview=summary[:80] if summary else "",
            compression_type=compression_type,
        )
        self.compressions.append(record)
        self.total_tokens_saved += (before - after)
        self.compression_count += 1
        self.last_compression_time = time.time()
        
        # 统计特殊压缩类型
        if compression_type == "emergency":
            self.emergency_compressions += 1
        elif compression_type == "preemptive":
            self.preemptive_compressions += 1
        
        # 更新峰值
        if before > self.peak_tokens:
            self.peak_tokens = before
    
    def record_usage(self, tokens: int) -> None:
        """记录 Token 使用"""
        self.token_history.append({
            'timestamp': time.time(),
            'tokens': tokens
        })
    
    def get_stats(self) -> Dict[str, Any]:
        """获取详细统计"""
        if not self.compressions:
            return {"status": "no_compressions"}
        
        recent = self.compressions[-5:]
        return {
            "total_compressions": self.compression_count,
            "total_tokens_saved": self.total_tokens_saved,
            "avg_ratio": sum(c.compression_ratio for c in self.compressions) / len(self.compressions),
            "last_compression": datetime.fromtimestamp(self.compressions[-1].timestamp).isoformat(),
            "emergency_count": self.emergency_compressions,
            "preemptive_count": self.preemptive_compressions,
            "peak_tokens": self.peak_tokens,
            "recent_savings": [c.before_tokens - c.after_tokens for c in recent],
            "compression_types": {
                t: sum(1 for c in self.compressions if c.compression_type == t)
                for t in set(c.compression_type for c in self.compressions)
            }
        }


# ============================================================================
# 核心工具函数
# ============================================================================

def estimate_tokens_precise(text: str) -> int:
    """
    精确的 Token 估算（考虑中英文差异）。
    
    改进：增加安全系数 1.2，避免低估导致超限。
    """
    if not text:
        return 0
    if not isinstance(text, str):
        return 0
    
    # 中文字符
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    # CJK 扩展
    cjk_ext = sum(1 for c in text if '\u3400' <= c <= '\u4dbf')
    # 英文和数字
    ascii_text = sum(1 for c in text if c.isascii() and not c.isspace())
    # 空白字符
    whitespace = sum(1 for c in text if c in ' \t\n\r')
    # 其他
    other = len(text) - chinese - cjk_ext - ascii_text - whitespace
    
    # 估算（中文约1.5字符=1 token，英文约4字符=1 token）
    # 增加 1.2x 安全系数，避免低估
    base_tokens = chinese / 1.5 + cjk_ext / 1.5 + ascii_text / 4 + whitespace / 6 + other / 2
    
    return int(base_tokens * 1.2) + 50  # 额外加50作为消息结构开销


def estimate_messages_tokens(messages: list) -> int:
    """估算消息列表的总 Token"""
    total = 0
    for msg in messages:
        if not hasattr(msg, 'content'):
            continue
        content = msg.content
        # 兼容 LangChain 消息格式：content 可能是 str、list 或其他类型
        if isinstance(content, str):
            total += estimate_tokens_precise(content)
        elif isinstance(content, list):
            # LangChain content blocks 格式（如 [{"type": "text", "text": "..."}]）
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    total += estimate_tokens_precise(block["text"])
                elif isinstance(block, str):
                    total += estimate_tokens_precise(block)
        else:
            # 其他类型（尝试转为字符串估算）
            total += estimate_tokens_precise(str(content)[:10000])
    return total


def get_message_priority(msg: Any) -> MessagePriority:
    """
    根据消息内容推断优先级。
    """
    content = getattr(msg, 'content', '')
    msg_type = getattr(msg, 'type', '')
    
    # 外部任务输入（协议头标记）
    if is_external_request_message(msg):
        return MessagePriority.MEDIUM

    # 系统消息最高优先级
    if msg_type == 'system':
        return MessagePriority.CRITICAL
    
    # 包含关键信息的工具结果
    if msg_type == 'tool':
        if any(kw in content for kw in ['错误', 'Error', '成功', 'OK', 'Syntax']):
            return MessagePriority.HIGH
        if any(kw in content for kw in ['edit_local_file', 'check_syntax', 'restart']):
            return MessagePriority.HIGH
        return MessagePriority.MEDIUM
    
    # AI 思考过程
    if msg_type == 'ai':
        # 有工具调用的通常更重要
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            return MessagePriority.MEDIUM
        return MessagePriority.MEDIUM
    
    return MessagePriority.MEDIUM


# ============================================================================
# 增强型截断函数
# ============================================================================

def truncate_tool_result(result: str, max_chars: int = None) -> str:
    """
    智能截断工具结果。
    
    采用保守策略，优先保留开头和结尾。
    """
    if result is None:
        return ""
    if not isinstance(result, str):
        result = str(result)
    if max_chars is None:
        max_chars = MAX_TOOL_RESULT_TOKENS
    if max_chars <= 0:
        return ""
    
    if len(result) <= max_chars:
        return result
    
    # 智能截断：保留开头、重要结尾
    marker = "\n[...已截断...]\n"
    if max_chars <= len(marker) + 2:
        return result[:max_chars]

    available = max_chars - len(marker)
    end_chars = int(available * 0.4)
    start_chars = available - end_chars
    
    return (result[:start_chars] + marker + result[-end_chars:])[:max_chars]


def truncate_ai_response(response: str, max_chars: int = None) -> str:
    """截断 AI 响应"""
    if response is None:
        return ""
    if not isinstance(response, str):
        response = str(response)
    if max_chars is None:
        max_chars = MAX_AI_RESPONSE_CHARS
    if max_chars <= 0:
        return ""
    
    if len(response) <= max_chars:
        return response
    
    # AI 响应通常开头是结论，保留开头
    marker = "\n[...已截断]"
    if max_chars <= len(marker):
        return response[:max_chars]
    return response[:max_chars - len(marker)] + marker


def smart_compress_message(msg: Any, max_chars: int = CORE_SUMMARY_CHARS) -> str:
    """
    根据消息类型智能压缩。
    """
    content = getattr(msg, 'content', str(msg))
    if content is None:
        return ""
    if not isinstance(content, str):
        content = str(content)
    msg_type = getattr(msg, 'type', '')
    
    if len(content) <= max_chars:
        return content
    
    # 不同类型采用不同策略
    if msg_type == 'tool':
        # 工具结果：保留开头和结尾
        return truncate_tool_result(content, max_chars)
    elif msg_type == 'ai':
        # AI 思考：保留开头（通常是结论）
        return truncate_ai_response(content, max_chars)
    else:
        # 其他：直接截断
        return content[:max_chars] + "\n[...已截断]"


# ============================================================================
# 增强型增量压缩器
# ============================================================================

class EnhancedTokenCompressor:
    """
    增强型 Token 压缩器。
    
    优化点：
    1. 预压缩机制 - 在达到警告阈值时就压缩
    2. 多级压缩 - 根据紧急程度选择压缩强度
    3. 智能摘要 - 用 LLM 生成高质量摘要
    4. 消息优先级 - 优先保留重要消息
    """
    
    def __init__(
        self,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        max_history_pairs: int = MAX_HISTORY_PAIRS,
        compression_llm: Any = None,
        enable_preemptive: bool = True,
        summary_prompt_path: str = None,
        preemptive_threshold: float = None,
        forced_threshold: float = None,
    ):
        self.token_budget = TokenBudget(
            total_budget=token_budget,
            reserved_tokens=int(token_budget * PRECOMPRESSION_BUFFER)
        )
        self.max_history_pairs = max_history_pairs
        self.compression_llm = compression_llm
        self.enable_preemptive = enable_preemptive
        self.preemptive_threshold = preemptive_threshold
        self.forced_threshold = forced_threshold
        self.stats = TokenCompressionStats()
        
        # 压缩历史
        self.compression_history: deque = deque(maxlen=20)
        
        # 当前压缩状态
        self._compression_level = 0  # 0=正常, 1=警告, 2=紧急
        
        # 摘要提示词
        self.summary_prompt_path = summary_prompt_path
        self._summary_prompt_cache = None
    
    @property
    def warning_threshold(self) -> int:
        """警告阈值"""
        ratio = self.preemptive_threshold if self.preemptive_threshold is not None else COMPRESSION_WARNING_RATIO
        return int(self.token_budget.effective_budget * ratio)
    
    @property
    def trigger_threshold(self) -> int:
        """触发阈值"""
        ratio = self.forced_threshold if self.forced_threshold is not None else COMPRESSION_TRIGGER_RATIO
        return int(self.token_budget.effective_budget * ratio)
    
    @property
    def critical_threshold(self) -> int:
        """紧急阈值"""
        return int(self.token_budget.effective_budget * COMPRESSION_CRITICAL_RATIO)
    
    @property
    def target_tokens(self) -> int:
        """目标 Token 数"""
        return int(self.token_budget.effective_budget * COMPRESSION_TARGET_RATIO)
    
    def get_compression_level(self, current_tokens: int) -> str:
        """获取当前压缩级别"""
        if current_tokens > self.critical_threshold:
            return "emergency"
        elif current_tokens > self.trigger_threshold:
            return "active"
        elif current_tokens > self.warning_threshold:
            return "warning"
        return "normal"
    
    def should_compress(self, messages: List[Any]) -> Tuple[bool, str, str]:
        """
        判断是否需要压缩。
        
        Returns:
            (是否需要压缩, 原因, 压缩类型)
        """
        current_tokens = estimate_messages_tokens(messages)
        self.stats.record_usage(current_tokens)
        
        level = self.get_compression_level(current_tokens)
        
        if level == "emergency":
            ratio = current_tokens / self.token_budget.effective_budget
            return True, f"紧急: {current_tokens}/{self.token_budget.effective_budget} ({ratio:.0%})", "emergency"
        
        if level == "active":
            ratio = current_tokens / self.token_budget.effective_budget
            return True, f"触发: {current_tokens}/{self.token_budget.effective_budget} ({ratio:.0%})", "active"
        
        if level == "warning" and self.enable_preemptive:
            ratio = current_tokens / self.token_budget.effective_budget
            return True, f"预压缩: {current_tokens}/{self.token_budget.effective_budget} ({ratio:.0%})", "preemptive"
        
        return False, "", "none"
    
    def compress(
        self,
        messages: List[Any],
        max_chars: int = CORE_SUMMARY_CHARS,
        reason: str = "",
        keep_count: int = 3,
        preserve_errors: bool = True,
        use_llm_summary: bool = True,
    ) -> CompressionOutput:
        """
        执行压缩：保留最近 N 条原始AI回复 + 压缩旧消息为摘要。

        策略：
        - 最近 N 条 AI 消息及其上下文保持原始不变
        - N 条之前的消息压缩成一条摘要
        - 包含错误信息的消息始终保留（不受 keep_count 限制）

        Args:
            messages: 消息列表
            max_chars: 摘要最大字符数
            reason: 压缩原因
            keep_count: 保留的最近 AI 消息数量
            preserve_errors: 是否强制保留错误消息
            use_llm_summary: 是否使用 LLM 生成摘要（False 时用规则提取）

        Returns:
            (压缩后的消息, 压缩统计/摘要对象)
        """
        from langchain_core.messages import SystemMessage, AIMessage
        
        current_tokens = estimate_messages_tokens(messages)
        compression_type = self.get_compression_level(current_tokens)
        
        # 分离消息类型
        system_msgs = [
            m for m in messages
            if isinstance(m, SystemMessage) and not is_external_request_message(m)
        ]
        external_request_msgs = [
            m for m in messages
            if is_external_request_message(m)
        ]
        
        # 提取所有非系统、非外部输入的普通消息
        other_msgs = [
            m for m in messages
            if not isinstance(m, SystemMessage) and not is_external_request_message(m)
        ]
        
        # 找出所有 AI 消息（带 tool_calls 或纯文本回复）
        ai_indices = []
        for i, msg in enumerate(other_msgs):
            if isinstance(msg, AIMessage) or (hasattr(msg, 'type') and msg.type == 'ai'):
                ai_indices.append(i)
        
        if not ai_indices:
            return CompressionOutput(
                messages,
                CompressionResult("", current_tokens, current_tokens, 0, "none"),
            )
        
        if len(ai_indices) <= keep_count:
            kept_msgs = list(other_msgs)
            old_msgs = []
        else:
            cutoff_idx = ai_indices[-keep_count]
            kept_msgs = list(other_msgs[cutoff_idx:])
            old_msgs = list(other_msgs[:cutoff_idx])

        # 错误消息强制保留
        if preserve_errors:
            ERROR_KEYWORDS = ['error', 'exception', 'traceback', 'failed',
                            '错误', '异常', '失败', '超时', '权限']
            still_old = []
            for msg in old_msgs:
                content = getattr(msg, 'content', '')
                if isinstance(content, str) and any(kw in content.lower() for kw in ERROR_KEYWORDS):
                    kept_msgs.insert(0, msg)
                else:
                    still_old.append(msg)
            old_msgs = still_old

        summary = ""
        if old_msgs:
            summary = self._generate_summary(old_msgs, max_chars, use_llm=use_llm_summary)
        if not old_msgs and not summary:
            return CompressionOutput(
                messages,
                CompressionResult("", current_tokens, current_tokens, 0, compression_type),
            )
        # 重建消息结构
        compressed = []
        
        # 1. SystemMessage（只保留一个）
        if system_msgs:
            compressed.append(system_msgs[0])
        
        # 2. 最新的外部任务输入
        if external_request_msgs:
            compressed.append(external_request_msgs[-1])
        
        # 3. 历史摘要（如果有）
        if summary:
            compressed.append(build_runtime_notice_message(f"历史摘要:\n{summary}"))
        
        # 4. 保留的最近 3 条 AI 及上下文（原始不变）
        compressed.extend(kept_msgs)
        
        # 记录压缩统计
        old_tokens = current_tokens
        new_tokens = estimate_messages_tokens(compressed)
        self.stats.record(
            old_tokens, new_tokens, 
            len(old_msgs), summary,
            compression_type
        )
        
        return CompressionOutput(
            compressed,
            CompressionResult(
                summary=summary,
                tokens_before=old_tokens,
                tokens_after=new_tokens,
                pairs_compressed=len(old_msgs),
                compression_type=compression_type,
            ),
        )
    
    def _pair_messages(self, messages: List[Any]) -> List[List[Any]]:
        """将消息配对"""
        pairs = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                pair = [msg]
                j = i + 1
                while j < len(messages):
                    next_msg = messages[j]
                    if hasattr(next_msg, 'tool_calls') and next_msg.tool_calls:
                        break
                    pair.append(next_msg)
                    j += 1
                pairs.append(pair)
                i = j
            else:
                pairs.append([msg])
                i += 1
        return pairs
    
    def _get_summary_prompt(self) -> str:
        """获取摘要提示词（带缓存）"""
        if self._summary_prompt_cache is not None:
            return self._summary_prompt_cache
        
        if self.summary_prompt_path and os.path.exists(self.summary_prompt_path):
            with open(self.summary_prompt_path, 'r', encoding='utf-8') as f:
                self._summary_prompt_cache = f.read()
        else:
            self._summary_prompt_cache = self._get_default_summary_prompt()
        
        return self._summary_prompt_cache
    
    def _get_default_summary_prompt(self) -> str:
        """获取默认摘要提示词"""
        return """你是一个专门用于压缩对话历史的 AI 助手。

生成一个结构化摘要，包含：
1. 核心任务目标
2. 关键决策
3. 工具使用
4. 重要结果
5. 保留上下文

格式要求：
- 使用简洁的短句
- 用 `|` 分隔不同部分
- 总长度不超过 {max_chars} 字符
- 使用中文输出"""
    
    def _generate_summary(
        self,
        messages: List[Any],
        max_chars: int,
        reason: str = "",
        use_llm: bool = True,
    ) -> str:
        """生成摘要。use_llm=False 时跳过 LLM，直接用规则提取。"""
        if not messages:
            return ""

        if self.compression_llm and use_llm:
            try:
                return self._generate_llm_summary(messages, max_chars, reason)
            except Exception as e:
                logging.warning(f"LLM 摘要生成失败，回退到规则摘要: {e}")
                return self._rule_based_summary(messages, max_chars)

        # 回退到基于规则的摘要
        return self._rule_based_summary(messages, max_chars)

    def _rule_based_summary(self, messages: List[Any], max_chars: int) -> str:
        """基于规则的简单摘要生成（增强版：集成关键信息提取）"""
        if not messages:
            return ""

        # 尝试导入并使用关键信息提取器
        try:
            from tools.key_info_extractor import get_key_info_extractor
            extractor = get_key_info_extractor()
            key_info_summary = extractor.extract_key_info_summary(messages)
            if key_info_summary:
                # 关键信息摘要
                summary = key_info_summary
                if len(summary) <= max_chars:
                    return summary
        except ImportError:
            pass

        # 回退到原有的摘要生成逻辑
        summary_parts = []
        remaining = max_chars - 50  # 留空间给前缀和省略号

        # 收集工具调用
        tool_calls = []
        for msg in messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    name = tc.get('name', 'unknown')
                    tool_calls.append(name)

        if tool_calls:
            unique_tools = list(dict.fromkeys(tool_calls))[:10]  # 去重，最多10个
            summary_parts.append(f"使用的工具: {', '.join(unique_tools)}")

        # 收集外部任务输入
        external_request_msgs = []
        for msg in messages:
            content_text = str(getattr(msg, 'content', '') or '')
            if is_external_request_message(msg):
                content = content_text[:100]
                if content:
                    external_request_msgs.append(content)

        if external_request_msgs:
            summary_parts.append(f"外部任务: {external_request_msgs[-1][:80]}")

        # 收集 AI 消息
        ai_contents = []
        for msg in messages:
            if hasattr(msg, 'type') and msg.type == 'ai':
                content = getattr(msg, 'content', '')
                if content and not hasattr(msg, 'tool_calls'):
                    ai_contents.append(content[:80])

        if ai_contents:
            summary_parts.append(f"AI响应数: {len(ai_contents)}")

        # 组合摘要
        summary = " | ".join(summary_parts)
        if len(summary) > max_chars:
            summary = summary[:max_chars - 3] + "..."

        return summary
    
    def _generate_llm_summary(
        self,
        messages: List[Any],
        max_chars: int,
        reason: str = "",
    ) -> str:
        """使用 LLM 生成摘要"""
        from langchain_core.messages import SystemMessage
        from langchain_core.prompts import ChatPromptTemplate
        
        # 构建消息历史文本
        history_text = self._format_messages_for_summary(messages)
        
        # 获取提示词模板
        prompt_template = self._get_summary_prompt()
        
        # 构造提示词
        prompt = prompt_template.format(max_chars=max_chars)
        full_prompt = f"{prompt}\n\n## 对话历史\n\n{history_text}"
        
        if reason:
            full_prompt += f"\n\n## 压缩原因\n{reason}"
        
        # 调用 LLM
        response = self.compression_llm.invoke([
            SystemMessage(content=full_prompt)
        ])
        
        summary = response.content if hasattr(response, 'content') else str(response)
        
        # 截断到最大长度
        if len(summary) > max_chars:
            summary = summary[:max_chars - 3] + "..."
        
        return summary
    
    def _format_messages_for_summary(self, messages: List[Any]) -> str:
        """将消息列表格式化为摘要输入文本"""
        lines = []
        for i, msg in enumerate(messages):
            msg_type = getattr(msg, 'type', 'unknown')
            content = getattr(msg, 'content', str(msg))
            
            if is_external_request_message(msg):
                lines.append(f"[外部输入] {content[:300]}...")
            elif msg_type == 'system':
                lines.append(f"[系统] {content[:200]}...")
            elif msg_type == 'ai':
                tool_calls = getattr(msg, 'tool_calls', None)
                if tool_calls:
                    for tc in tool_calls:
                        name = tc.get('name', 'unknown')
                        args = tc.get('args', {})
                        lines.append(f"[AI 工具调用] {name}({args})")
                else:
                    lines.append(f"[AI] {content[:300]}...")
            elif msg_type == 'tool':
                lines.append(f"[工具结果] {content[:200]}...")
            else:
                lines.append(f"[{msg_type}] {content[:150]}...")
        
        return "\n".join(lines)
    
    def get_status_report(self, messages: List[Any] = None) -> Dict[str, Any]:
        """获取状态报告"""
        current = estimate_messages_tokens(messages) if messages else 0
        return {
            "budget": self.token_budget.total_budget,
            "current_tokens": current,
            "usage_ratio": current / self.token_budget.effective_budget if current else 0,
            "compression_level": self.get_compression_level(current),
            "thresholds": {
                "warning": self.warning_threshold,
                "trigger": self.trigger_threshold,
                "critical": self.critical_threshold,
            },
            "stats": self.stats.get_stats(),
        }


# ============================================================================
# 便捷函数
# ============================================================================

def create_compressor(
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    max_history_pairs: int = MAX_HISTORY_PAIRS,
    compression_llm: Any = None,
    enable_preemptive: bool = True,
) -> EnhancedTokenCompressor:
    """创建压缩器"""
    return EnhancedTokenCompressor(
        token_budget=token_budget,
        max_history_pairs=max_history_pairs,
        compression_llm=compression_llm,
        enable_preemptive=enable_preemptive,
    )


def truncate_by_priority(
    content: Any,
    priority: MessagePriority = None,
    max_chars: int = None,
) -> str:
    """根据优先级截断内容"""
    if isinstance(content, list) and priority is None:
        if not content:
            return ""
        budget = max_chars if max_chars is not None else 1000
        ordered = sorted(content, key=lambda item: item[0])
        parts: List[str] = []
        used = 0
        for item_priority, item_content in ordered:
            text = "" if item_content is None else str(item_content)
            separator = "\n" if parts else ""
            remaining = budget - used - len(separator)
            if remaining <= 0:
                break
            if len(text) > remaining:
                if item_priority <= MessagePriority.HIGH and remaining > 0:
                    parts.append(separator + text[:remaining])
                    used = budget
                continue
            parts.append(separator + text)
            used += len(separator) + len(text)
        return "".join(parts)[:budget]

    if content is None:
        return ""
    content = str(content)
    if priority is None:
        priority = MessagePriority.MEDIUM
    if max_chars is None:
        max_chars = {
            MessagePriority.CRITICAL: 99999,  # 几乎不截断
            MessagePriority.HIGH: 800,
            MessagePriority.MEDIUM: 400,
            MessagePriority.LOW: 200,
            MessagePriority.TRIVIAL: 100,
        }.get(priority, 300)
    if max_chars <= 0:
        return ""
    
    if len(content) <= max_chars:
        return content
    
    marker = "\n[...已截断]"
    if max_chars <= len(marker):
        return content[:max_chars]
    return content[:max_chars - len(marker)] + marker


def format_compression_report(compressor: Any) -> str:
    """格式化压缩报告"""
    if isinstance(compressor, TokenCompressionStats):
        stats_obj = compressor
        stats = stats_obj.get_stats()
        total_budget = DEFAULT_TOKEN_BUDGET
        effective_budget = DEFAULT_TOKEN_BUDGET
        warning_threshold = trigger_threshold = critical_threshold = 0
    else:
        stats_obj = compressor.stats
        stats = stats_obj.get_stats()
        total_budget = compressor.token_budget.total_budget
        effective_budget = compressor.token_budget.effective_budget
        warning_threshold = compressor.warning_threshold
        trigger_threshold = compressor.trigger_threshold
        critical_threshold = compressor.critical_threshold
    
    lines = [
        "=" * 50,
        "[Token压缩] 状态报告",
        "=" * 50,
        f"总预算: {total_budget}",
        f"有效预算: {effective_budget}",
        f"阈值: 警告={warning_threshold} 触发={trigger_threshold} 紧急={critical_threshold}",
        "",
        f"压缩次数: {stats.get('total_compressions', 0)}",
        f"节省Token: {stats.get('total_tokens_saved', 0)}",
        f"紧急压缩: {stats.get('emergency_count', 0)}",
        f"预压缩: {stats.get('preemptive_count', 0)}",
        f"峰值: {stats.get('peak_tokens', 0)}",
        "=" * 50,
    ]
    records = getattr(stats_obj, "compressions", [])
    if records:
        latest = records[-1]
        lines.insert(-1, f"最近: {latest.before_tokens} -> {latest.after_tokens}")
        compression_types = ", ".join(dict.fromkeys(record.compression_type for record in records))
        lines.insert(-1, f"类型: {compression_types}")

    return "\n".join(lines)


# ============================================================================
# 主动压缩工具 — 模型感知到疲惫时可主动调用
# ============================================================================

# 模块级标志：工具设置，agent 主循环检查并执行
_compression_requested: bool = False
_compression_reason: str = ""


def request_compression(reason: str = "主动压缩") -> str:
    """请求上下文压缩（由 compress_context_tool 调用）"""
    global _compression_requested, _compression_reason
    _compression_requested = True
    _compression_reason = reason
    return f"已请求上下文压缩: {reason}。压缩将在下一次迭代时执行。"


def is_compression_requested() -> bool:
    """检查是否有待执行的压缩请求（由 agent 主循环调用）"""
    return _compression_requested


def consume_compression_request() -> str:
    """消费压缩请求并返回原因（由 agent 主循环调用）"""
    global _compression_requested, _compression_reason
    reason = _compression_reason
    _compression_requested = False
    _compression_reason = ""
    return reason


def compress_context_tool(reason: str = "主动压缩") -> str:
    """
    主动压缩上下文，释放思维空间。

    当你感到思绪拥挤、上下文混乱、或需要更多空间思考时调用。
    压缩会保留最近的关键对话，将旧内容压缩为摘要。

    Args:
        reason: 压缩原因（如"上下文太长"、"需要更多空间"）

    Returns:
        确认信息
    """
    return request_compression(reason)
