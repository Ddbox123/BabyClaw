## Problem Statement

Vibelution currently has early **Self-Evolution** and **Supervised Evolution** machinery, including **Datasets**, **Bundles**, **Cases**, **Decision Records**, **Lineage**, and a **Selection Policy**. This proves that candidate behavior can be compared against baseline behavior, but the system is still mainly task-triggered and human-directed.

The next step is an embeddable task-driven **Evolution Engine** with a **Gym**: Vibelution should improve by repeatedly doing known and generated **Cases**, scoring each **Attempt**, diagnosing which **Harness Gap** limited performance, proposing one focused **Candidate Improvement**, applying it to an isolated **Harness Variant**, and accepting it only when evaluation shows measurable gain without unacceptable regression.

This is not a tool-generation-only feature. New **Tools** are one possible outcome, but the broader goal is to improve the entire Agent harness: planning, context management, Tool routing, validation strategy, memory policy, recovery behavior, Workbench flows, and promotion policy.

The engine should be reusable outside Vibelution. Vibelution is the first host Agent, but the core evolution loop must depend on an **Agent Harness Adapter** boundary rather than `agent.py`, Workbench, or Vibelution-specific process details.

The requirement has one important v1 safety boundary: Gym v1 may produce auditable promotion proposals, but it must not automatically rewrite baseline behavior. This decision is recorded in [ADR 0001](../adr/0001-gym-v1-uses-promotion-proposals-before-baseline-rewrite.md).

## Solution

Build an embeddable task-driven Agent Evolution Engine that turns an Agent's growth into a measurable closed loop:

1. Select an **Exercise** from a **Gym**.
2. Materialize one or more **Cases** from registered **Datasets**, **Dataset Adapters**, or generated-case sources.
3. Run the current Agent harness against each **Case**, producing one Case-level **Attempt** and one **Trace** per Attempt.
4. Persist Tool Calls, observations, errors, validation results, artifacts, and multi-dimensional **Scores**.
5. Use a **Critic** to diagnose the dominant **Harness Gap** from Trace evidence.
6. Use an **Evolver** to propose exactly one bounded **Candidate Improvement** with an expected effect.
7. Apply that proposal to an isolated **Harness Variant** for candidate Attempts.
8. Compare baseline and candidate **Evaluation Runs** across dev, holdout, smoke, and regression **Dataset Splits**.
9. Route the **Improvement Episode** through **Selection Policy**.
10. Persist a **Decision Record**; in v1, PROMOTE writes a promotion proposal rather than automatically rewriting baseline behavior.

The product outcome is an Agent-centered training loop. Vibelution is not waiting for a user to request improvements; it is exercising against a gym, measuring itself, and retaining only improvements that survive selection pressure. Other Agents should be able to host the same loop by providing their own Agent Harness Adapter.

## Domain Boundaries

- **Gym** is the training environment that organizes **Exercises**. It is not a **Dataset**, **Bundle**, or **Supervised Evolution** mode.
- **Evolution Engine** is the host-agnostic orchestration layer for Improvement Episodes. It must not depend on `agent.py` or Workbench.
- **Agent Harness Adapter** is the host-specific integration boundary. It runs Attempts, applies Harness Variants, and returns Traces/Scores for a concrete Agent.
- **Training Tier** is the training purpose of an Exercise or Case: foundation, coordination, or intelligence.
- **Exercise** is the training objective. A **Case** is the runnable and scoreable scenario created from that objective.
- **Attempt** is Case-level: one Agent version or **Harness Variant** trying one **Case**.
- **Evaluation Run** is Bundle-level: the aggregation of Attempts and Scores across a **Bundle**.
- **Improvement Episode** is the main evolution unit: Exercise, baseline Attempts, diagnosis, Candidate Improvement, Harness Variant, candidate Attempts, evaluation, and Selection Policy decision.
- **Candidate Improvement** is a proposed change. **Harness Variant** is the isolated runtime with that proposed change applied.
- **Trace** is structured evidence, not a generic log.
- **Score** is multi-dimensional; it must not collapse success, quality, cost, validation, regression, and safety into one blind metric.
- **Critic** diagnoses Harness Gaps from Traces; it does not apply changes.
- **Evolver** proposes one Candidate Improvement; it does not promote changes.
- **Selection Policy** is the only promotion authority.
- **Decision Record** records the selection result for an Improvement Episode.
- **Lineage** tracks accepted Candidate Improvements that become baseline behavior across Improvement Episodes.
- **Dataset Adapter** converts each Dataset format into Vibelution Cases; Workbench and `agent.py` must not hardcode individual dataset formats.
- **Dataset Split** declares evaluation use: train, dev, observe, regression, or holdout.
- **Generated Case** must carry provenance and cannot automatically enter holdout.

