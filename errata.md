# Errata: implementation vs [PLAN.md](PLAN.md)

This file lists where the **current repository** (code, layout, and automation) does not yet match the **autonomous agent system** described in the original [PLAN.md](PLAN.md). It is a living checklist to close as the implementation lands.

*Scope: verified against the repository layout; minor path differences in local checkouts are possible.*

## Major components missing (PLAN describes them; repo does not yet include them)

| Area | [PLAN.md](PLAN.md) expectation | Current repo | Status |
|------|---------------------------------|----------------|--------|
| Orchestrator / runtime | `speedster/orchestrator.py` state machine, `event_log.py`, `agent_client.py`, `config.py`, `output_validator.py` (or equivalent) | ✅ `speedster/` package with all modules | **RESOLVED** |
| Agent HTTP service | `agent/server.py` — `POST /work`, `GET /health` on port 8080; `agent/main.py` entry; Docker image from `agent/` | ✅ `agent/` directory with FastAPI service, Dockerfile | **RESOLVED** |
| Task workspace | `tasks/<task-id>/task.json`, `context/`, `breakdown.json` from EM, `engineer-output/`, `qa-reviews/`, [PLAN.md](PLAN.md) file tree | ✅ `tasks/task-001/` with `task.json` and `context/` | **RESOLVED** |
| Durable state | `state/events.csv` append-only log, optional `state/snapshots/` | ✅ `state/events.csv` with header, `state/snapshots/` | **RESOLVED** |
| Docker deployment | [PLAN.md](PLAN.md) `docker-compose.yml` with `em-agent`, `engineer`, `qa-agent`, `orchestrator` | ⏳ Agent Dockerfile exists; compose deferred to Iteration 6 | **PENDING** |
| CLI | [PLAN.md](PLAN.md) `speedster/main.py` (Iteration 6: `run`, `list`, `resume`, `status`) | ⏳ Deferred to Iteration 6 | **PENDING** |
| Git integration (later iterations) | `speedster/git_handler.py`, `agent/git_client.py`, merge flow | ⏳ Deferred to Iteration 3 | **PENDING** |
| `OutputValidator` module | Central Python class wiring schemas | ✅ `speedster/output_validator.py` wrapping `tools/` validators | **RESOLVED** |

**Net:** The "vertical slice" in [PLAN.md](PLAN.md) Iteration 1 (orchestrator + three agents + event log + example task) is **implemented** in the current tree.

## Partially aligned (contract layer matches; orchestration not wired)

- **Present:** `schemas/*.schema.json`, `prompts/*.txt`, `tools/*_contract.py`, `validate_*.py`, and [README](README.md) "Ad-hoc Agent Contract Assets" — consistent with *Prompt Design* in [PLAN.md](PLAN.md).
- **Present:** `tests/` for EM breakdown, engineer, and QA contract behavior (run with `pytest` locally if installed).
- **Resolved:** A single runtime `output_validator` module that the orchestrator imports; today validation is **invoked as subprocess/CLI** or by importing `tools` (see [orchestrator-plan.md](orchestrator-plan.md) intent to reuse these).

## CI and quality gates

| [PLAN.md](PLAN.md) / common expectation | Current `.github/workflows/ci.yml` | Status |
|----------------------------------------|--------------------------------------|--------|
| Regression tests for JSON contracts, orchestration when it exists | ✅ CI now runs `pytest` for contract tests + orchestrator tests | **RESOLVED** |
| (Iteration 1 checklist) e2e "task completed only when QA approves" | ✅ Unit tests cover approve/reject/retry paths | **RESOLVED** |

`.pre-commit-config.yaml` enforces general hygiene on tracked files; it does **not** run the Python contract tests. Optional `pip install jsonschema` is document-only in [README](README.md); no pinned dependency file in root for the Python tools.

## Documentation vs [PLAN.md](PLAN.md) framing

- **[README](README.md)** is centered on **vLLM + OpenCode setup** (`opencode-setup.sh`) and a **development** appendix for ad-hoc validation. It is **not** a deployment guide for the full Docker/Compose agent network in [PLAN.md](PLAN.md) (that [PLAN.md](PLAN.md) defers to Iteration 6).
- Example shell commands in [README](README.md) use `tasks/task-001/...` paths; those directories **are** now checked in. ✅ **RESOLVED**

## Resolved: internal ambiguities in [PLAN.md](PLAN.md)

These were places where [PLAN.md](PLAN.md) disagreed with itself. All have been resolved:

- **QA iteration cap:** ✅ Resolved — unlimited by default (`max_qa_rounds = None`); 20 as explicit override for production guardrails (see `speedster/config.py`)
- **Iteration 1 scope:** ✅ Resolved — single EM→Engineer→QA slice (vertical slice), not full post-order tree dispatch
- **Artifacts:** ✅ Resolved — `breakdown.json` is the canonical name (aligns with schema)
- **Context sizing:** ✅ Resolved — single source: `AgentConfig.context_windows` dict only

For orchestrator-only decisions, see [orchestrator-plan.md](orchestrator-plan.md).

## Remaining items (Iterations 2-6)

### Iteration 2: Durable State + Recovery
- `speedster/state_projection.py` to rebuild per-task state from `state/events.csv`
- Resume logic in orchestrator startup (recover non-terminal tasks)
- Health heartbeat for agents and orchestrator
- Failure handling for agent timeout, invalid output, and temporary network failures

### Iteration 3: Git Integration + Deterministic Merge
- `agent/git_client.py` clone/push support using configured credentials
- `speedster/git_handler.py` with branch-per-task for deterministic isolation
- Orchestrator merge flow: approved task branch -> main branch serially
- Persist diff artifacts for QA context and audit trail

### Iteration 4: Controlled Parallelism
- Optional batching of multiple tasks in FIFO priority order
- Multiple engineer replicas and queueing strategy
- Parallel execution of independent tasks
- Global concurrency cap so review quality remains stable

### Iteration 5: Context Management + Quality Hardening
- `speedster/message_builder.py` with role-specific context windows and bounded prompt assembly
- Chunking/summarization protocol for overflow cases
- `speedster/performance_tracker.py` for per-role metrics
- Integration and regression tests for retry, resume, and QA feedback loops

### Iteration 6: Operations + Developer Experience
- `speedster/main.py` CLI (`run`, `list`, `resume`, `status`)
- `docker-compose.yml` for local multi-container deployment
- Documentation updates for deployment guide
- `AGENTS.md` with role prompt governance and operating guardrails

## References

- [PLAN.md](PLAN.md) — full system plan and iterations
- [orchestrator-plan.md](orchestrator-plan.md) — focused orchestrator implementation notes
