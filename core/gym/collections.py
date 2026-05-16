# -*- coding: utf-8 -*-
"""Built-in Gym training collections."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional

from .coordination import build_coordination_workflow_exercise, materialize_coordination_workflow_cases
from .intelligence import build_intelligence_strategy_exercise, materialize_intelligence_strategy_cases
from .local import build_local_transaction_exercise, materialize_local_transaction_cases
from .mixed import build_mixed_readiness_gate_exercise, materialize_mixed_readiness_gate_cases
from .models import GymCase, GymExercise, GymTrainingCollection, normalize_training_tier


CaseFactory = Callable[[], list[GymCase]]
ExerciseFactory = Callable[[], GymExercise]


class GymCollectionRegistry:
    def __init__(self) -> None:
        self._collections: dict[str, GymTrainingCollection] = {}
        self._exercise_factories: dict[str, ExerciseFactory] = {}
        self._case_factories: dict[str, CaseFactory] = {}

    def register(
        self,
        collection: GymTrainingCollection,
        *,
        exercise_factory: ExerciseFactory,
        case_factory: CaseFactory,
    ) -> None:
        self._collections[collection.collection_id] = collection
        self._exercise_factories[collection.collection_id] = exercise_factory
        self._case_factories[collection.collection_id] = case_factory

    def list_collections(self, *, training_tier: Optional[str] = None) -> list[GymTrainingCollection]:
        tier = normalize_training_tier(training_tier) if training_tier else None
        collections = list(self._collections.values())
        if tier:
            collections = [item for item in collections if item.training_tier == tier]
        return sorted(collections, key=lambda item: (_tier_rank(item.training_tier), item.collection_id))

    def get_collection(self, collection_id: str) -> GymTrainingCollection:
        try:
            return self._collections[collection_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Gym training collection: {collection_id}") from exc

    def materialize_exercise(self, collection_id: str) -> GymExercise:
        self.get_collection(collection_id)
        return self._exercise_factories[collection_id]()

    def materialize_cases(self, collection_id: str) -> list[GymCase]:
        collection = self.get_collection(collection_id)
        cases = self._case_factories[collection_id]()
        for case in cases:
            if not collection.allow_mixed_tiers and case.training_tier != collection.training_tier:
                raise ValueError(
                    f"Case {case.case_id} tier {case.training_tier!r} does not match collection {collection.collection_id}"
                )
        return cases


def build_builtin_collection_registry() -> GymCollectionRegistry:
    registry = GymCollectionRegistry()
    registry.register(
        GymTrainingCollection(
            collection_id="foundation_local_stability",
            name="Foundation local stability",
            training_tier="foundation",
            objective="Protect core Agent stability: transaction closure, validation, safe edit discipline, and recovery basics.",
            exercise_ids=["local_transaction_closing_v1"],
            capability_tags=["planning", "validation", "tool_routing", "recovery"],
            promotion_gate=True,
        ),
        exercise_factory=build_local_transaction_exercise,
        case_factory=materialize_local_transaction_cases,
    )
    registry.register(
        GymTrainingCollection(
            collection_id="mixed_readiness_gate",
            name="Mixed readiness gate",
            training_tier="foundation",
            objective="Run foundation, coordination, and intelligence readiness cases through one promotion gate.",
            exercise_ids=["mixed_readiness_gate_v1"],
            capability_tags=["planning", "validation", "coordination", "diagnosis", "selection"],
            promotion_gate=True,
            allow_mixed_tiers=True,
        ),
        exercise_factory=build_mixed_readiness_gate_exercise,
        case_factory=materialize_mixed_readiness_gate_cases,
    )
    registry.register(
        GymTrainingCollection(
            collection_id="coordination_workflow_readiness",
            name="Coordination workflow readiness",
            training_tier="coordination",
            objective="Exercise cooperation across planning, context, validation, memory, recovery, delegation, and runtime flows.",
            exercise_ids=["coordination_workflow_readiness_v1"],
            capability_tags=["planning", "context", "validation", "memory", "recovery"],
            promotion_gate=False,
        ),
        exercise_factory=build_coordination_workflow_exercise,
        case_factory=materialize_coordination_workflow_cases,
    )
    registry.register(
        GymTrainingCollection(
            collection_id="intelligence_strategy_readiness",
            name="Intelligence strategy readiness",
            training_tier="intelligence",
            objective="Exercise diagnosis, abstraction, self-correction, generalization, and Candidate Improvement quality.",
            exercise_ids=["intelligence_strategy_readiness_v1"],
            capability_tags=["diagnosis", "abstraction", "self_correction", "generalization"],
            promotion_gate=False,
        ),
        exercise_factory=build_intelligence_strategy_exercise,
        case_factory=materialize_intelligence_strategy_cases,
    )
    return registry


def list_builtin_collections(*, training_tier: Optional[str] = None) -> list[GymTrainingCollection]:
    return build_builtin_collection_registry().list_collections(training_tier=training_tier)


def materialize_collection_cases(collection_id: str) -> list[GymCase]:
    return build_builtin_collection_registry().materialize_cases(collection_id)


def materialize_collection_exercise(collection_id: str) -> GymExercise:
    return build_builtin_collection_registry().materialize_exercise(collection_id)


def _placeholder_exercise(
    *,
    exercise_id: str,
    name: str,
    training_tier: str,
    objective: str,
    capability_tags: list[str],
) -> GymExercise:
    return GymExercise(
        exercise_id=exercise_id,
        name=name,
        objective=objective,
        capability_tags=capability_tags,
        training_tier=training_tier,
        dataset_names=[],
        default_splits=["train", "dev"],
    )


def _tier_rank(tier: str) -> int:
    return {"foundation": 0, "coordination": 1, "intelligence": 2}[tier]
