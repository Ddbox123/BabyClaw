#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.infrastructure.event_bus import Event
from core.infrastructure.mental_model import MentalModel


class TestMentalModelGitSignals:
    def test_file_modified_and_validation_are_reflected(self, tmp_path, monkeypatch):
        import core.infrastructure.mental_model as mm_mod
        import core.infrastructure.agent_session as session_mod

        session_mod._agent_session = None
        MentalModel._instance = None

        class FakeBus:
            def subscribe_global(self, *_args, **_kwargs):
                return "ok"

            def subscribe(self, *_args, **_kwargs):
                return "ok"

        class FakeStateManager:
            def get_consecutive_count(self):
                return 0

        monkeypatch.setattr(mm_mod, "get_event_bus", lambda: FakeBus())
        monkeypatch.setattr(mm_mod, "get_state_manager", lambda: FakeStateManager())

        model = MentalModel(workspace_root=str(tmp_path / "workspace"))
        session = session_mod.get_session_state()
        session.record_modified_path("core/x.py")
        session.record_modified_entities("core/x.py", ["Alpha.run", "Alpha"])

        model._on_file_modified(Event("workspace:file_modified", {"path": "core/x.py"}))
        model._on_validation_completed(Event("validation:completed", {"kind": "tests", "passed": False}))

        model._tool_history.extend(
            [
                mm_mod.ToolRecord("read_file_tool", True, "ok", "t1", "core/x.py"),
                mm_mod.ToolRecord("apply_diff_edit_tool", True, "ok", "t2", "core/x.py"),
                mm_mod.ToolRecord("run_test_for_tool", False, "fail", "t3", None),
            ]
        )
        diagnosis = model.diagnose()

        assert diagnosis.metrics["focused_entity"] in {"Alpha.run", "Alpha"}
        assert diagnosis.metrics["entities_touched_total"] >= 1
        assert diagnosis.metrics["last_validation_passed"] is False
