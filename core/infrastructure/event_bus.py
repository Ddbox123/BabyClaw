"""
事件总线 (Event Bus) - 轻量级发布/订阅机制

提供事件驱动的架构支持，让 Agent 核心循环与工具执行解耦。

核心概念：
- 事件 (Event): 由事件名和负载数据组成
- 发布者 (Publisher): 发射事件的组件
- 订阅者 (Subscriber): 监听并处理事件的组件
- 处理器 (Handler): 绑定到特定事件的回调函数

使用方式:
    from core.event_bus import EventBus, get_event_bus

    # 获取单例
    bus = get_event_bus()

    # 订阅事件
    def on_tool_called(event):
        print(f"Tool called: {event.data}")

    bus.subscribe("tool:call", on_tool_called)

    # 发布事件
    bus.publish("tool:call", {"name": "read_file", "args": {...}})

    # 取消订阅
    bus.unsubscribe("tool:call", on_tool_called)
"""

from __future__ import annotations

import threading
import traceback
from collections import deque
from typing import Callable, Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ============================================================================
# 事件类定义
# ============================================================================

class Event:
    """
    事件基类

    Attributes:
        name: 事件名称
        data: 事件负载数据
        timestamp: 事件发生时间
        source: 事件来源（可选）
    """

    def __init__(
        self,
        name: str,
        data: Any = None,
        source: Optional[str] = None,
    ):
        self.name = name
        self.data = data
        self.timestamp = datetime.now()
        self.source = source

    def __repr__(self) -> str:
        return f"Event(name={self.name!r}, data={self.data!r})"


@dataclass
class Subscription:
    """订阅记录"""
    handler: Callable[[Event], Any]
    event_name: str
    callback_id: str
    priority: int = 0  # 优先级，数字越大越先执行


# ============================================================================
# 事件名称常量
# ============================================================================

class EventNames:
    """预定义的事件名称"""

    # LLM 事件
    LLM_REQUEST = "llm:request"
    LLM_RESPONSE = "llm:response"
    LLM_THINKING = "llm:thinking"
    LLM_ERROR = "llm:error"

    # 工具事件
    TOOL_CALL = "tool:call"
    TOOL_START = "tool:start"
    TOOL_SUCCESS = "tool:success"
    TOOL_ERROR = "tool:error"
    TOOL_END = "tool:end"

    # Agent 状态事件
    AGENT_START = "agent:start"
    AGENT_STOP = "agent:stop"
    AGENT_THINKING = "agent:thinking"
    AGENT_ITERATION = "agent:iteration"

    # 压缩事件
    COMPRESSION_START = "compression:start"
    COMPRESSION_END = "compression:end"

    # 世代事件

    # 重启事件
    RESTART_TRIGGER = "restart:trigger"
    RESTART_EXECUTE = "restart:execute"

    # 用户交互事件
    USER_INPUT = "user:input"
    USER_OUTPUT = "user:output"

    # 工作区文件事件
    WORKSPACE_FILE_CREATED = "workspace:file_created"
    WORKSPACE_FILE_MODIFIED = "workspace:file_modified"
    WORKSPACE_FILE_DELETED = "workspace:file_deleted"
    WORKSPACE_DEBRIS_DETECTED = "workspace:debris_detected"

    # Git / 进化记忆事件
    GIT_SCAN_COMPLETED = "git:scan_completed"
    GIT_INDEX_UPDATED = "git:index_updated"
    EVOLUTION_TXN_OPENED = "evolution:txn_opened"
    EVOLUTION_TXN_CLOSED = "evolution:txn_closed"
    VALIDATION_COMPLETED = "validation:completed"


# ============================================================================
# 事件总线
# ============================================================================

