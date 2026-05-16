# Vibelution Context

This context defines the domain language for Vibelution so architecture work can use stable names for the same concepts. It is intentionally small: add terms when they become load-bearing in design or tests.

## Language

### Agent Runtime

**Vibelution**:
A self-evolving AI Agent system that can inspect, change, validate, and restart its own project.
_Avoid_: App, bot, assistant

**Agent**:
The runtime persona that receives a goal, builds context, calls the LLM, chooses tools, and produces user-facing output.
_Avoid_: Bot, model, executor

**Turn**:
One goal-processing cycle in which the **Agent** builds messages, invokes the LLM, processes tool calls, and reports an outcome.
_Avoid_: Loop, request, iteration

**Tool**:
A callable capability exposed to the **Agent** for reading, modifying, searching, validating, or controlling the project.
_Avoid_: Command, function, action

**Tool Call**:
A single invocation of a **Tool** with concrete arguments and a recorded result.
_Avoid_: Command run, operation

**Workbench**:
The terminal shell that lets a user enter major Vibelution modes without remembering command-line flags.
_Avoid_: Menu, launcher

### Evolution

**Self-Evolution**:
The capability for Vibelution to change its own code or prompts and validate the change before continuing.
_Avoid_: Auto-update, self-modification

**Supervised Evolution**:
A controlled evaluation workflow that compares baseline and candidate behavior on known cases before deciding whether a change should advance.
_Avoid_: Benchmark run, eval mode

**Gym**:
A training environment that organizes exercises for Vibelution's task-driven self-improvement.
_Avoid_: Dataset, benchmark, evaluation mode

**Training Tier**:
The intended training purpose of a **Gym** **Exercise** or **Case**: foundation, coordination, or intelligence.
_Avoid_: Difficulty score, priority, tag

**Evolution Engine**:
The embeddable orchestration layer that runs **Improvement Episodes** against an **Agent Harness Adapter** without depending on Vibelution-specific entry points.
_Avoid_: Workbench, agent.py, Gym

**Agent Harness Adapter**:
A host-provided boundary that lets the **Evolution Engine** run **Attempts**, apply **Harness Variants**, and collect **Traces** for a specific Agent implementation.
_Avoid_: Agent, Tool, Workbench

**Dataset**:
A named source that can be materialized into **Cases**.
_Avoid_: Corpus, source file

**Dataset Adapter**:
A normalizer that converts a specific **Dataset** format into Vibelution **Cases**.
_Avoid_: Dataset, parser, importer

**Dataset Split**:
The intended evaluation use of a **Case** within a **Dataset**, such as train, dev, observe, regression, or holdout.
_Avoid_: Tag, folder, benchmark

**Exercise**:
A training objective from a **Gym** that can be materialized into one or more **Cases**.
_Avoid_: Case, task, prompt

**Bundle**:
A runnable collection of supervised-evolution cases with shared benchmark metadata.
_Avoid_: Suite, test set

**Case**:
A runnable and scoreable training scenario with the objective, inputs, constraints, validation, and scoring basis needed for an **Attempt**.
_Avoid_: Example, sample, task

**Generated Case**:
A **Case** created from prior **Trace**, **Harness Gap**, or **Improvement Episode** evidence to increase training pressure.
_Avoid_: Holdout case, accepted behavior, benchmark

**Attempt**:
One try by a specific Agent version or harness variant to solve one **Case**.
_Avoid_: Run, session, result

**Evaluation Run**:
One execution that aggregates **Attempts** across a **Bundle** for comparison or scoring.
_Avoid_: Attempt, session, benchmark

**Improvement Episode**:
One complete self-improvement cycle that compares baseline and candidate behavior before a selection decision.
_Avoid_: Task, experiment, run

**Candidate Improvement**:
A proposed change to Vibelution's harness, prompts, memory, policies, or Tools that must be evaluated before promotion.
_Avoid_: New Agent, patch, result

**Harness Variant**:
An isolated runtime version of the Agent harness with one **Candidate Improvement** applied for evaluation.
_Avoid_: Candidate Improvement, branch, model

**Trace**:
The structured evidence record from one **Attempt** used for diagnosis, replay, scoring, and selection.
_Avoid_: Log, transcript, report

**Score**:
A multi-dimensional evaluation of an **Attempt** or **Evaluation Run** across success, quality, cost, speed, validation, regression, and safety.
_Avoid_: Single metric, pass/fail, grade

**Critic**:
An evaluation role that reads **Traces** and produces evidence-backed diagnoses of the main harness gap.
_Avoid_: Evolver, judge, reviewer

**Harness Gap**:
A limitation in the Agent harness that prevents or slows successful **Attempts**.
_Avoid_: Model weakness, bug, failure

**Evolver**:
An improvement role that turns a **Critic** diagnosis into one bounded **Candidate Improvement**.
_Avoid_: Critic, executor, promoter

**Decision Record**:
The persisted selection result for an **Improvement Episode**, including evidence summaries, gates, final decision, and policy action.
_Avoid_: Report, result file

**Lineage**:
The tracked history of accepted **Candidate Improvements** that become baseline behavior across **Improvement Episodes**.
_Avoid_: History, ancestry

**Selection Policy**:
The rules that interpret a **Decision Record** and decide whether to promote, hold, observe, or reject candidate behavior.
_Avoid_: Gate logic, promotion logic

### Prompt And Memory

**Core Prompt**:
The static prompt layer stored in the project and treated as built-in identity and operating rules.
_Avoid_: System text, base prompt

**Dynamic Prompt**:
The workspace prompt layer that can change as Vibelution learns or adapts to current work.
_Avoid_: User prompt, mutable prompt

**State Memory**:
The current operational memory used to carry constraints, lessons, and runtime state across turns or restarts.
_Avoid_: Scratchpad, session notes

