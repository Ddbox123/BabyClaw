# Vibelution Evolution Evaluation Metrics v1

## Goal

This metric system is designed to answer one practical question:

`after a mutation, should the new agent state be retained?`

It is not primarily designed to assign one absolute intelligence score to the agent.

Its purpose is to support stable selection decisions across generations.

## Core Principles

1. Always compare `before evolution` versus `after evolution`.
2. Primary survival metrics come first.
3. Efficiency metrics matter, but only after survival.
4. Safety metrics are hard gates, not soft suggestions.
5. Complexity metrics act as penalties against bloated adaptations.
6. One-off gains are not enough; stability matters.

## Metric Layers

The metrics are grouped into four layers.

### A. Primary Survival Metrics

These answer whether the candidate is actually better at surviving task environments.

#### 1. Task Success Rate

Definition:

- proportion of tasks successfully completed

Formula:

- `success_rate = successful_tasks / total_tasks`

Role:

- main selection metric

#### 2. Valid Completion Rate

Definition:

- proportion of tasks completed in a way that satisfies benchmark or environment rules

Role:

- prevents false wins based on superficial completion

### B. Efficiency Metrics

These prevent success from being purchased through wasteful execution.

#### 3. Average Tool Calls

Definition:

- average number of tool invocations per task

Role:

- measures execution compactness

#### 4. Average Turn Count

Definition:

- average number of cognitive or tool-action turns per task

Role:

- measures convergence efficiency

#### 5. Average Wall-Clock Time

Definition:

- average real execution time per task

Role:

- measures environment-level survival efficiency

#### 6. Retry / Recovery Count

Definition:

- average number of retries, recoveries, or rescue actions per task

Role:

- distinguishes robust success from fragile success

### C. Safety and Stability Metrics

These are hard constraints. They are not mere scoring features.

#### 7. Validation Failure Rate

Definition:

- failed validations divided by total tasks or runs

Includes:

- lint failures
- test gate failures
- environment smoke failures
- benchmark invalid-completion failures

Role:

- hard safety gate

#### 8. Catastrophic Failure Rate

Definition:

- proportion of runs that produce serious failure states

Includes:

- process crash
- restart handoff failure
- critical state corruption
- structural file damage
- unrecoverable environment contamination

Role:

- one-vote veto metric

#### 9. Restart Survival Rate

Definition:

- proportion of restart-requiring tasks that successfully continue after restart

Role:

- especially important for Vibelution because restart continuity is part of the organism

#### 10. Repeated Failure Pattern Rate

Definition:

- rate at which previously known failure patterns reappear

Role:

- measures whether the system is actually learning from prior mistakes

### D. Complexity and Growth Cost Metrics

These defend against fake evolution through system bloat.

#### 11. Files Touched Per Mutation

Definition:

- number of files touched by a single candidate mutation

Role:

- measures mutation scope

#### 12. New Module Count

Definition:

- number of newly added modules

Role:

- detects organ growth through uncontrolled structural expansion

#### 13. New Prompt Rules Count

Definition:

- number of newly added prompt rules or constraints

Role:

- prevents progress through prompt pile-up

#### 14. New Persistent State Keys

Definition:

- number of new long-lived state fields introduced

Role:

- defends against state inflation

#### 15. Cross-Module Dependency Delta

Definition:

- net increase in cross-module dependencies

Role:

- monitors coupling growth

## Metric Roles

Not all metrics have the same function.

### Promotion Metrics

These determine whether the candidate is stronger:

- `Task Success Rate`
- `Valid Completion Rate`

### Efficiency Support Metrics

These determine whether the candidate is more economical:

- `Average Tool Calls`
- `Average Turn Count`
- `Average Wall-Clock Time`

### Veto Metrics

These can directly block promotion:

- `Validation Failure Rate`
- `Catastrophic Failure Rate`
- materially worse `Restart Survival Rate`

### Penalty Metrics

These determine whether gains are worth the cost:

- `Files Touched Per Mutation`
- `New Module Count`
- `New Prompt Rules Count`
- `New Persistent State Keys`
- `Cross-Module Dependency Delta`

## Recommended Selection Logic

Evaluation should not collapse immediately into one number.

Use three steps.

### Step 1: Safety Gate

Reject immediately if:

- catastrophic failures increase
- validation failures materially worsen
- restart survival materially drops
- mutation violates safety boundaries

### Step 2: Survival Comparison

If the candidate:

- improves `success_rate`
or
- holds `success_rate` while improving `valid_completion_rate`

then proceed to cost evaluation.

Otherwise reject.

### Step 3: Cost and Complexity Review

If the candidate improves survival but:

- tool calls surge
- runtime surges
- complexity grows sharply

then downgrade confidence or hold for further review instead of immediate promotion.

## Example Simplified Promotion Formula

This formula is not the final truth. It is only a first operational scoring layer.

```text
promotion_score =
  0.50 * success_rate_delta
+ 0.20 * valid_completion_delta
- 0.10 * tool_call_delta_norm
- 0.10 * time_delta_norm
- 0.10 * complexity_penalty
```

Use the formula only after safety gates pass.

```text
if safety_failed:
    reject
elif promotion_score > threshold:
    promote
else:
    reject_or_hold
```

## Dataset Stratification

To keep evaluation honest, use three sets.

### 1. Selection Set

Purpose:

- primary comparison set for candidate mutations

Properties:

- small
- stable
- repeatable

### 2. Validation Set

Purpose:

- second-pass verification after an apparent gain

Properties:

- somewhat larger
- not used for every small mutation

### 3. Fresh Set

Purpose:

- detect overfitting
- test generalization

Properties:

- periodically refreshed
- not used as the daily inner loop

## Metrics That Should Not Be Misused

### 1. Single-run success

Problem:

- too noisy

### 2. Average score alone

Problem:

- can hide catastrophic failures

### 3. Pass rate without cost

Problem:

- encourages brute-force success

### 4. Internal test performance without external environment performance

Problem:

- proves the system did not break
- does not prove the system became stronger

### 5. External score without complexity accounting

Problem:

- encourages bloated adaptations

## Recommended Minimal Dashboard

For v1, the minimal useful dashboard is:

- `success_rate`
- `valid_completion_rate`
- `avg_tool_calls`
- `avg_wall_clock_time`
- `validation_failure_rate`
- `catastrophic_failure_rate`
- `restart_survival_rate`
- `files_touched_per_mutation`
- `new_prompt_rules_count`
- `new_module_count`

## Minimal Retention Policy Inputs

The evaluation system should be able to support these decisions:

### Retain

When:

1. safety gates pass
2. `success_rate` improves above a small threshold
3. `validation_failure_rate` does not worsen
4. `catastrophic_failure_rate` does not worsen
5. complexity penalties stay within budget

### Hold

When:

1. gains are small
2. cost has grown
3. evidence is narrow or unstable

### Reject

When:

1. primary survival declines
2. safety worsens
3. complexity rises without enough benefit
4. gains appear only in a tiny corner of the environment

## Final Principle

The job of the evaluation system is not to prove how intelligent the agent is.

Its real job is:

`to reliably distinguish which mutations deserve to survive.`