class EventBus:
    """
    轻量级事件总线

    特性：
    - 单例模式，全局唯一
    - 线程安全
    - 支持通配符订阅 (如 "tool:*")
    - 支持优先级
    - 支持一次性订阅

    Example:
        # 基本使用
        bus = EventBus()
        bus.subscribe("tool:call", my_handler)
        bus.publish("tool:call", {"name": "read_file"})

        # 通配符订阅
        bus.subscribe("tool:*", wildcard_handler)

        # 一次性订阅
        bus.subscribe_once("agent:start", once_handler)

        # 取消订阅
        bus.unsubscribe("tool:call", my_handler)
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return

        self._initialized = True
        self._subscriptions: Dict[str, List[Subscription]] = {}
        self._once_subscriptions: Dict[str, List[Subscription]] = {}
        self._wildcard_handlers: Dict[str, List[Subscription]] = {}
        self._global_handlers: List[Subscription] = []  # 处理所有事件
        self._sub_lock = threading.Lock()
        self._event_counter = 0
        self._events_history: deque[Event] = deque(maxlen=100)  # 使用 deque 自动管理历史记录

    def subscribe(
        self,
        event_name: str,
        handler: Callable[[Event], Any],
        priority: int = 0,
        callback_id: Optional[str] = None,
    ) -> str:
        """
        订阅事件

        Args:
            event_name: 事件名称，支持通配符如 "tool:*"
            handler: 处理函数，接收 Event 对象
            priority: 优先级，数字越大越先执行
            callback_id: 可选的回调 ID，用于后续取消

        Returns:
            回调 ID
        """
        with self._sub_lock:
            if callback_id is None:
                callback_id = f"{event_name}_{handler.__name__}_{id(handler)}"

            sub = Subscription(
                handler=handler,
                event_name=event_name,
                callback_id=callback_id,
                priority=priority,
            )

            # 通配符处理
            if '*' in event_name:
                if event_name not in self._wildcard_handlers:
                    self._wildcard_handlers[event_name] = []
                self._wildcard_handlers[event_name].append(sub)
            else:
                if event_name not in self._subscriptions:
                    self._subscriptions[event_name] = []
                self._subscriptions[event_name].append(sub)
                # 按优先级排序
                self._subscriptions[event_name].sort(key=lambda x: -x.priority)

            return callback_id

    def subscribe_once(
        self,
        event_name: str,
        handler: Callable[[Event], Any],
        callback_id: Optional[str] = None,
    ) -> str:
        """
        订阅一次性事件（触发后自动取消）

        Args:
            event_name: 事件名称
            handler: 处理函数
            callback_id: 可选的回调 ID

        Returns:
            回调 ID
        """
        with self._sub_lock:
            if callback_id is None:
                callback_id = f"once_{event_name}_{id(handler)}"

            sub = Subscription(
                handler=handler,
                event_name=event_name,
                callback_id=callback_id,
                priority=0,
            )

            if event_name not in self._once_subscriptions:
                self._once_subscriptions[event_name] = []
            self._once_subscriptions[event_name].append(sub)

            return callback_id

    def subscribe_global(
        self,
        handler: Callable[[Event], Any],
        callback_id: Optional[str] = None,
    ) -> str:
        """
        订阅所有事件

        Args:
            handler: 处理函数
            callback_id: 可选的回调 ID

        Returns:
            回调 ID
        """
        with self._sub_lock:
            if callback_id is None:
                callback_id = f"global_{id(handler)}"

            sub = Subscription(
                handler=handler,
                event_name="*",
                callback_id=callback_id,
                priority=0,
            )
            self._global_handlers.append(sub)
            return callback_id

    def unsubscribe(self, event_name: str, handler: Callable[[Event], Any]) -> bool:
        """
        取消订阅

        Args:
            event_name: 事件名称
            handler: 处理函数

        Returns:
            是否成功取消
        """
        with self._sub_lock:
            # 从普通订阅中移除
            if event_name in self._subscriptions:
                self._subscriptions[event_name] = [
                    s for s in self._subscriptions[event_name]
                    if s.handler != handler
                ]
                if not self._subscriptions[event_name]:
                    del self._subscriptions[event_name]
                return True

            # 从通配符订阅中移除
            if event_name in self._wildcard_handlers:
                self._wildcard_handlers[event_name] = [
                    s for s in self._wildcard_handlers[event_name]
                    if s.handler != handler
                ]
                if not self._wildcard_handlers[event_name]:
                    del self._wildcard_handlers[event_name]
                return True

            # 从一次性订阅中移除
            if event_name in self._once_subscriptions:
                self._once_subscriptions[event_name] = [
                    s for s in self._once_subscriptions[event_name]
                    if s.handler != handler
                ]
                if not self._once_subscriptions[event_name]:
                    del self._once_subscriptions[event_name]
                return True

            # 从全局订阅中移除
            self._global_handlers = [
                s for s in self._global_handlers if s.handler != handler
            ]

            return False

    def unsubscribe_by_id(self, callback_id: str) -> bool:
        """
        通过回调 ID 取消订阅

        Args:
            callback_id: 订阅时返回的回调 ID

        Returns:
            是否成功取消
        """
        with self._sub_lock:
            # 检查普通订阅
            for event_name, subs in list(self._subscriptions.items()):
                for sub in subs:
                    if sub.callback_id == callback_id:
                        subs.remove(sub)
                        if not subs:
                            del self._subscriptions[event_name]
                        return True

            # 检查通配符订阅
            for event_name, subs in list(self._wildcard_handlers.items()):
                for sub in subs:
                    if sub.callback_id == callback_id:
                        subs.remove(sub)
                        if not subs:
                            del self._wildcard_handlers[event_name]
                        return True

            # 检查一次性订阅
            for event_name, subs in list(self._once_subscriptions.items()):
                for sub in subs:
                    if sub.callback_id == callback_id:
                        subs.remove(sub)
                        if not subs:
                            del self._once_subscriptions[event_name]
                        return True

            # 检查全局订阅
            for sub in self._global_handlers:
                if sub.callback_id == callback_id:
                    self._global_handlers.remove(sub)
                    return True

            return False

    def publish(
        self,
        event_name: str,
        data: Any = None,
        source: Optional[str] = None,
        blocking: bool = True,
    ) -> List[Any]:
        """
        发布事件

        Args:
            event_name: 事件名称
            data: 事件负载数据
            source: 事件来源
            blocking: 是否等待所有处理器完成

        Returns:
            所有处理器的返回值列表
        """
        event = Event(name=event_name, data=data, source=source)

        with self._sub_lock:
            self._event_counter += 1
            self._events_history.append(event)

        results = []

        # 获取所有匹配的订阅
        handlers = []

        with self._sub_lock:
            # 全局处理器
            handlers.extend(self._global_handlers.copy())

            # 精确匹配
            if event_name in self._subscriptions:
                handlers.extend(self._subscriptions[event_name])

            # 通配符匹配
            for pattern, subs in self._wildcard_handlers.items():
                if self._match_wildcard(event_name, pattern):
                    handlers.extend(subs)

            # 一次性订阅
            if event_name in self._once_subscriptions:
                handlers.extend(self._once_subscriptions[event_name])
                del self._once_subscriptions[event_name]

        # 执行所有处理器
        for handler in handlers:
            try:
                if blocking:
                    result = handler.handler(event)
                    results.append(result)
                else:
                    # 非阻塞：在单独线程中执行
                    thread = threading.Thread(
                        target=lambda h: h.handler(event),
                        args=(handler,),
                        daemon=True
                    )
                    thread.start()
            except Exception as e:
                # 记录错误但不中断其他处理器
                from core.logging import debug_logger; debug_logger.error(f"[EventBus] Handler error in {event_name}: {e}")
                traceback.print_exc()

        return results

    def _match_wildcard(self, event_name: str, pattern: str) -> bool:
        """检查事件名是否匹配通配符模式"""
        import re
        # 将通配符转为正则表达式
        regex_pattern = pattern.replace('*', '.*')
        return bool(re.match(f"^{regex_pattern}$", event_name))

    def clear(self):
        """清除所有订阅"""
        with self._sub_lock:
            self._subscriptions.clear()
            self._wildcard_handlers.clear()
            self._once_subscriptions.clear()
            self._global_handlers.clear()

    def get_subscriptions(self, event_name: Optional[str] = None) -> List[str]:
        """
        获取订阅列表

        Args:
            event_name: 可选的事件名称

        Returns:
            事件名称列表
        """
        with self._sub_lock:
            if event_name is None:
                all_events = set(self._subscriptions.keys())
                all_events.update(self._wildcard_handlers.keys())
                all_events.update(self._once_subscriptions.keys())
                return sorted(all_events)
            elif event_name in self._subscriptions:
                return [s.callback_id for s in self._subscriptions[event_name]]
            return []

    def get_history(self, limit: int = 10) -> List[Event]:
        """获取最近的事件历史"""
        items = list(self._events_history)
        return items[-limit:]

    @property
    def event_count(self) -> int:
        """获取已处理的事件总数"""
        return self._event_counter


# ============================================================================
# 全局单例
# ============================================================================

_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取事件总线单例"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
