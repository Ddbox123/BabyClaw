# -*- coding: utf-8 -*-

from core.orchestration.subagent_roles import (
    ALLOWED_SUBAGENT_TASK_TYPES,
    SubagentRoleNeed,
    get_subagent_role_spec,
)


def test_subagent_role_specs_cover_allowed_task_types():
    assert ALLOWED_SUBAGENT_TASK_TYPES == {"diagnose", "inspect", "summarize"}
    for task_type in ALLOWED_SUBAGENT_TASK_TYPES:
        spec = get_subagent_role_spec(task_type)
        assert spec.task_type == task_type
        assert spec.role_name
        assert spec.system_purpose
        assert len(spec.owned_work) == 2
        assert len(spec.forbidden_work) == 2
        assert spec.return_shape


def test_unknown_subagent_role_defaults_to_inspect():
    spec = get_subagent_role_spec("unknown")
    assert spec.task_type == "inspect"
    assert spec.role_name == "局部状态探针"


def test_subagent_role_need_shape_is_explicit():
    need = SubagentRoleNeed(
        task_type="diagnose",
        trigger_reason="failure_attribution_needed",
        why_now="当前更缺的是局部故障归因证据。",
    )
    assert need.task_type == "diagnose"
    assert need.trigger_reason == "failure_attribution_needed"
    assert "故障归因" in need.why_now
