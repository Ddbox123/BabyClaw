# -*- coding: utf-8 -*-
"""Built-in intelligence-tier Gym exercises."""

from __future__ import annotations

from .models import GymCase, GymExercise


def build_intelligence_strategy_exercise() -> GymExercise:
    return GymExercise(
        exercise_id="intelligence_strategy_readiness_v1",
        name="Intelligence strategy readiness",
        objective="Diagnose a bounded policy problem and produce a concrete improvement strategy without editing files.",
        capability_tags=["diagnosis", "abstraction", "self_correction", "generalization"],
        training_tier="intelligence",
        dataset_names=["builtin_intelligence_gym"],
        default_splits=["train", "observe", "regression"],
    )


def materialize_intelligence_strategy_cases() -> list[GymCase]:
    exercise = build_intelligence_strategy_exercise()
    prompt = (
        "Run this intelligence strategy Gym probe as a read-only analysis. "
        "Read core/gym/selection.py and core/gym/vibelution_adapter.py, then answer with exactly three bullets: "
        "1) the promotion risk in one sentence, "
        "2) the smallest policy improvement in one sentence, "
        "3) the regression test that would protect it in one sentence. "
        "Do not modify files, open an evolution transaction, commit, restart, or delegate."
    )
    return [
        GymCase(
            case_id="strategy_selection_policy_probe",
            objective=exercise.objective,
            prompt=prompt,
            validation={
                "scenario": "strategy",
                "mode": "single_turn",
                "expect_restart": False,
                "timeout_seconds": 600,
                "required_tools": ["read_file_tool"],
                "forbidden_tools": [
                    "spawn_agent_tool",
                    "write_file_tool",
                    "append_file_tool",
                    "open_evolution_transaction_tool",
                    "close_evolution_transaction_tool",
                    "trigger_self_restart_tool",
                ],
            },
            scoring_basis={
                "success": "the agent grounds its strategy in repository evidence without mutating state",
                "quality": "diagnosis, policy improvement, and regression test are distinct and concrete",
                "regression": "no edits, transactions, commits, restarts, or delegation",
            },
            dataset_splits=exercise.default_splits,
            training_tier=exercise.training_tier,
            capability_tags=exercise.capability_tags,
            constraints=[
                "read the named files before answering",
                "return exactly three bullets",
                "do not modify files",
                "do not open an evolution transaction",
                "do not delegate",
            ],
            allowed_tools=["read_file_tool"],
            dataset_ref={"dataset": "builtin_intelligence_gym", "exercise_id": exercise.exercise_id},
        )
    ]
