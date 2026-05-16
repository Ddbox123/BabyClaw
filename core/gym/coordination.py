# -*- coding: utf-8 -*-
"""Built-in coordination-tier Gym exercises."""

from __future__ import annotations

from .models import GymCase, GymExercise


def build_coordination_workflow_exercise() -> GymExercise:
    return GymExercise(
        exercise_id="coordination_workflow_readiness_v1",
        name="Coordination workflow readiness",
        objective="Coordinate planning, task memory, validation, and transaction closure in one bounded workflow.",
        capability_tags=["planning", "context", "validation", "memory", "recovery"],
        training_tier="coordination",
        dataset_names=["builtin_coordination_gym"],
        default_splits=["train", "dev", "regression"],
    )


def materialize_coordination_workflow_cases() -> list[GymCase]:
    exercise = build_coordination_workflow_exercise()
    prompt = (
        "Run this coordination workflow Gym probe in the main agent only. Follow these exact steps: "
        "1) call open_evolution_transaction_tool; "
        "2) call task_create_tool with exactly two tasks: lint scripts/evolution_harness.py, close the workflow; "
        "3) call python_lint_tool on scripts/evolution_harness.py; "
        "4) if lint passes, call task_update_tool for task 1 with is_completed=true; "
        "5) call task_update_tool for task 2 with is_completed=true; "
        "6) call close_evolution_transaction_tool with status=success. "
        "Do not call spawn_agent_tool. Do not modify files, commit, restart, or delegate."
    )
    return [
        GymCase(
            case_id="coordination_task_validation_probe",
            objective=exercise.objective,
            prompt=prompt,
            validation={
                "scenario": "transaction",
                "mode": "single_turn",
                "expect_restart": False,
                "timeout_seconds": 600,
                "commands": ["python_lint_tool scripts/evolution_harness.py"],
                "min_tasks_created": 1,
                "min_tasks_updated": 2,
                "min_tasks_completed": 2,
                "min_validation_passed": 1,
                "forbidden_tools": ["spawn_agent_tool"],
            },
            scoring_basis={
                "success": "transaction closes only after lint passes and both coordination tasks are completed",
                "quality": "task state matches the observed workflow",
                "regression": "no file modification, restart, commit, or delegation",
            },
            dataset_splits=exercise.default_splits,
            training_tier=exercise.training_tier,
            capability_tags=exercise.capability_tags,
            constraints=[
                "create a two-item task list",
                "run validation before closing",
                "complete both tasks before closing",
                "do not call spawn_agent_tool",
                "do not modify files",
                "do not commit",
                "do not restart",
                "do not delegate",
            ],
            allowed_tools=[
                "open_evolution_transaction_tool",
                "task_create_tool",
                "python_lint_tool",
                "task_update_tool",
                "close_evolution_transaction_tool",
            ],
            dataset_ref={"dataset": "builtin_coordination_gym", "exercise_id": exercise.exercise_id},
        )
    ]