**Memory Archive**:
A persisted record of compressed learning from earlier generations or sessions.
_Avoid_: Log, transcript

### Project Shape

**Core First**:
The architectural rule that stable behavior belongs under `core/`, while `agent.py` remains runtime glue.
_Avoid_: Core architecture, extracted logic

**Workspace**:
The mutable project area where runtime artifacts, prompts, memory, evaluation outputs, and generated state live.
_Avoid_: Working directory, storage

**Restart**:
A controlled handoff from the current **Agent** process to a new process after state and safety checks are complete.
_Avoid_: Reboot, relaunch

## Relationships

- **Vibelution** runs one active **Agent** process at a time.
- An **Agent** handles many **Turns** during a session.
- A **Turn** may contain zero or more **Tool Calls**.
- A **Tool Call** invokes exactly one **Tool**.
- The **Workbench** exposes major modes including chat, configuration, reset, and **Supervised Evolution**.
- The **Evolution Engine** is host-agnostic and can be embedded into Vibelution or another Agent runtime.
- An **Agent Harness Adapter** connects one host Agent implementation to the **Evolution Engine**.
- The **Evolution Engine** coordinates **Improvement Episodes** but does not import `agent.py` or Workbench UI modules.
- A **Gym** contains one or more **Exercises**.
- A **Gym** organizes **Exercises** and **Cases** by **Training Tier**.
- The foundation **Training Tier** protects core Agent stability and regression safety.
- The coordination **Training Tier** exercises multi-module cooperation across planning, context, Tools, validation, memory, recovery, delegation, and runtime flows.
- The intelligence **Training Tier** exercises higher-order diagnosis, abstraction, self-correction, generalization, and Candidate Improvement quality.
- An **Exercise** can be materialized into one or more **Cases**.
- A **Gym** selects or generates **Cases** from one or more **Datasets** to create training pressure for **Self-Evolution**.
- A **Dataset Adapter** materializes one **Dataset** format into **Cases**.
- A **Dataset** can be materialized into one **Bundle**.
- A **Case** belongs to one or more **Dataset Splits**.
- A **Bundle** contains one or more **Cases**.
- A **Generated Case** must record provenance from the **Trace**, **Harness Gap**, or **Improvement Episode** that caused it to be created.
- An **Attempt** belongs to exactly one **Case** and one Agent version or harness variant.
- An **Evaluation Run** produces one or more **Attempts** from a **Bundle**.
- An **Attempt** writes exactly one **Trace**.
- An **Attempt** has one **Score**.
- An **Evaluation Run** aggregates **Scores** across **Attempts**.
- A **Critic** diagnoses **Traces** but does not apply **Candidate Improvements**.
- A **Critic** classifies one main **Harness Gap** for an **Attempt** or **Improvement Episode**.
- An **Evolver** proposes **Candidate Improvements** but does not promote them.
- An **Improvement Episode** contains baseline **Attempts**, one **Candidate Improvement**, candidate **Attempts**, and one selection decision.
- A **Harness Variant** applies exactly one **Candidate Improvement** during an **Improvement Episode**.
- The **Selection Policy** is the only authority that can promote a **Candidate Improvement** into baseline behavior.
- A **Supervised Evolution** session runs one **Bundle** and contributes evidence to a **Decision Record**.
- A **Decision Record** may update **Lineage** through the **Selection Policy** when a **Candidate Improvement** is promoted.
- The **Core Prompt** and **Dynamic Prompt** are combined to build the **Agent**'s runtime prompt.
- **State Memory** may be persisted in the **Workspace** and later restored after a **Restart**.
- **Core First** keeps reusable behavior in `core/` and leaves `agent.py` as orchestration glue.
- **Core First** keeps **Gym** and **Supervised Evolution** behavior in core modules while the **Workbench** exposes thin runtime entry points.

## Example Dialogue

> **Dev:** "Should the **Workbench** scan JSON files directly to show recent supervised results?"
> **Domain expert:** "No. The **Workbench** should ask a deeper Module for recent **Decision Records**, because **Lineage** and **Selection Policy** details belong to the evolution domain."

## Flagged Ambiguities

- "evaluation" can mean both **Supervised Evolution** and generic test execution; use **Supervised Evolution** only for baseline/candidate case comparison.
- "result" can mean a **Tool Call** result or a **Decision Record**; use the specific term.
- "prompt" can mean **Core Prompt**, **Dynamic Prompt**, or the user's current task text; use the specific term when architecture is being discussed.
- "workspace" can mean the repository root or the mutable **Workspace** area; use **Workspace** only for runtime artifacts under `workspace/`.
- Generated **Cases** can train or observe Vibelution, but holdout **Bundles** must be stable, versioned, and not automatically generated by the same **Improvement Episode**.
- In the first Gym release, **Selection Policy** may produce a promotion proposal for a **Candidate Improvement**, but it must not automatically rewrite baseline behavior.
- Workbench and `agent.py` must not hardcode individual **Dataset** formats; they should use registry and **Dataset Adapter** boundaries.
- A **Generated Case** provenance record must at least preserve source trace, source episode, source harness gap, generation reason, creator version, creation time, and allowed dataset splits.
- **Selection Policy** must interpret **Scores** in relation to their **Dataset Split**.
- The observe **Dataset Split** may collect uncertain evidence, but it must not trigger promotion without supporting dev, holdout, or regression evidence.
- **Evolution Engine** code must remain embeddable in arbitrary Agent runtimes; Vibelution-specific process, Workbench, and `agent.py` behavior must live behind **Agent Harness Adapter** implementations.
- Higher **Training Tiers** cannot bypass lower-tier gates: foundation regression failure blocks promotion even when coordination or intelligence scores improve.
