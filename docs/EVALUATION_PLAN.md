# Evaluation plan (format only — nothing here has been measured)

Question to answer later: does adding a supervisor (Astra in Codex) on top of an executor
(Claude Code / Opus 5.5) improve outcomes enough to justify the extra usage and rework? Mock
data cannot answer this; no percentages are claimed anywhere in this repository.

## Arms
- **A** Opus executes alone.
- **B** Opus executes, then the same model self-reviews (separates "more review work" from
  "cross-model review").
- **C** Astra plans + Opus executes through Harness Bridge + Astra reviews independently.

## Protocol
Same base commit, same requirements and acceptance checks, separate worktrees, fresh sessions,
explicit work limits. No leakage of one arm's solution or failures into another. Start with a
small set of representative tasks as exploration (no significance claims); with budget, add
repetitions and randomized order and report uncertainty.

## What to record per run
completion / failure; independent acceptance result; wall time; human interventions; repair
cycles; observable usage on both sides; context/artifact bytes read; total model calls;
model + CLI versions (with source of truth); permission and cache configuration; bridge overhead
(startup, artifact handling, verification time) kept separate from model tokens. Unknown usage
is `null`. Plan percentages across resets or with other concurrent use are marked
non-comparable. Without real dollar costs, no cost-per-success is computed.

Result records follow `docs/evaluation_result.schema.json`.
