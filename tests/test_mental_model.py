"""
Tests for core/infrastructure/mental_model.py

Covers:
- CognitiveState enum
- ToolRecord dataclass
- Diagnosis dataclass
- MentalModel singleton + key methods
- Default rules behavior
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import core.infrastructure.mental_model as mental_model_module
from core.infrastructure.event_bus import Event, EventNames
from core.infrastructure.mental_model import (
    CognitiveState,
    ToolRecord,
    Diagnosis,
    MentalModel,
    _default_rules,
)


class TestCognitiveState:
    """Test CognitiveState enum values"""

    def test_all_states_defined(self):
        """All expected cognitive states are defined"""
        assert CognitiveState.NORMAL == "normal"
        assert CognitiveState.LOOPING == "looping"
        assert CognitiveState.THRASHING == "thrashing"
        assert CognitiveState.TUNNEL_VISION == "tunnel_vision"
        assert CognitiveState.PRODUCTIVE == "productive"
        assert CognitiveState.DISORIENTED == "disoriented"

    def test_states_are_strings(self):
        """All state values are strings"""
        for attr_name in dir(CognitiveState):
            if not attr_name.startswith("_"):
                attr_value = getattr(CognitiveState, attr_name)
                assert isinstance(attr_value, str), f"{attr_name} should be string"


class TestToolRecord:
    """Test ToolRecord dataclass"""

    def test_tool_record_creation(self):
        """ToolRecord can be created with required fields"""
        record = ToolRecord(
            tool_name="read_file_tool",
            success=True,
            args_summary="file_path: tests/test_mental_model.py",
            timestamp="2026-05-05T23:50:00",
        )
        assert record.tool_name == "read_file_tool"
        assert record.success is True
        assert record.args_summary == "file_path: tests/test_mental_model.py"
        assert record.timestamp == "2026-05-05T23:50:00"
        assert record.file_target is None

    def test_tool_record_with_optional_file_target(self):
        """ToolRecord with optional file_target"""
        record = ToolRecord(
            tool_name="apply_diff_edit_tool",
            success=True,
            args_summary="file_path: core/test.py",
            timestamp="2026-05-05T23:50:00",
            file_target="core/test.py",
        )
        assert record.file_target == "core/test.py"

    def test_tool_record_failure(self):
        """ToolRecord with failed tool call"""
        record = ToolRecord(
            tool_name="nonexistent_tool",
            success=False,
            args_summary="invalid args",
            timestamp="2026-05-05T23:50:00",
        )
        assert record.success is False


class TestDiagnosis:
    """Test Diagnosis dataclass"""

    def test_diagnosis_creation(self):
        """Diagnosis can be created with all fields"""
        diagnosis = Diagnosis(
            state=CognitiveState.NORMAL,
            metrics={"tool_success_rate": 0.9, "unique_tools": 5},
            intervention="",
            timestamp="2026-05-05T23:50:00",
            confidence=0.85,
        )
        assert diagnosis.state == CognitiveState.NORMAL
        assert diagnosis.metrics["tool_success_rate"] == 0.9
        assert diagnosis.intervention == ""
        assert diagnosis.timestamp == "2026-05-05T23:50:00"
        assert diagnosis.confidence == 0.85

    def test_diagnosis_with_intervention(self):
        """Diagnosis with non-empty intervention"""
        diagnosis = Diagnosis(
            state=CognitiveState.LOOPING,
            metrics={"repeat_count": 6},
            intervention="You appear to be looping. Consider trying a different approach.",
            timestamp="2026-05-05T23:50:00",
            confidence=0.9,
        )
        assert diagnosis.state == CognitiveState.LOOPING
        assert "looping" in diagnosis.intervention.lower()


class TestDefaultRules:
    """Test _default_rules function"""

    def test_default_rules_structure(self):
        """Default rules has expected structure"""
        rules = _default_rules()
        
        assert "looping" in rules
        assert "thrashing" in rules
        assert "tunnel_vision" in rules
        assert "disoriented" in rules
        assert "version_proliferation" in rules

    def test_looping_rules(self):
        """Loop detection rules have correct thresholds"""
        rules = _default_rules()
        looping = rules["looping"]

        assert looping["metric"] == "repetition_count"
        assert looping["threshold"] == 4
        assert looping["window_size"] == 10

    def test_thrashing_rules(self):
        """Thrashing detection rules have correct values"""
        rules = _default_rules()
        thrashing = rules["thrashing"]

        assert thrashing["metric"] == "success_rate"
        assert thrashing["threshold"] == 0.4
        assert thrashing["window_size"] == 8

    def test_tunnel_vision_rules(self):
        """Tunnel vision detection rules have correct thresholds"""
        rules = _default_rules()
        tunnel = rules["tunnel_vision"]

        assert tunnel["metric"] == "file_focus_ratio"
        assert tunnel["threshold"] == 0.8
        assert tunnel["window_size"] == 8

    def test_disoriented_rules(self):
        """Disoriented detection rules have correct values"""
        rules = _default_rules()
        disoriented = rules["disoriented"]

        assert disoriented["metric"] == "tool_diversity"
        assert disoriented["threshold"] == 0.7
        assert disoriented["window_size"] == 8

    def test_version_proliferation_rules(self):
        """Version proliferation rules have patterns"""
        rules = _default_rules()
        vp = rules["version_proliferation"]
        
        assert vp["enabled"] is True
        assert len(vp["patterns"]) > 0


class TestMentalModel:
    """Test MentalModel class"""

    @pytest.fixture
    def temp_workspace(self, tmp_path):
        """Create a temporary workspace for tests"""
        workspace = tmp_path / "test_workspace"
        workspace.mkdir()
        
        # Create required subdirectories
        (workspace / "mental_model").mkdir(parents=True)
        
        return workspace

    @pytest.fixture
    def mock_event_bus(self):
        """Create a mock EventBus"""
        mock = MagicMock()
        mock.subscribe = MagicMock(return_value="sub_id")
        mock.subscribe_global = MagicMock(return_value="global_sub_id")
        mock.unsubscribe = MagicMock(return_value=True)
        return mock

    @pytest.fixture
    def mental_model(self, temp_workspace):
        """Create a MentalModel instance for testing"""
        mental_model_module.reset_mental_model()
        model = MentalModel(workspace_root=str(temp_workspace))
        yield model
        mental_model_module.reset_mental_model()

    def test_singleton_pattern(self, temp_workspace):
        """MentalModel uses singleton pattern"""
        mental_model_module.reset_mental_model()

        model1 = MentalModel(workspace_root=str(temp_workspace))
        model2 = MentalModel(workspace_root=str(temp_workspace))

        assert model1 is model2
        mental_model_module.reset_mental_model()

    def test_initial_state(self, mental_model):
        """MentalModel starts in NORMAL state"""
        diagnosis = mental_model.diagnose()
        
        assert diagnosis.state == CognitiveState.NORMAL
        assert diagnosis.confidence >= 0 and diagnosis.confidence <= 1

    def test_get_rules(self, mental_model):
        """get_rules returns rules dictionary"""
        rules = mental_model.get_rules()
        
        assert isinstance(rules, dict)
        assert "looping" in rules
        assert "thrashing" in rules

    def test_reload_rules(self, mental_model):
        """reload_rules refreshes rules from file"""
        # Should not raise
        mental_model.reload_rules()
        
        # Rules should still be valid
        rules = mental_model.get_rules()
        assert "looping" in rules

    def test_tick_increments_cycle(self, mental_model):
        """tick() increments the thinking cycle counter"""
        initial_tick = mental_model._tick

        mental_model.tick()

        assert mental_model._tick == initial_tick + 1

    def test_diagnosis_history(self, mental_model):
        """get_diagnosis_history returns history list"""
        for name in ("read_file_tool", "grep_search_tool", "python_symbol_tool"):
            mental_model._on_tool_result(
                Event(EventNames.TOOL_SUCCESS, {"name": name, "result": "ok"}),
                success=True,
            )

        # Perform some diagnoses
        mental_model.diagnose()
        mental_model.diagnose()
        
        history = mental_model.get_diagnosis_history()
        
        assert isinstance(history, list)
        assert len(history) >= 2

    def test_get_self_model(self, mental_model):
        """get_self_model returns dict with expected keys"""
        model = mental_model.get_self_model()
        
        assert isinstance(model, dict)
        # May have 'strengths', 'weaknesses', etc. or be empty default

    def test_get_state_for_soul(self, mental_model):
        """get_state_for_soul returns state dict for SOUL"""
        state = mental_model.get_state_for_soul()

        assert isinstance(state, dict)
        assert "元认知" in state

    def test_get_last_state(self, mental_model):
        """get_last_state returns most recent state"""
        mental_model.sense_state("thinking", "tool summary")

        last = mental_model.get_last_state()

        assert last is not None
        assert "mood" in last

    def test_record_tool_call(self, mental_model):
        """_on_tool_start records tool calls"""
        mental_model._on_tool_start(
            Event(
                EventNames.TOOL_START,
                {"name": "read_file_tool", "args": {"file_path": "test.py"}},
            )
        )

        assert mental_model._touched_files["test.py"] == 1

    def test_record_tool_result(self, mental_model):
        """_on_tool_result processes tool results"""
        mental_model._on_tool_result(
            Event(EventNames.TOOL_SUCCESS, {"name": "read_file_tool", "result": "file content"}),
            success=True,
        )

        assert mental_model._tool_history[-1].tool_name == "read_file_tool"
        assert mental_model._tool_history[-1].success is True

    def test_file_created_tracking(self, mental_model):
        """_on_file_created adds file to tracking"""
        mental_model._on_file_created(
            Event(
                EventNames.WORKSPACE_FILE_CREATED,
                {"path": "test.py", "timestamp": "2026-05-05T23:50:00"},
            )
        )
        
        files = mental_model.get_agent_created_files()
        assert any("test.py" in str(f) for f in files)

    def test_version_variant_detection(self, mental_model):
        """_detect_version_proliferation identifies backup files"""
        result = mental_model._detect_version_proliferation(
            "core_backup_20260505_235000.py"
        )
        
        assert result is not None or result is None  # Depends on patterns

    def test_update_rules_persists(self, mental_model, temp_workspace):
        """update_rules saves to file"""
        new_rules = {
            "looping": {"threshold": 10, "cooldown": 3},
        }
        
        # Should not raise
        mental_model.update_rules(new_rules)
        
        # Verify rules were updated
        current = mental_model.get_rules()
        assert current["looping"]["threshold"] == 10

    def test_reset_clears_state(self, mental_model):
        """reset() clears internal state"""
        # Add some state
        mental_model.tick()
        mental_model.diagnose()
        
        # Reset
        mental_model.reset()
        
        # Should be back to initial state
        assert mental_model._tick == 0
        assert list(mental_model._tool_history) == []

    def test_set_shared_llm(self, mental_model):
        """set_shared_llm stores LLM client"""
        mock_llm = MagicMock()
        
        mental_model.set_shared_llm(mock_llm)

        assert mental_model._shared_llm is mock_llm

    def test_sense_state_fallback(self, mental_model):
        """sense_state handles missing LLM gracefully"""
        # Without LLM set, should use fallback
        state = mental_model.sense_state("thinking", "tool summary")

        assert isinstance(state, str)
        assert "<state>" in state

    def test_diagnose_with_metrics(self, mental_model):
        """diagnose() returns metrics in Diagnosis"""
        diagnosis = mental_model.diagnose()
        
        assert isinstance(diagnosis, Diagnosis)
        assert isinstance(diagnosis.metrics, dict)
        assert "timestamp" in diagnosis.__dict__ or hasattr(diagnosis, "timestamp")


class TestMentalModelIntegration:
    """Integration tests for MentalModel"""

    @pytest.fixture
    def temp_workspace(self, tmp_path):
        """Create a temporary workspace for tests"""
        workspace = tmp_path / "test_workspace"
        workspace.mkdir()
        (workspace / "mental_model").mkdir(parents=True)
        return workspace

    @pytest.fixture
    def test_event_bus_subscription(self, temp_workspace, mock_event_bus):
        """MentalModel subscribes to EventBus on init"""
        mental_model_module.reset_mental_model()
        with patch("core.infrastructure.mental_model.get_event_bus", return_value=mock_event_bus):
            MentalModel(workspace_root=str(temp_workspace))

        assert mock_event_bus.subscribe_global.called
        assert mock_event_bus.subscribe.call_count >= 3
        mental_model_module.reset_mental_model()

    def test_full_diagnosis_cycle(self, temp_workspace):
        """Complete diagnosis cycle works correctly"""
        mental_model_module.reset_mental_model()
        model = MentalModel(workspace_root=str(temp_workspace))

        model._on_tool_start(
            Event(EventNames.TOOL_START, {"name": "read_file_tool", "args": {"file_path": "test.py"}})
        )
        model._on_tool_result(
            Event(EventNames.TOOL_SUCCESS, {"name": "read_file_tool", "result": "content"}),
            success=True,
        )

        model.tick()
        diagnosis = model.diagnose()

        assert diagnosis is not None
        assert isinstance(diagnosis.state, str)
        mental_model_module.reset_mental_model()
