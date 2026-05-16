"""运行时输入协议 - 去人格化的消息构建。

本模块定义了运行时输入消息的类型和构建函数，用于将外部输入
表示为环境/任务事件，而非人类说话者。

Architecture:
    - RuntimeInputKind: 输入类型枚举
    - RuntimeInput: 不可变数据结构
    - build_external_request_message: 外部请求消息
    - build_runtime_notice_message: 运行时通知消息
    - build_delegation_evidence_message: 委派证据消息
    - build_delegation_failure_message: 委派失败消息
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from langchain_core.messages import SystemMessage


class RuntimeInputKind(str, Enum):
    """运行时输入类型枚举。"""
    EXTERNAL_REQUEST = "external_request"
    RUNTIME_NOTICE = "runtime_notice"
    DELEGATION_EVIDENCE = "delegation_evidence"
    DELEGATION_FAILURE = "delegation_failure"


@dataclass(frozen=True)
class RuntimeInput:
    """不可变的运行时输入数据结构。"""
    kind: RuntimeInputKind
    content: str


_TITLES = {
    RuntimeInputKind.EXTERNAL_REQUEST: "外部任务输入",
    RuntimeInputKind.RUNTIME_NOTICE: "运行时提示",
    RuntimeInputKind.DELEGATION_EVIDENCE: "委派证据",
    RuntimeInputKind.DELEGATION_FAILURE: "委派失败",
}

EXTERNAL_REQUEST_HEADER = f"## {_TITLES[RuntimeInputKind.EXTERNAL_REQUEST]}"


def build_runtime_input_message(item: RuntimeInput) -> SystemMessage:
    """根据运行时输入类型构建 SystemMessage。"""
    title = _TITLES[item.kind]
    return SystemMessage(content=f"## {title}\n{item.content.strip()}")


def build_external_request_message(content: str) -> SystemMessage:
    """构建外部请求消息。"""
    return SystemMessage(content=f"{EXTERNAL_REQUEST_HEADER}\n{content.strip()}")


def build_runtime_notice_message(content: str) -> SystemMessage:
    """构建运行时通知消息。"""
    return build_runtime_input_message(RuntimeInput(RuntimeInputKind.RUNTIME_NOTICE, content))


def build_delegation_evidence_message(content: str) -> SystemMessage:
    """构建委派证据消息。"""
    return build_runtime_input_message(RuntimeInput(RuntimeInputKind.DELEGATION_EVIDENCE, content))


def build_delegation_failure_message(content: str) -> SystemMessage:
    """构建委派失败消息。"""
    return build_runtime_input_message(RuntimeInput(RuntimeInputKind.DELEGATION_FAILURE, content))


def is_external_request_message(message: object) -> bool:
    """判断一条消息是否表示外部任务输入。"""
    content = str(getattr(message, "content", "") or "")
    return EXTERNAL_REQUEST_HEADER in content