## Training Tiers

Gym training collections should be organized by Training Tier, because not every exercise trains the same thing:

- **foundation** protects core Agent stability. These Cases verify task boundaries, file reading, safe edits, validation, transaction closure, recovery basics, no unrelated changes, no unsafe restart, and no uncontrolled delegation. Foundation Cases are the primary smoke and regression gates.
- **coordination** improves cooperation between Agent subsystems. These Cases exercise planning plus Tool routing, context management plus validation, memory plus current task state, recovery after partial failure, delegation coordination, and Workbench/CLI/harness flows.
- **intelligence** improves higher-order capability. These Cases exercise complex decomposition, long-context judgment, self-correction, Trace diagnosis, Candidate Improvement quality, strategic no-change decisions, generated Case design, and cross-task generalization.

Promotion must be tier-aware. A Candidate Improvement that improves coordination or intelligence but regresses foundation must be rejected. Coordination regressions should normally force HOLD or REJECT unless the Selection Policy has explicit evidence that the regression is acceptable. Intelligence gains are not enough by themselves to bypass foundation, holdout, regression, or safety gates.

## User Stories

1. As Vibelution, I want a named Gym that contains task-driven Exercises, so that my growth is shaped by repeatable external pressure.
2. As Vibelution, I want each Case to declare objective, setup, allowed tools, scoring rules, and validation commands, so that I can attempt it without hidden human judgment.
3. As Vibelution, I want to materialize Gym Cases into Bundles, so that existing Supervised Evolution workflows can run them.
4. As Vibelution, I want to run baseline Attempts against individual Cases and aggregate them into an Evaluation Run, so that I know my current capability before proposing changes.
5. As Vibelution, I want to record each Case-level Attempt as structured Trace data, so that later diagnosis can inspect what actually happened.
6. As Vibelution, I want Tool Calls, command failures, retries, file reads, edits, tests, and final outcomes to be part of the Attempt trace, so that failures can be attributed to harness behavior rather than vague model weakness.
7. As Vibelution, I want Attempt scoring to include success, steps, elapsed time, Tool errors, validation coverage, regression count, and artifact quality, so that improvement is multi-dimensional.
8. As Vibelution, I want a Critic to classify failures by harness gap, so that I can distinguish planning problems from context, Tool routing, validation, memory, and recovery problems.
9. As Vibelution, I want the Critic to produce evidence-backed diagnoses, so that proposed improvements are grounded in trace facts.
10. As Vibelution, I want the Critic to identify repeated inefficient behavior, so that evolution can improve speed and reliability even when Cases eventually pass.
11. As Vibelution, I want an Evolver to propose one focused improvement at a time, so that A/B evaluation can attribute changes to a specific cause.
12. As Vibelution, I want improvement types to include policy patch, context patch, memory patch, Tool patch, verifier patch, scheduler patch, Workbench flow patch, and prompt patch, so that evolution is not reduced to creating new Tools.
13. As Vibelution, I want every proposed improvement to include an expected effect, so that evaluation can falsify it.
14. As Vibelution, I want candidate improvements to run in an isolated evolution transaction, so that unsafe changes cannot silently become part of the baseline.
15. As Vibelution, I want the Evaluator to compare baseline and candidate on development Bundles, so that local gains are measured before broader promotion.
16. As Vibelution, I want the Evaluator to compare baseline and candidate on holdout Bundles, so that overfitting to the current Case is detected.
17. As Vibelution, I want the Evaluator to run regression Bundles for core behavior, so that growth does not damage basic Agent safety or runtime stability.
18. As Vibelution, I want the Selection Policy to decide promote, hold, observe, or reject, so that evolution decisions are consistent and auditable.
19. As Vibelution, I want promoted improvements to update Lineage only through Selection Policy, so that future generations know which baseline they descend from.
20. As Vibelution, I want rejected improvements to be stored with their failure reason, so that I avoid rediscovering the same dead end.
21. As Vibelution, I want held improvements to enter an observation pool, so that promising but uncertain changes can be revisited.
22. As Vibelution, I want the Gym to support fixed benchmark Cases, so that progress can be compared across Agent versions.
23. As Vibelution, I want the Gym to support generated Cases, so that I can create new training pressure from observed weaknesses.
24. As Vibelution, I want generated Cases to carry provenance, so that synthetic exercise growth remains auditable.
25. As Vibelution, I want Case tags for planning, context management, Tool routing, validation, memory, recovery, Workbench, and codebase navigation, so that performance can be tracked by capability.
26. As Vibelution, I want score dashboards by capability tag, so that the next improvement target is chosen from evidence.
27. As Vibelution, I want the Workbench to expose Gym runs, recent Attempts, Decision Records, and Lineage summaries, so that operators can inspect the evolution loop without memorizing flags.
28. As Vibelution, I want the Workbench to recover from blocked Datasets and invalid setup, so that Gym operation does not collapse on incomplete sources.
29. As Vibelution, I want the Gym to ingest public task environments such as AgentGym-style trajectories, so that growth can start from existing research assets.
30. As Vibelution, I want external trajectories to be normalized into local Cases and Attempts, so that imported data speaks Vibelution's domain language.
31. As Vibelution, I want imported traces to be marked as reference behavior rather than automatically accepted Agent behavior, so that external data does not bypass local evaluation.
32. As Vibelution, I want Reflexion-style reflection records from failed Attempts, so that language-level lessons can improve future behavior without immediate code changes.
33. As Vibelution, I want Voyager-style reusable skills to be extracted only after repeated success, so that the skill library stays useful rather than noisy.
34. As Vibelution, I want ACE-style context curation, so that Core Prompt, Dynamic Prompt, and State Memory improve without collapsing into vague summaries.
35. As Vibelution, I want Tool-Genesis-style checks when a new Tool is proposed, so that Tool schema, unit behavior, and downstream task value are evaluated separately.
36. As Vibelution, I want AgentEvolver-style self-questioning to create variants of failed Cases, so that one weakness becomes a family of exercises.
37. As Vibelution, I want every accepted improvement to include a compact post-mortem, so that future Critic decisions learn from selection outcomes.
38. As Vibelution, I want every evolution episode to be replayable, so that regressions can be reproduced.
39. As Vibelution, I want cost and runtime to be part of scoring, so that evolution favors effective and efficient harness behavior.
40. As Vibelution, I want safety constraints to be part of scoring, so that risky shortcuts cannot be mistaken for capability gains.
41. As Vibelution, I want an improvement to be rejected if it improves one tag but causes unacceptable regression on core tags, so that growth remains balanced.
42. As Vibelution, I want the Gym to support small smoke Bundles, so that harness changes can be checked quickly.
43. As Vibelution, I want the Gym to support larger scheduled evaluation Bundles, so that slower but deeper progress checks can run outside interactive work.
44. As Vibelution, I want evolution artifacts to live in the Workspace, so that runtime data remains separate from stable Core behavior.
45. As Vibelution, I want reusable evolution logic to live in Core modules, so that Workbench and CLI surfaces remain thin.
46. As Vibelution, I want issue-ready PRDs and plans to be produced from accepted research, so that large evolution work can be split into agent-executable implementation slices.
47. As Vibelution, I want the Gym to avoid direct dependence on a single public benchmark, so that the evolution loop remains useful even if one source is unavailable.
48. As Vibelution, I want public research sources to be tracked as provenance, so that future maintainers know why each mechanism exists.
49. As Vibelution, I want the first version to work with local Bundles before external environments, so that the loop becomes reliable before integrations expand.
50. As Vibelution, I want every module boundary to be testable in isolation, so that harness evolution does not create a fragile monolith.
51. As Vibelution, I want Datasets to be extensible through Dataset Adapters, so that new local, public, generated, and imported sources can be added without changing Workbench or `agent.py`.
52. As Vibelution, I want every Case to declare Dataset Splits, so that training, observation, development, regression, and holdout evidence are not confused.
53. As Vibelution, I want Generated Case provenance to include source trace, source episode, source harness gap, generation reason, creator version, creation time, and allowed splits, so that future training pressure remains explainable.
54. As Vibelution, I want observe split evidence to be retained without triggering promotion by itself, so that uncertain signals can mature without becoming false proof.
55. As Vibelution, I want v1 PROMOTE outcomes to create promotion proposals rather than automatically rewriting baseline behavior, so that the first loop is auditable and recoverable.
56. As an Agent host, I want to plug my own Agent runtime into the Evolution Engine through an Agent Harness Adapter, so that the engine can train Agents other than Vibelution.
57. As an Agent host, I want the Evolution Engine core to avoid importing Workbench, `agent.py`, or Vibelution-specific process code, so that embedding remains clean.
58. As Vibelution, I want Vibelution-specific execution to live in a Vibelution adapter, so that the generic engine stays reusable.
59. As Vibelution, I want Gym Exercises and Cases to declare a Training Tier, so that training pressure can distinguish stability, coordination, and intelligence goals.
60. As Vibelution, I want foundation Cases to gate every promotion, so that higher-level gains cannot damage core Agent stability.
61. As Vibelution, I want coordination Cases to measure subsystem cooperation, so that planning, context, Tool routing, validation, memory, recovery, delegation, and runtime flows improve together.
62. As Vibelution, I want intelligence Cases to measure strategic capability, so that evolution can improve diagnosis, abstraction, self-correction, generated Case quality, and generalization.

