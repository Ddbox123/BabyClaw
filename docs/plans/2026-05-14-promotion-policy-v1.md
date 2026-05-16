# Vibelution Promotion Policy v1

## Goal

This policy defines how Vibelution should decide whether a candidate mutation is:

- promoted
- held for further review
- rejected
- rolled back

This is the decision layer that sits on top of the evaluation metrics.

## Decision States

Only four final states should exist in v1.

### 1. `PROMOTE`

Meaning:

- the candidate mutation becomes the new accepted baseline

Use when:

- primary metrics clearly improve
- safety does not regress
- complexity cost remains acceptable
- results are stable enough to trust

### 2. `HOLD`

Meaning:

- do not promote yet
- keep the candidate in an observation pool for more evidence

Use when:

- gains exist but are weak
- complexity cost is questionable
- gains appear narrow
- variance is too high for confidence

### 3. `REJECT`

Meaning:

- do not retain the mutation
- the mutation is not harmful enough to trigger emergency rollback, but it is not worth promotion

Use when:

- primary metrics do not improve
- gains are too small for the cost
- improvements appear too narrow or noisy

### 4. `ROLLBACK`

Meaning:

- immediately revert or discard the mutation
- treat the mutation as dangerous or structurally unacceptable

Use when:

- safety gates fail
- catastrophic failures increase
- restart survival declines materially
- environment contamination occurs
- mutation scope violates governance

## Decision Pipeline

The policy should use four gates.

## Gate 0: Legality Gate

Ask:

- did the mutation stay within allowed boundaries?
- did it respect transaction, validation, and audit rules?
- did it avoid unauthorized modification?

If the answer is no:

- return `ROLLBACK`

This gate does not discuss performance. It only checks lawful evolution behavior.

## Gate 1: Safety Gate

Ask:

- did `validation_failure_rate` get worse?
- did `catastrophic_failure_rate` rise?
- did `restart_survival_rate` drop?
- did the run damage structure, continuity, or environment stability?

If yes:

- return `ROLLBACK`

Unsafe evolution never proceeds to benefit analysis.

## Gate 2: Survival Gate

Ask:

- did `success_rate` improve?
- did `valid_completion_rate` improve?
- was the improvement achieved under comparable resource budgets?

If primary survival gets worse:

- return `REJECT`

If survival is flat:

- inspect cost and complexity
- in rare cases allow `HOLD`

## Gate 3: Cost Gate

Ask:

- did tool calls surge?
- did turn count surge?
- did runtime surge?
- did new modules, state, or prompt rules grow too much?

If benefit is clear and cost acceptable:

- return `PROMOTE`

If benefit exists but confidence or cost is questionable:

- return `HOLD`

If benefit is tiny and cost is large:

- return `REJECT`

## Decision Matrix

| Condition | Decision |
|---|---|
| Unauthorized mutation / broken audit / environment contamination | `ROLLBACK` |
| Safety metrics regress | `ROLLBACK` |
| Primary metrics regress | `REJECT` |
| Primary metrics flat, cost worse, complexity worse | `REJECT` |
| Primary metrics slightly improve, but complexity or variance is high | `HOLD` |
| Primary metrics clearly improve, safety stable, complexity acceptable | `PROMOTE` |

## Suggested Thresholds

V1 should use conservative thresholds.

### `PROMOTE`

Require all of:

1. `success_rate_delta > +0.05`
2. `validation_failure_rate_delta <= 0`
3. `catastrophic_failure_rate_delta <= 0`
4. `restart_survival_rate_delta >= 0`
5. `complexity_penalty <= budget`
6. repeated runs show the same directional improvement

### `HOLD`

Use when any of the following is true:

1. `0 < success_rate_delta <= 0.05`
2. primary metrics improve but efficiency degrades noticeably
3. primary metrics improve but complexity cost is high
4. gains appear only in one task family

### `REJECT`

Use when any of the following is true:

1. `success_rate_delta <= 0`
2. `valid_completion_rate_delta <= 0` without compensating benefit
3. complexity rises sharply with near-no gain
4. repeated runs are too noisy to justify retention

### `ROLLBACK`

Use when any of the following is true:

1. safety gate failed
2. catastrophic failure rate increased
3. restart survival materially declined
4. environment contamination occurred
5. core mutation governance was violated

## Observation Pool Policy

`HOLD` candidates should enter an observation pool instead of disappearing.

Suggested pool:

- `candidate_observation_pool`

Each entry should track:

- candidate id
- mutation summary
- initial benchmark results
- unresolved concerns
- required follow-up environment set
- expiration or recheck deadline

This prevents:

1. prematurely discarding potentially useful adaptations
2. prematurely promoting immature structures

## Rollback Policy

Rollback should be an explicit governed action, not just an ad hoc Git move.

Each rollback record should include:

- `candidate_id`
- `rollback_reason`
- `trigger_gate`
- `affected_paths`
- `failure_summary`
- `repeatable_failure_pattern`
- `do_not_retry_until`

### `repeatable_failure_pattern`

This should compress the failure into reusable learning, for example:

- terminal-task wrapper expansion increased latency and caused timeout growth
- dynamic-state expansion improved one run but lowered restart continuity

### `do_not_retry_until`

This prevents the system from immediately rediscovering the same bad mutation class.

## Baseline Update Policy

When a candidate is promoted:

1. mark it as the new accepted baseline
2. store baseline id and lineage
3. store its recent benchmark results
4. store its complexity profile

Without this, future improvement claims become ambiguous.

## Anti-False-Promotion Safeguards

### 1. No promotion from a single lucky run

Rule:

- one good run is not enough

### 2. No promotion from one isolated case

Rule:

- local wins without bundle-level strength are not enough

### 3. Prompt or module bloat lowers confidence

Rule:

- gains purchased with excessive structural growth default to `HOLD`

### 4. Safety regressions override reward

Rule:

- if safety regresses, do not argue from success gains

## Minimal Pseudocode

```python
def decide_promotion(candidate, baseline):
    if not candidate.is_legal:
        return "ROLLBACK", "illegal mutation scope"

    if candidate.safety_regressed:
        return "ROLLBACK", "safety regression"

    if candidate.success_rate < baseline.success_rate:
        return "REJECT", "primary survival regressed"

    if candidate.success_rate == baseline.success_rate:
        if candidate.efficiency_worse and candidate.complexity_higher:
            return "REJECT", "no gain, higher cost"
        return "HOLD", "no clear gain yet"

    if candidate.success_rate > baseline.success_rate:
        if candidate.complexity_too_high or candidate.result_variance_too_high:
            return "HOLD", "gain exists but needs more validation"
        return "PROMOTE", "clear gain without safety regression"
```

## Final Principle

This policy exists to enforce one idea:

`not every change is evolution; only changes that survive selective pressure deserve retention.`
