#!/usr/bin/env python3
"""TaskManager tests for the single tasks.json-backed model."""

from __future__ import annotations

import json

import pytest

from core.orchestration import task_planner
from core.orchestration.task_planner import TaskManager, TaskPriority
from core.prompt_manager.task_analyzer import TaskStatus


@pytest.fixture
def isolated_task_manager(tmp_path, monkeypatch):
    tasks_file = tmp_path / "workspace" / "memory" / "tasks.json"
    monkeypatch.setattr(task_planner, "_tasks_json_path", lambda: str(tasks_file))
    task_planner.reset_task_manager()
    manager = TaskManager()
    yield manager
    task_planner.reset_task_manager()


def test_task_create_replaces_list_and_persists(isolated_task_manager):
    result = isolated_task_manager.task_create(
        [
            {"description": "Inspect config"},
            {"description": "Refactor task manager", "substeps": [{"description": "rewrite"}]},
        ],
        goal="Single source",
    )

    assert "已创建 2 个任务" in result
    assert isolated_task_manager.get_completion_stats() == {"total": 2, "completed": 0, "pending": 2}

    persisted = json.loads(isolated_task_manager._tasks_path.read_text(encoding="utf-8"))
    assert persisted["goal"] == "Single source"
    assert [task["description"] for task in persisted["tasks"]] == [
        "Inspect config",
        "Refactor task manager",
    ]
    assert "subtasks" not in persisted


def test_task_update_updates_same_list_source(isolated_task_manager):
    isolated_task_manager.task_create([{"description": "Ship it"}], goal="Goal")

    result = isolated_task_manager.task_update(1, is_completed=True, result_summary="Done")

    assert result == "任务 1 已更新: 完成"
    assert isolated_task_manager.task_list()[0]["is_completed"] is True
    assert isolated_task_manager.get_task("1").status == TaskStatus.COMPLETED
    assert isolated_task_manager.get_completion_stats() == {"total": 1, "completed": 1, "pending": 0}


def test_create_task_and_complete_task_share_storage(isolated_task_manager):
    task_id = isolated_task_manager.create_task(
        "Add tests",
        description="Add direct tests",
        priority=TaskPriority.HIGH,
    )

    assert task_id == "1"
    assert isolated_task_manager.task_list()[0]["description"] == "Add direct tests"

    assert isolated_task_manager.complete_task(task_id, "Covered") is True
    task = isolated_task_manager.task_list()[0]
    assert task["is_completed"] is True
    assert task["status"] == TaskStatus.COMPLETED.value
    assert task["result_summary"] == "Covered"


def test_current_plan_is_projection_not_second_storage(isolated_task_manager):
    isolated_task_manager.task_create(
        [{"description": "One"}, {"description": "Two"}],
        goal="Projected plan",
    )

    plan = isolated_task_manager.get_current_plan()

    assert plan is not None
    assert plan.goal == "Projected plan"
    assert list(plan.tasks) == ["1", "2"]
    assert plan.tasks["1"].description == "One"


def test_prioritize_reorders_single_list(isolated_task_manager):
    isolated_task_manager.task_create(
        [{"description": "A"}, {"description": "B"}, {"description": "C"}],
        goal="Order",
    )

    assert isolated_task_manager.task_prioritize([3, 1]) == [3, 1]
    assert [task["id"] for task in isolated_task_manager.task_list()] == [3, 1, 2]


def test_task_breakdown_is_persisted_on_task(isolated_task_manager):
    isolated_task_manager.task_create([{"description": "分析日志系统"}], goal="Breakdown")

    substeps = isolated_task_manager.task_breakdown(1)

    assert substeps
    assert isolated_task_manager.task_list()[0]["substeps"] == substeps
    persisted = json.loads(isolated_task_manager._tasks_path.read_text(encoding="utf-8"))
    assert persisted["tasks"][0]["substeps"] == substeps
