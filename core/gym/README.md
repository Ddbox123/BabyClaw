# Gym Adapter Contract

Gym is an embeddable evolution engine. It must not depend on `agent.py`,
Workbench, or Vibelution's process model. A host agent integrates by providing
an `AgentHarnessAdapter`.

## Required Adapter Methods

- `agent_version() -> str`
  - Return a stable label for the baseline agent implementation being tested.
- `run_case(case, *, role, variant=None) -> AttemptEvidence`
  - Run one `GymCase` as either `baseline` or `candidate`.
  - Return one `Attempt` with a `Score`, plus one `Trace` with structured
    evidence.
- `propose_improvement(exercise, diagnosis) -> CandidateImprovement`
  - Convert a critic diagnosis into one bounded candidate improvement.
- `apply_variant(improvement) -> HarnessVariant`
  - Apply or describe the isolated candidate variant that will be used for
    candidate attempts.

## Minimal Host Integration

For agents that already have a callable task runner, use
`CallableAgentHarnessAdapter`:

```python
from core.gym import (
    CallableAgentHarnessAdapter,
    GenericCaseResult,
    run_promotion_gate_episode,
    validate_agent_harness_adapter,
)

def run_case(case, role, variant):
    result = my_agent_runtime.run(prompt=case.prompt, variant=variant)
    return GenericCaseResult(
        success=result.ok,
        quality=result.quality,
        validation={"passed": result.validation_passed},
        events=result.events,
        artifacts=result.artifacts,
        reason=result.reason,
    )

adapter = CallableAgentHarnessAdapter(
    agent_version_label="my-agent-v1",
    run_case_fn=run_case,
)

validate_agent_harness_adapter(adapter).raise_for_errors()
decision = run_promotion_gate_episode(adapter=adapter)
```

Use `validate_agent_harness_adapter(adapter)` before a full run when bringing up
a new host. It checks that the adapter returns matching Attempt, Trace, Score,
CandidateImprovement, and HarnessVariant records, and reports concrete schema
errors without launching a full evolution episode.

## Score Semantics

- `success`: whether the case met its required outcome.
- `quality`: task quality on a 0.0 to 1.0 style scale.
- `cost`: host-defined execution cost, such as tool calls or tokens.
- `latency`: elapsed seconds.
- `validation`: structured verifier results.
- `tool_errors`: count of failed host/tool calls.
- `regression_risk`: risk introduced by the candidate.
- `safety_risk`: safety or boundary risk observed during the attempt.

Promotion is tier-aware. The mixed promotion gate includes foundation,
coordination, and intelligence cases; a higher-level gain must not bypass core
stability evidence.

## Promotion Application

Gym v1 still writes promotion proposals before changing baseline behavior. The
next explicit step is to apply a proposal in record-only mode:

```bash
python -m core.gym --apply-proposal workspace/gym/promotion_proposals/<proposal>.json --approved-by operator
```

The apply step verifies that the proposal is still proposed, its Decision
Record is a `PROMOTE`, and the episode trace index exists. It then marks the
proposal as `applied` and appends `workspace/gym/applied_promotions.jsonl`.
It does not rewrite baseline code or prompts yet.

Applied proposals can be explicitly rolled back in the same record-only lane:

```bash
python -m core.gym --rollback-proposal workspace/gym/promotion_proposals/<proposal>.json --rolled-back-by operator --rollback-reason "manual review"
```

Rollback requires an `applied` proposal, verifies the same decision and trace
evidence, marks the proposal as `rolled_back`, and appends
`workspace/gym/rolled_back_promotions.jsonl`.

An applied proposal can also be activated as the current advisory baseline
candidate for its target:

```bash
python -m core.gym --activate-proposal workspace/gym/promotion_proposals/<proposal>.json --activated-by operator
```

Activation writes `workspace/gym/active_promotions.json` and appends
`workspace/gym/activation_history.jsonl`. The registry records
`runtime_effect: not_applied` and `agent_consumption: advisory`: an active
proposal is visible to Vibelution as a learning signal, but it has not rewritten
runtime code or prompts. Activating a newer proposal for the same target marks
the previous active proposal as `superseded`.

## Vibelution Host

Vibelution uses `VibelutionAgentHarnessAdapter`, which maps Gym cases onto
`scripts/evolution_harness.py`. Other agents should not depend on that adapter
unless they intentionally share Vibelution's harness.
