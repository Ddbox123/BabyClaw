from langchain_core.messages import SystemMessage

from core.infrastructure.runtime_input import (
    RuntimeInputKind,
    build_external_request_message,
    build_runtime_notice_message,
    is_external_request_message,
)


def test_external_request_message_uses_system_message_with_protocol_header():
    msg = build_external_request_message("验证 Windows 命令")

    assert isinstance(msg, SystemMessage)
    assert msg.type == "system"
    assert RuntimeInputKind.EXTERNAL_REQUEST.value == "external_request"
    assert "外部任务输入" in msg.content
    assert "验证 Windows 命令" in msg.content
    assert "用户" not in msg.content


def test_runtime_notice_message_has_depersonalized_label():
    msg = build_runtime_notice_message("压缩已发生")

    assert isinstance(msg, SystemMessage)
    assert "运行时提示" in msg.content
    assert "压缩已发生" in msg.content
    assert "用户" not in msg.content


def test_is_external_request_message_uses_protocol_header_only():
    external_msg = build_external_request_message("继续执行")

    class UnmarkedHumanMessage:
        type = "human"
        content = "旧日志里的输入"

    assert is_external_request_message(external_msg) is True
    assert is_external_request_message(UnmarkedHumanMessage()) is False
