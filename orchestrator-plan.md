# Orchestrator implementation plan

This document captures the implementation plan for `speedster/orchestrator.py` and its direct dependencies. It is derived from [PLAN.md](PLAN.md) and from design decisions that resolve ambiguities in that plan. For the full system, agents, and iterations roadmap, use `PLAN.md` as the source of truth; this file stays focused on the orchestrator.

## Role

The orchestrator is the **only writer** to the append-only CSV event log (`state/events.csv`). It:

- Drives **EM → Engineer → QA** over HTTP (`POST /work`, `GET /health`).
- Appends a durable event **only after** the corresponding step succeeds (or after an explicit failure path like timeout).
- Respects contracts in [PLAN.md](PLAN.md) *Prompt Design* (schemas, `needs_context`, QA approval/rejection mapping, no self-reported `commit_sha` from the Engineer JSON).

## Quality-first and QA loop

- **Policy:** Default behavior is to iterate Engineer ↔ QA until QA returns **approved** (no arbitrary low retry budget for “cost” reasons when implementing).
- **Safety:** [PLAN.md](PLAN.md)’s `max_qa_rounds` (e.g. 20) is a **circuit breaker** for runaway loops or broken agents, not the primary product policy. Prefer treating “unlimited” as the default in code, with an **optional** `max_qa_rounds` (or a very high ceiling) for tests and production guardrails. Document the chosen default in `config.py`.

## Dependency order (build in this sequence)

1. **`speedster/config.py`** — `AgentConfig`, per-role base URLs, `EventLogConfig`, context limits, optional `max_qa_rounds`, `task_dir`, harness `repo` fields if passed at run start.
2. **`speedster/event_log.py`** — `HEADER`, monotonic `seq`, `append` + `fsync`, `replay` (needed for tests and later resume).
3. **`speedster/agent_client.py`** — `POST /work` with session handling as required, `GET /health`, timeouts, basic retries for empty output and transient network errors.
4. **`speedster/output_validator.py`** (or facades to existing `tools/validate_*.py`) — EM breakdown, **engineer input/output**, QA output; return parsed data or a structured “retry with validation error in prompt” signal.
5. **`speedster/orchestrator.py`** — state machine; **Iteration 1** can use mocks/stubs for git until `GitHandler` exists.

`StateProjection`, full `MessageBuilder` chunking, and `main.py` CLI can land after the vertical slice, per iteration boundaries in [PLAN.md](PLAN.md).

## State machine and events (CSV)

| Phase | `event_type` (typical) | Notes |
|--------|-------------------------|--------|
| Task accepted | `TaskCreated` | Message may record harness `repo.url` + `repo.default_branch` for audit/replay. |
| EM success | `PlanningCompleted` | After schema-valid EM output. |
| Engineer + git | `ImplementationCompleted` | `message` encodes `branch=… commit=…`; **read SHA from git** after push, not from Engineer JSON. |
| QA pass | `ReviewPassed` then `TaskCompleted` | |
| QA fail | `ReviewFailed` | Then re-dispatch Engineer with `prior_feedback` per schemas. |
| Cap / fatal | `TaskFailed` | e.g. max QA rounds, timeout, unrecoverable error (see [PLAN.md](PLAN.md) Error Handling). |

Pseudocode structure in [PLAN.md](PLAN.md) (orchestrator section) is the template; extend it for **EM re-run** on `needs_context` and for **post-order tree** engineer dispatch when that scope is implemented (see *Scope* below).

## Scope: Iteration 1 vs full tree

[PLAN.md](PLAN.md) Iteration 1 is a **vertical slice** (single flow); the **Prompt Design** section describes **full** EM tree behavior (post-order dispatch, integration nodes, one commit per node). **Decide explicitly:**

- **Slice:** Root-only EM output and a single engineer/QA pair (or a minimal non-recursive path), **or**
- **Full contract:** Post-order multi-invocation and `needs_context` / blocked handling in v1.

The orchestrator must not silently implement one while the other is assumed by tests or prompts. Record the chosen option here when decided.

## Integration points

- **Agent API:** [PLAN.md](PLAN.md) — `POST /work` body `{ "message", "session_id" }`, response with `output`, `tokens_used`, `latency_ms`.
- **Harness repo:** [PLAN.md](PLAN.md) *Harness run input* — `repo.url` and `repo.default_branch` come from the harness, not from `task.json` / `breakdown.json`; persist in durable state (e.g. `TaskCreated` message or header row if you add one).
- **Validation:** Reuse or mirror `tools/validate_em_breakdown.py`, `validate_engineer_input.py`, `validate_engineer_output.py`, `validate_qa_input.py`, `validate_qa_output.py` so CI and runtime share one contract.

## What to defer (keep orchestrator thin)

- **Iteration 2:** `state_projection` resume, optional snapshots, 30s health loop, idempotent recovery (no duplicate terminal events).
- **Iteration 3:** `GitHandler` + real clone/push, merge, conflict status vs `TaskFailed` / explicit conflict event.
- **Iteration 4+:** Multiple tasks, engineer replicas, queueing.
- **Iteration 5+:** Full `MessageBuilder` with chunking, richer `PerformanceTracker` (track EM/engineer too, not only QA).
- **Iteration 6:** `speedster/main.py` CLI, docker-compose for full stack.

## Testing

- **Unit:** Event sequences for approve path, reject→approve path, and optional cap exceeded path; validator behavior (invalid JSON / schema).
- **Integration:** Mock HTTP or stub agents; assert three roles log distinct `model` values; task completes only after QA `approved`.
- **E2E (when agents exist):** One full loop against real containers.

## Module layout (orchestrator package)

- **`orchestrator.py`:** `run()`, `process_task()`, inject `EventLog`, `AgentClient`, `AgentConfig`, validator, optional `GitHandler` / `StateProjection` later.
- **Private helpers:** `_run_em`, `_run_engineer`, `_run_qa`, `_append`, `_load_task` — return structured results, not raw strings.
- **Stable `message` column** in CSV for machine replay; free text only where the plan’s examples do.

## Risks (address early)

1. **Event schema + append ordering** — everything else (resume, audit) depends on it.
2. **Validator + retry** — avoid poisoning durable state on bad model output.
3. **`session_id` semantics** — must match agent behavior across multiple `/work` calls.
4. **Commit SHA** — always from git after push, never from engineer JSON.
5. **Tree + `needs_context`** — largest complexity jump; keep behind clear milestones.

## Plan errata (orchestrator-relevant)

[PLAN.md](PLAN.md) has a few items worth overriding or clarifying in code/docs:

- **`plan.json` vs `breakdown.json`:** File tree should align with `breakdown.json` + `schemas/em_breakdown.schema.json`.
- **`ModelConfig.context_window` vs `AgentConfig.context_windows`:** Pick a single source of truth for `MessageBuilder` (e.g. only `context_windows` for orchestration).
- **OutputValidator** section mentions outputs only; Iteration 1 also expects **engineer input** validation — include in the validator design.
- **Terminal conflict state** (merge failure): plan mentions `conflict` status; ensure event log / projection can represent it when Git integration ships.

## References

- [PLAN.md](PLAN.md) — architecture, HTTP API, CSV schema, `Orchestrator` pseudocode, iterations, checklists, Prompt Design.
- `schemas/*.schema.json` and `tools/*_contract.py` — runtime and CI contracts for each role.