## Implementation Decisions

- Build the feature around a task-driven evolution loop rather than a tool-generation loop. Tool creation is a supported improvement type, not the main abstraction.
- Treat the primary data unit as an **Improvement Episode**: Exercise, baseline Attempts, diagnosis, Candidate Improvement, Harness Variant, candidate Attempts, Evaluation Runs, and Selection Policy decision.
- Preserve and use the vocabulary in `CONTEXT.md`, especially Gym, Exercise, Dataset, Dataset Adapter, Dataset Split, Bundle, Case, Generated Case, Attempt, Evaluation Run, Trace, Score, Harness Gap, Critic, Evolver, Candidate Improvement, Harness Variant, Decision Record, Lineage, Selection Policy, Workbench, State Memory, and Workspace.
- Add a Gym module that owns Case selection, generated Case registration, Case tags, and Bundle creation for evolution exercises.
- Add an Evolution Engine module that owns host-agnostic Improvement Episode orchestration.
- Add an Agent Harness Adapter protocol that hosts implement to run Attempts, apply Harness Variants, expose agent version, and return Trace/Score evidence.
- Add Training Tier metadata to Exercises, Cases, Attempts, Scores, Evaluation Runs, and Selection Policy summaries where applicable.
- Use foundation, coordination, and intelligence as the stable tier identifiers.
- Treat foundation tier regression as a promotion blocker even when coordination or intelligence improves.
- Add an Attempt Runner module that executes individual Cases against a specific Agent version or Harness Variant and emits structured Attempt records.
- Add an Evaluation Runner or aggregation layer that groups Attempt records into Bundle-level Evaluation Runs.
- Add a Trace Store module that persists Tool Calls, observations, errors, validation outputs, score components, and artifacts in a queryable form.
- Add a Critic module that reads Attempt traces and classifies harness gaps using a fixed taxonomy: planning, context management, Tool routing, validation, memory, recovery, Workbench flow, execution environment, and safety policy.
- Add an Evolver module that proposes one bounded improvement from a Critic diagnosis. It should emit an improvement spec before any code or prompt mutation is applied.
- Add an Evaluator module that compares baseline and candidate behavior on development, holdout, smoke, and regression Bundles.
- Extend the Selection Policy so that it can evaluate full harness improvements, not only candidate behavior on a single supervised run.
- In v1, Selection Policy PROMOTE writes an auditable promotion proposal; it must not automatically rewrite baseline behavior.
- Keep Workbench as a thin shell. It should ask deeper evolution modules for available Gyms, Bundles, Attempts, Decision Records, and Lineage summaries.
- Keep `agent.py` as runtime glue. It must not hardcode Gym or Dataset-format logic.
- Keep Vibelution-specific harness execution behind a Vibelution Agent Harness Adapter. The generic Evolution Engine must not import `agent.py`, Workbench, or scripts directly.
- Route all Dataset expansion through Dataset Registry and Dataset Adapters.
- Generated Cases must be stored through a registered generated Dataset source and must include provenance: source trace, source episode, source harness gap, generation reason, creator version, creation time, and allowed splits.
- Dataset Splits must be first-class metadata on Cases and Scores. Selection Policy must interpret Scores in relation to split.
- Training Tier must be first-class metadata on Cases and Scores. Selection Policy must interpret Scores in relation to tier.
- Generated Cases can enter train or observe by default, but must never automatically enter holdout.
- Observe split evidence can support further investigation, but cannot trigger promotion without dev, holdout, or regression support.
- Gym v1 should prove the full loop using a small local transaction-closing Exercise, while keeping Dataset and adapter boundaries open for later expansion.
- Gym v1 should begin with low-risk improvement types such as prompt_patch, policy_patch, verifier_patch, or small workbench_patch. Broader Tool, scheduler, memory, and harness code changes can follow once trace and evaluation machinery is reliable.
- Treat imported public research data as seed material. AgentGym-like traces can become Cases and reference traces, but local acceptance must still require Vibelution evaluation.
- Use AgentGym as the design reference for multi-environment exercise structure and trajectory capture.
- Use Voyager as the design reference for reusable skill extraction and long-term capability accumulation.
- Use Reflexion as the design reference for failed Attempt reflection records that can improve future behavior without immediate code mutation.
- Use AgentEvolver as the design reference for self-generated exercises and credit assignment across long traces.
- Use Tool-Genesis as the design reference for evaluating generated Tools across interface correctness, functional correctness, and downstream usefulness.
- Use ACE as the design reference for context and playbook evolution with curation, anti-collapse checks, and provenance.
- The core improvement episode schema should be stable enough to support future training. A decision-rich shape is:

