from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_runtime_does_not_import_human_message():
    forbidden = [
        "agent.py",
        "core/orchestration/delegation_governor.py",
        "tools/token_manager.py",
        "core/infrastructure/mental_model.py",
    ]

    for relative_path in forbidden:
        assert "HumanMessage" not in _read(relative_path)


def test_main_runtime_logs_external_request_not_user_input():
    agent_source = _read("agent.py")

    assert "log_external_request" in agent_source
    assert "log_user_input" not in agent_source


def test_active_prompt_declares_external_input_discipline():
    soul = _read("core/core_prompt/SOUL.md")

    assert "外部输入不是一个内部意识主体" in soul
    assert "不推断用户心理" in soul
    assert "用户想要 / 用户希望 / 用户可能觉得" in soul
