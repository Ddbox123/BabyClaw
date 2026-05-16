# -*- coding: utf-8 -*-
"""Built-in local Gym exercises for v1 smoke coverage."""

from __future__ import annotations

from .models import GymCase, GymExercise

SAFE_MODIFY_ABSOLUTE_PATH_PLACEHOLDER = "{SAFE_MODIFY_ABSOLUTE_PATH}"
SAFE_MODIFY_MARKER = "HARNESS_SAFE_MODIFY_MARKER"
SAFE_MODIFY_PROBE_CONTENT = (
    'HARNESS_SAFE_MODIFY_MARKER = "HARNESS_SAFE_MODIFY_MARKER"\n\n'
    "\n"
    "def probe_marker() -> str:\n"
    "    return HARNESS_SAFE_MODIFY_MARKER\n"
)


def build_local_transaction_exercise() -> GymExercise:
    return GymExercise(
        exercise_id="local_transaction_closing_v1",
        name="Local transaction closing",
        objective="Close a local edit transaction by reading the goal, making one safe file change, running validation, and recording the outcome.",
        capability_tags=["planning", "validation", "tool_routing", "recovery"],
        training_tier="foundation",
        dataset_names=["supervised_dry_run"],
        default_splits=["train", "dev", "regression"],
    )


def materialize_local_transaction_cases() -> list[GymCase]:
    exercise = build_local_transaction_exercise()
    prompt = (
        "Run the local transaction closing Gym probe: open one evolution transaction, "
        f"write this exact Python content to {SAFE_MODIFY_ABSOLUTE_PATH_PLACEHOLDER}: "
        f"{SAFE_MODIFY_PROBE_CONTENT!r}. Run python_lint_tool on "
        "tests/harness_safe_modify_probe.py, and close the transaction with success only after validation passes. "
        "Do not commit, restart, delegate, or modify any other file."
    )
    return [
        GymCase(
            case_id="local_transaction_closing_probe",
            objective=exercise.objective,
            prompt=prompt,
            validation={
                "scenario": "modify_rollback",
                "mode": "single_turn",
                "expect_restart": False,
                "timeout_seconds": 600,
                "commands": ["python_lint_tool tests/harness_safe_modify_probe.py"],
            },
            scoring_basis={
                "success": "transaction closed after validation passes and the safe modify probe exists",
                "quality": "only the probe file changes",
                "regression": "no restart, commit, or delegation",
            },
            dataset_splits=exercise.default_splits,
            training_tier=exercise.training_tier,
            capability_tags=exercise.capability_tags,
            constraints=[
                f"write the probe with write_file_tool at {SAFE_MODIFY_ABSOLUTE_PATH_PLACEHOLDER}",
                f"probe content must equal {SAFE_MODIFY_PROBE_CONTENT!r}",
                "modify only tests/harness_safe_modify_probe.py",
                f"include literal marker {SAFE_MODIFY_MARKER}",
                "run validation before closing",
                "do not commit",
                "do not restart",
                "do not delegate",
            ],
            allowed_tools=[
                "open_evolution_transaction_tool",
                "write_file_tool",
                "python_lint_tool",
                "close_evolution_transaction_tool",
            ],
            dataset_ref={"dataset": "builtin_local_gym", "exercise_id": exercise.exercise_id},
        )
    ]
