# -*- coding: utf-8 -*-
"""Built-in mixed-tier Gym gate."""

from __future__ import annotations

from .coordination import materialize_coordination_workflow_cases
from .intelligence import materialize_intelligence_strategy_cases
from .local import materialize_local_transaction_cases
from .models import GymCase, GymExercise


def build_mixed_readiness_gate_exercise() -> GymExercise:
    return GymExercise(
        exercise_id="mixed_readiness_gate_v1",
        name="Mixed readiness gate",
        objective="Evaluate foundation, coordination, and intelligence readiness in one proposal-only episode.",
        capability_tags=["planning", "validation", "coordination", "diagnosis", "selection"],
        training_tier="foundation",
        dataset_names=["builtin_mixed_gym"],
        default_splits=["train", "dev", "regression"],
    )


def materialize_mixed_readiness_gate_cases() -> list[GymCase]:
    cases: list[GymCase] = []
    cases.extend(materialize_local_transaction_cases())
    cases.extend(materialize_coordination_workflow_cases())
    cases.extend(materialize_intelligence_strategy_cases())
    return cases
