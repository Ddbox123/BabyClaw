#!/usr/bin/env python3
"""Gym training collection tests."""

import pytest

from core.gym import (
    GymCase,
    GymCollectionRegistry,
    GymExercise,
    GymTrainingCollection,
    build_builtin_collection_registry,
    list_builtin_collections,
    materialize_collection_cases,
    materialize_collection_exercise,
)


def test_builtin_collections_expose_three_training_tiers():
    collections = list_builtin_collections()

    assert [item.training_tier for item in collections] == [
        "foundation",
        "foundation",
        "coordination",
        "intelligence",
    ]
    assert [item.collection_id for item in collections] == [
        "foundation_local_stability",
        "mixed_readiness_gate",
        "coordination_workflow_readiness",
        "intelligence_strategy_readiness",
    ]
    assert collections[0].promotion_gate is True


def test_foundation_collection_materializes_local_stability_cases():
    exercise = materialize_collection_exercise("foundation_local_stability")
    cases = materialize_collection_cases("foundation_local_stability")

    assert exercise.training_tier == "foundation"
    assert exercise.exercise_id == "local_transaction_closing_v1"
    assert len(cases) == 1
    assert cases[0].training_tier == "foundation"
    assert "regression" in cases[0].dataset_splits
    assert "{SAFE_MODIFY_ABSOLUTE_PATH}" in cases[0].prompt
    assert "HARNESS_SAFE_MODIFY_MARKER" in cases[0].prompt
    assert "def probe_marker() -> str" in cases[0].prompt
    assert "import " not in cases[0].prompt
    assert "tests/harness_safe_modify_probe.py" in cases[0].prompt


def test_coordination_collection_materializes_workflow_case():
    registry = build_builtin_collection_registry()

    coordination = registry.get_collection("coordination_workflow_readiness")
    exercise = registry.materialize_exercise("coordination_workflow_readiness")
    cases = registry.materialize_cases("coordination_workflow_readiness")

    assert coordination.training_tier == "coordination"
    assert exercise.training_tier == "coordination"
    assert exercise.exercise_id == "coordination_workflow_readiness_v1"
    assert len(cases) == 1
    assert cases[0].case_id == "coordination_task_validation_probe"
    assert cases[0].validation["min_tasks_completed"] == 2
    assert cases[0].validation["forbidden_tools"] == ["spawn_agent_tool"]
    assert "task_create_tool" in cases[0].allowed_tools
    assert "task_update_tool" in cases[0].allowed_tools


def test_intelligence_collection_materializes_strategy_case():
    registry = build_builtin_collection_registry()

    intelligence = registry.get_collection("intelligence_strategy_readiness")
    exercise = registry.materialize_exercise("intelligence_strategy_readiness")
    cases = registry.materialize_cases("intelligence_strategy_readiness")

    assert intelligence.training_tier == "intelligence"
    assert exercise.training_tier == "intelligence"
    assert exercise.exercise_id == "intelligence_strategy_readiness_v1"
    assert len(cases) == 1
    assert cases[0].case_id == "strategy_selection_policy_probe"
    assert cases[0].validation["scenario"] == "strategy"
    assert cases[0].validation["required_tools"] == ["read_file_tool"]
    assert "open_evolution_transaction_tool" in cases[0].validation["forbidden_tools"]


def test_mixed_readiness_gate_materializes_all_training_tiers():
    registry = build_builtin_collection_registry()

    collection = registry.get_collection("mixed_readiness_gate")
    exercise = registry.materialize_exercise("mixed_readiness_gate")
    cases = registry.materialize_cases("mixed_readiness_gate")

    assert collection.promotion_gate is True
    assert collection.allow_mixed_tiers is True
    assert exercise.exercise_id == "mixed_readiness_gate_v1"
    assert exercise.training_tier == "foundation"
    assert [case.training_tier for case in cases] == ["foundation", "coordination", "intelligence"]
    assert {case.case_id for case in cases} == {
        "local_transaction_closing_probe",
        "coordination_task_validation_probe",
        "strategy_selection_policy_probe",
    }


def test_collection_registry_rejects_case_tier_mismatch():
    registry = GymCollectionRegistry()
    registry.register(
        GymTrainingCollection(
            collection_id="bad_collection",
            name="Bad collection",
            training_tier="coordination",
            objective="mismatch",
        ),
        exercise_factory=lambda: GymExercise(
            exercise_id="bad_exercise",
            name="bad",
            objective="bad",
            capability_tags=[],
            training_tier="coordination",
        ),
        case_factory=lambda: [
            GymCase(
                case_id="foundation_case",
                objective="bad",
                prompt="bad",
                validation={},
                scoring_basis={},
                dataset_splits=["dev"],
                training_tier="foundation",
            )
        ],
    )

    with pytest.raises(ValueError, match="does not match collection"):
        registry.materialize_cases("bad_collection")