```json
{
  "exercise": {
    "case_id": "string",
    "bundle_name": "string",
    "capability_tags": ["planning", "validation"],
    "success_metric": "string"
  },
  "baseline_attempt": {
    "agent_version": "string",
    "case_id": "string",
    "score": {
      "success": "boolean",
      "quality": "number",
      "cost": "number",
      "latency": "number",
      "validation": {},
      "regression_risk": "number",
      "safety_risk": "number"
    },
    "trace_id": "string"
  },
  "diagnosis": {
    "harness_gap": "planning | context | tool_routing | validation | memory | recovery | workbench | environment | safety",
    "evidence": ["string"]
  },
  "improvement": {
    "type": "policy_patch | context_patch | memory_patch | tool_patch | verifier_patch | scheduler_patch | workbench_patch | prompt_patch",
    "expected_effect": "string",
    "promotion_mode": "proposal_only"
  },
  "harness_variant": {
    "variant_id": "string",
    "applied_improvement_id": "string"
  },
  "candidate_attempt": {
    "agent_version": "string",
    "case_id": "string",
    "score": {},
    "trace_id": "string"
  },
  "evaluation_runs": {
    "dev": "evaluation_run_id",
    "holdout": "evaluation_run_id",
    "regression": "evaluation_run_id"
  },
  "selection": {
    "decision": "PROMOTE | HOLD | OBSERVE | REJECT",
    "reason": "string",
    "action": "write_promotion_proposal | observe | reject"
  }
}
```

