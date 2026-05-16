# Gym v1 Uses Promotion Proposals Before Baseline Rewrite

Gym v1 evaluates **Candidate Improvements** through isolated **Harness Variants** and **Improvement Episodes**, but a promoted result is first persisted as an auditable promotion proposal instead of automatically rewriting baseline behavior. This keeps the task-driven self-evolution loop measurable and recoverable while the new **Trace**, **Critic**, **Evolver**, and **Selection Policy** boundaries are still being proven.

Automatic baseline rewrite remains a future capability that should only be enabled after replay, rollback, holdout, and regression evidence are strong enough to make autonomous promotion safe.

The first implementation should prove the full **Improvement Episode** loop with low-risk, bounded improvement types such as prompt patches, policy patches, verifier patches, or small Workbench flow patches. Broader Tool, scheduler, memory, and harness code changes can follow after the trace and evaluation machinery is reliable.

The first Gym should use a small local transaction-closing exercise to keep the loop deterministic, but the **Dataset** and adapter boundary must remain extensible so future local, public, generated, and imported sources can be added without hardcoding them into the Workbench or `agent.py`.
