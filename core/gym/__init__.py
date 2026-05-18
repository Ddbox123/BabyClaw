# -*- coding: utf-8 -*-
"""Task-driven Gym v1 domain surface."""

from .models import (
    ALLOWED_DATASET_SPLITS,
    ALLOWED_TRAINING_TIERS,
    CandidateImprovement,
    EvaluationRun,
    GeneratedCaseProvenance,
    GymCase,
    GymExercise,
    GymTrainingCollection,
    HarnessVariant,
    ImprovementEpisode,
    PromotionProposal,
    Score,
    Trace,
    Attempt,
    normalize_dataset_splits,
    normalize_training_tier,
)
from .local import build_local_transaction_exercise, materialize_local_transaction_cases
from .coordination import build_coordination_workflow_exercise, materialize_coordination_workflow_cases
from .intelligence import build_intelligence_strategy_exercise, materialize_intelligence_strategy_cases
from .mixed import build_mixed_readiness_gate_exercise, materialize_mixed_readiness_gate_cases
from .episodes import record_improvement_episode
from .collections import (
    GymCollectionRegistry,
    build_builtin_collection_registry,
    list_builtin_collections,
    materialize_collection_cases,
    materialize_collection_exercise,
)
from .engine import AgentHarnessAdapter, AttemptEvidence, CriticDiagnosis, EvolutionEngine
from .adapter_contract import AdapterContractCheck, validate_agent_harness_adapter
from .generic_adapter import CallableAgentHarnessAdapter, GenericCaseResult
from .generated_cases import append_generated_case, build_generated_case
from .promotion import (
    GymPromotionActivation,
    GymPromotionApplication,
    GymPromotionRollback,
    activate_gym_promotion_proposal,
    apply_gym_promotion_proposal,
    rollback_gym_promotion_proposal,
)
from .advisory import (
    ActiveAdvisoryBaseline,
    build_active_advisory_snapshot,
    load_active_advisory_baselines,
    summarize_active_advisory_baselines,
)
from .selection import TierScoreSummary, TierSelectionDecision, select_by_training_tier
from .vibelution_adapter import VibelutionAgentHarnessAdapter
from .runner import (
    DEFAULT_COLLECTION_ID,
    PROMOTION_GATE_COLLECTION_ID,
    GymRunResult,
    format_gym_run_result,
    run_gym_collection_episode,
    run_promotion_gate_episode,
)

__all__ = [
    "ALLOWED_DATASET_SPLITS",
    "ALLOWED_TRAINING_TIERS",
    "AdapterContractCheck",
    "DEFAULT_COLLECTION_ID",
    "PROMOTION_GATE_COLLECTION_ID",
    "Attempt",
    "AttemptEvidence",
    "AgentHarnessAdapter",
    "CandidateImprovement",
    "CallableAgentHarnessAdapter",
    "CriticDiagnosis",
    "EvaluationRun",
    "EvolutionEngine",
    "GeneratedCaseProvenance",
    "GenericCaseResult",
    "GymCase",
    "GymExercise",
    "GymCollectionRegistry",
    "GymRunResult",
    "GymTrainingCollection",
    "GymPromotionActivation",
    "GymPromotionApplication",
    "GymPromotionRollback",
    "ActiveAdvisoryBaseline",
    "HarnessVariant",
    "ImprovementEpisode",
    "PromotionProposal",
    "Score",
    "Trace",
    "TierScoreSummary",
    "TierSelectionDecision",
    "VibelutionAgentHarnessAdapter",
    "append_generated_case",
    "activate_gym_promotion_proposal",
    "apply_gym_promotion_proposal",
    "build_active_advisory_snapshot",
    "build_builtin_collection_registry",
    "build_coordination_workflow_exercise",
    "build_generated_case",
    "build_intelligence_strategy_exercise",
    "build_local_transaction_exercise",
    "build_mixed_readiness_gate_exercise",
    "format_gym_run_result",
    "list_builtin_collections",
    "load_active_advisory_baselines",
    "materialize_collection_cases",
    "materialize_collection_exercise",
    "materialize_coordination_workflow_cases",
    "materialize_intelligence_strategy_cases",
    "materialize_local_transaction_cases",
    "materialize_mixed_readiness_gate_cases",
    "normalize_dataset_splits",
    "normalize_training_tier",
    "record_improvement_episode",
    "rollback_gym_promotion_proposal",
    "run_gym_collection_episode",
    "run_promotion_gate_episode",
    "select_by_training_tier",
    "summarize_active_advisory_baselines",
    "validate_agent_harness_adapter",
]
