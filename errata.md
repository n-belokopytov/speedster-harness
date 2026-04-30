# Errata: implementation vs [PLAN.md](PLAN.md)

This file lists where the **current repository** (code, layout, and automation) does not yet match the **autonomous agent system** described in the original [PLAN.md](PLAN.md). It is a living checklist to close as the implementation lands.

*Scope: verified against the repository layout; minor path differences in local checkouts are possible.*

## Remaining Items

### OpenCode ACP Integration (Wired)
- **Remaining:** Real-model E2E tests are `xfail` until `opencode` CLI + model endpoint are reachable

### Git Integration (Iteration 3) - Implemented
- **Remaining:** End-to-end merge flow with remote push not yet tested (requires remote repo)

## Resolved

The following items previously listed as pending are now implemented:
`speedster run --watch` polls for new pending tasks on a configurable interval (default 30s) until `SIGINT`/`SIGTERM`. The Docker orchestrator service defaults to watch mode via `ENTRYPOINT speedster run --watch`.
`docker-compose.yml` now includes the `orchestrator` service with `depends_on: [em-agent, engineer-agent, qa-agent]` (health-check gated). `speedster/Dockerfile` builds the orchestrator container.
- **Docker Compose orchestrator service:** `docker-compose.yml` orchestrator service with health-gated `depends_on`, `speedster/Dockerfile`
- **Orchestrator watch mode:** `speedster run --watch` with configurable poll interval
- **CLI (`speedster/main.py`):** `run`, `list`, `resume`, `status` commands all implemented (Iteration 6, pulled forward)
- **State projection (`speedster/state_projection.py`):** event replay, per-task state reconstruction, non-terminal resume (Iteration 2, pulled forward)
- **Docker Compose agents:** `docker-compose.yml` with `em-agent`, `engineer-agent`, `qa-agent` services
- **Agent Dockerfile:** `agent/Dockerfile` exists with role/model build args
- **Agent entry point:** `agent/main.py` starts FastAPI server with config validation
- **tools/ CLI validators:** all 6 exist in `speedster/cli/`; docs updated to match
- **Git Integration:** `agent/git_client.py`, `speedster/git_handler.py`, orchestrator merge flow (Iteration 3)
- **AGENTS.md:** Role prompt governance and operating guardrails (Iteration 6)

- `agent/git_client.py` — implemented: clone, branch, commit, push, diff, SSH key auth
- `speedster/git_handler.py` — implemented: branch-per-task, merge flow, diff retrieval for QA
Git operations are wired into the agent and orchestrator.

- `orchestrator.py` — `ImplementationCompleted` events now include branch and commit SHA
- `orchestrator.py` — `TaskCompleted` events trigger merge to default branch
- `tests/test_git_client.py` — 12 tests with real git repos
- `tests/test_git_handler.py` — 9 tests (unit + integration)
- `agent/acp_client.py` — implemented with timeout, error handling, JSON parsing
- `agent/server.py:170-176` — `_process_message` delegates to `ACPClient.process_message()` in non-mock mode
- `tests/test_server.py` — unit tests cover non-mock delegation, HTTP 500 error propagation, `MOCK_MODE` env variable
- `tests/test_e2e.py` — `TestE2ERealModel` class with `xfail` marker; requires reachable model endpoint to pass



## Deferred (Future Iterations)

### Iteration 4: Controlled Parallelism
- Optional batching of multiple tasks in FIFO priority order
- Multiple engineer replicas and queueing strategy
- Parallel execution of independent tasks
- Global concurrency cap so review quality remains stable

### Iteration 5: Context Management + Quality Hardening
- `speedster/message_builder.py` (currently `prompt_builder.py`) with role-specific context windows and bounded prompt assembly
- Chunking/summarization protocol for overflow cases
- `speedster/performance_tracker.py` for per-role metrics
- Integration and regression tests for retry, resume, and QA feedback loops

## References

- [PLAN.md](PLAN.md) — full system plan and iterations
- [orchestrator-plan.md](orchestrator-plan.md) — focused orchestrator implementation notes