- The first release should prefer local, deterministic Cases and Bundles over heavy external environments. External integrations can follow once the loop is reliable.
- Generated Cases must never automatically count as holdout evaluation. Holdout Bundles should be stable and versioned.
- In v1, promoted improvements should write auditable promotion proposals and Decision Records. Automatic baseline rewrite is out of scope until replay, rollback, holdout, and regression evidence are stronger.
- Rejected, held, and observed improvements should also be retained as learning artifacts.

## Testing Decisions

- Tests should verify observable evolution behavior rather than private implementation details.
- Gym tests should verify that Cases can be selected, tagged, and materialized into Bundles with stable metadata.
- Training Tier tests should verify that foundation, coordination, and intelligence metadata survives Exercise creation, Case materialization, Bundle materialization, Attempt recording, and Evaluation Run aggregation.
- Selection Policy tier tests should verify that foundation regression blocks promotion even when higher tiers improve.
- Evolution Engine tests should verify that a fake Agent Harness Adapter can run a full proposal-only episode without importing Vibelution-specific runtime modules.
- Agent Harness Adapter contract tests should verify that host implementations return Attempt, Trace, and Score evidence in the generic schema.
- Dataset Adapter tests should verify that registry entries can materialize local, generated, and fixture-backed sources into Cases without Workbench or `agent.py` format knowledge.
- Dataset Split tests should verify that train, dev, observe, regression, and holdout metadata is preserved through Bundle materialization and Score aggregation.
- Generated Case tests should verify provenance fields and reject automatic holdout assignment.
- Attempt Runner tests should verify that a Case run produces one Attempt record with score, trace identifier, and validation artifacts.
- Evaluation Run tests should verify Bundle-level aggregation across Case-level Attempts.
- Trace Store tests should verify round-trip persistence and filtering by Case, Bundle, Agent version, capability tag, and decision.
- Critic tests should use small synthetic traces to verify that common failure patterns map to the expected harness gap taxonomy.
- Evolver tests should verify that a diagnosis produces exactly one bounded improvement spec with an expected effect and target module type.
- Evaluator tests should verify baseline-versus-candidate scoring, holdout regression detection, and cost-aware comparison.
- Selection Policy tests should verify promote, hold, observe, and reject decisions for multi-metric improvement episodes, including split-aware scoring.
- Selection Policy v1 tests should verify PROMOTE writes a promotion proposal and does not automatically rewrite baseline behavior.
- Workbench tests should verify external behavior: listing Gyms, selecting Bundles, running evaluation, recovering from blocked setup, showing recent Decision Records, and showing Lineage summaries.
- Regression tests should reuse prior supervised-evolution tests as precedent: persist Decision Records, update Lineage, reject regressions, hold uncertain improvements, and promote only when gates pass.
- Public data ingestion tests should use tiny fixtures, not live downloads, so that test runs remain deterministic.
- End-to-end smoke tests should run a minimal local Gym Bundle and assert that a complete improvement episode can be recorded without requiring a real harness mutation.

