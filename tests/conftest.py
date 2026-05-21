#!/usr/bin/env python3
"""
pytest 配置和共享 fixtures

提供测试所需的共享资源：
- 单例重置（防止测试间状态泄漏）
- 隔离工作空间
- 可复用 mock 对象
"""

import pytest
import os
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# 单例重置 — 最关键的熵增防护机制
# ============================================================================

@pytest.fixture(autouse=True)
def reset_singletons():
    """
    每个测试前后重置所有模块级单例变量，防止测试间状态泄漏。

    覆盖：
    - StateManager (state.py)
    - EventBus (event_bus.py)
    - TaskManager (task_planner.py)
    - ToolExecutor (tool_executor.py)
    - PromptManager (prompt_manager.py)
    """
    # 保存并重置 state.py 单例
    import core.infrastructure.state as _state_mod
    _orig_state = _state_mod._state_manager
    _state_mod._state_manager = None

    # 保存并重置 agent_session.py 单例
    import core.infrastructure.agent_session as _session_mod
    _orig_session = _session_mod._agent_session
    _session_mod._agent_session = None

    # 保存并重置 event_bus.py 单例
    import core.infrastructure.event_bus as _eb_mod
    _orig_bus = _eb_mod._event_bus
    _eb_mod._event_bus = None

    # 保存并重置 task_planner.py 单例
    try:
        import core.orchestration.task_planner as _tp_mod
        _orig_tp = _tp_mod._task_manager_instance
        _tp_mod._task_manager_instance = None
        _orig_tp_root = _tp_mod._task_manager_root
        _tp_mod._task_manager_root = None
    except ImportError:
        pass

    # 保存并重置 tool_executor.py 单例
    try:
        import core.infrastructure.tool_executor as _te_mod
        _orig_te = _te_mod._tool_executor
        _te_mod._tool_executor = None
    except ImportError:
        pass

    # 保存并重置 prompt_manager.py 单例
    try:
        import core.prompt_manager.prompt_manager as _pm_mod
        _orig_pm = _pm_mod._prompt_manager
        _pm_mod._prompt_manager = None
    except ImportError:
        pass

    # 保存并重置 git_memory.py 单例
    try:
        import core.infrastructure.git_memory as _gm_mod
        _orig_gm = _gm_mod._git_memory_service
        _gm_mod._git_memory_service = None
    except ImportError:
        pass

    yield

    # 测试后恢复原始单例（或保持 None）
    _state_mod._state_manager = _orig_state
    _session_mod._agent_session = _orig_session
    _eb_mod._event_bus = _orig_bus
    try:
        _tp_mod._task_manager_instance = _orig_tp
        _tp_mod._task_manager_root = _orig_tp_root
    except (NameError, AttributeError):
        pass
    try:
        _te_mod._tool_executor = _orig_te
    except (NameError, AttributeError):
        pass
    try:
        _pm_mod._prompt_manager = _orig_pm
    except (NameError, AttributeError):
        pass
    try:
        _gm_mod._git_memory_service = _orig_gm
    except (NameError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def isolate_runtime_manager_evolution_store(tmp_path, monkeypatch):
    """Keep manager-owned evolution snapshots out of the real .runtime tree."""
    from core.runtime_manager import evolution_store
    from core.runtime_manager import work_run_store
    try:
        from core.web.services import session_service
    except Exception:
        session_service = None

    runtime_manager_dir = tmp_path / ".runtime" / "runtime-manager"
    evolution_dir = runtime_manager_dir / "evolution"
    self_runs_dir = evolution_dir / "self" / "runs"
    supervised_runs_dir = evolution_dir / "supervised" / "runs"
    work_runs_dir = runtime_manager_dir / "work_runs"

    monkeypatch.setattr(evolution_store, "EVOLUTION_DIR", evolution_dir)
    monkeypatch.setattr(evolution_store, "SELF_RUNS_DIR", self_runs_dir)
    monkeypatch.setattr(evolution_store, "SUPERVISED_RUNS_DIR", supervised_runs_dir)
    monkeypatch.setattr(evolution_store, "SELF_INDEX_PATH", evolution_dir / "self" / "index.json")
    monkeypatch.setattr(evolution_store, "SUPERVISED_INDEX_PATH", evolution_dir / "supervised" / "index.json")
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)
    if session_service is not None:
        monkeypatch.setattr(session_service, "_WORK_RUN_STORE", work_run_store.WorkRunStore(root=work_runs_dir))
        with session_service._RUNNING_SESSIONS_LOCK:
            session_service._RUNNING_SESSION_IDS.clear()
            session_service._SESSION_ACTIVE_TURN_IDS.clear()
            session_service._SESSION_ACTIVE_TURN_LEASES.clear()
        with session_service._SESSION_TURN_CONTROLS_LOCK:
            session_service._SESSION_TURN_CONTROLS.clear()


# ============================================================================
# 隔离工作空间
# ============================================================================

@pytest.fixture
def isolated_workspace(tmp_path):
    """
    提供隔离的 workspace 目录结构，确保测试不触碰真实 workspace/。

    目录结构：
        tmp_path/
        └── workspace/
            ├── memory/
            │   └── archives/
            └── prompts/
    """
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "memory").mkdir()
    (ws / "memory" / "archives").mkdir()
    (ws / "prompts").mkdir()
    return ws


# ============================================================================
# 可复用 Mock 对象
# ============================================================================

@pytest.fixture
def mock_llm_response():
    """返回可自定义的 mock LLM 响应。"""
    from unittest.mock import MagicMock
    resp = MagicMock()
    resp.content = "This is a test response."
    resp.tool_calls = []
    resp.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
    return resp


@pytest.fixture
def project_root():
    """返回项目根目录（Path 对象）。"""
    return PROJECT_ROOT


# ============================================================================
# 自动标记 — 根据文件路径自动应用 pytest markers
# ============================================================================

def pytest_collection_modifyitems(items):
    """
    根据测试文件路径自动应用 markers，无需在每个文件手动加装饰器。

    标记规则：
    - tests/test_xxx.py (tools/)  → tools
    - tests/test_xxx.py (core/infrastructure/) → infrastructure
    - tests/test_xxx.py (core/orchestration/)  → orchestration
    - tests/test_xxx.py (config/)  → config
    """
    from pathlib import Path

    for item in items:
        fspath = Path(str(item.fspath))
        rel = fspath.relative_to(PROJECT_ROOT).as_posix()
        item_path = str(item.fspath)

        # Source-based markers (inferred from test file name)
        stem = fspath.stem  # e.g., "test_shell_tools" → "shell_tools"

        # Heuristic: check what the test file imports to determine layer
        source = fspath.read_text(encoding="utf-8")[:2000]
        if "core.infrastructure" in source or "core/infrastructure" in source:
            item.add_marker(pytest.mark.infrastructure)
        elif "core.orchestration" in source or "core/orchestration" in source:
            item.add_marker(pytest.mark.orchestration)
        elif "config" in stem and "tools" not in stem:
            item.add_marker(pytest.mark.config)
        elif "tools." in source or "from tools" in source or "import tools" in source:
            item.add_marker(pytest.mark.tools)