## Out of Scope

- Training or fine-tuning a model's weights is out of scope for the first release.
- Full SWE-bench harness integration is out of scope for the first release.
- Browser, Minecraft, WebShop, or other heavy external environments are out of scope for the first release.
- Autonomous unbounded self-modification is out of scope. All candidate improvements must pass explicit evaluation and Selection Policy gates.
- Automatic baseline rewrite is out of scope for Gym v1; v1 promotion writes an auditable proposal.
- Broad Tool, scheduler, memory, and harness code mutation is out of scope for the first Gym slice unless implemented behind low-risk proposal-only evaluation.
- Replacing existing Supervised Evolution is out of scope. The Gym should build on it and generalize it.
- Building a public benchmark service is out of scope.
- Automatically trusting public trajectories as accepted Vibelution behavior is out of scope.
- Optimizing for a single score while ignoring safety, cost, and regression is out of scope.
- Requiring all host Agents to use Vibelution's Workbench, `agent.py`, or process model is out of scope; integration must happen through adapters.

## Further Notes

- The research synthesis suggests using AgentGym for exercise and trajectory concepts, Voyager for reusable skill accumulation, Reflexion for language-level learning from failed Attempts, AgentEvolver for self-generated training pressure, Tool-Genesis for Tool creation evaluation, and ACE for context/playbook evolution.
- The first milestone should prove a local closed loop with a small transaction-closing Gym Exercise, Case-level Attempts, Traces, Scores, a proposal-only Decision Record, and a fake embeddable Agent Harness Adapter.
- The second milestone should add Training Tiers, Dataset Adapter extensibility, Dataset Splits, Generated Case provenance, and observe split handling.
- The third milestone should add Critic-driven improvement specs, isolated Harness Variants, and multi-metric Evaluation Runs.
- The fourth milestone should introduce generated Cases and observation pools.
- The fifth milestone should import selected public trajectory data into local Case and reference Trace format.
- The long-term goal is measurable task-driven Self-Evolution: Vibelution repeatedly improves its ability to solve task distributions while preserving safety, stability, and core behavior.
