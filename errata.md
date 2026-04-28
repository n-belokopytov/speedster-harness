# Errata: implementation vs [PLAN.md](PLAN.md)

This file lists where the **current repository** (code, layout, and automation) does not yet match the **autonomous agent system** described in the original [PLAN.md](PLAN.md). It is a living checklist to close as the implementation lands.

*Scope: verified against the repository layout; minor path differences in local checkouts are possible.*

## Remaining Items

### OpenCode ACP Integration (Wired)
The agent server is wired to `ACPClient` when `mock_mode=False`. The `ACPClient` spawns `opencode --model <model> --stdin` via `subprocess.run()` and parses JSON output.

- `agent/acp_client.py` — implemented with timeout, error handling, JSON parsing
- `agent/server.py:170-176` — `_process_message` delegates to `ACPClient.process_message()` in non-mock mode
- `tests/test_server.py` — unit tests cover non-mock delegation, HTTP 500 error propagation, `MOCK_MODE` env variable
- `tests/test_e2e.py` — `TestE2ERealModel` class with `xfail` marker; requires reachable model endpoint to pass
- **Remaining:** Real-model E2E tests are `xfail` until `opencode` CLI + model endpoint are reachable

### Git Integration (Iteration 3)
No git operations are implemented. The orchestrator records `ImplementationCompleted` events but does not read the post-push HEAD SHA, create branches, or push code.

- `agent/git_client.py` — missing entirely; needs clone/push support with SSH key auth
- `speedster/git_handler.py` — missing entirely; needs branch-per-task, merge flow, diff retrieval
- `orchestrator.py:241-247` — logs `ImplementationCompleted` with `round=N` but not `branch=` or `commit=`
- `agent/config.py:20-25` — `git_ssh_key` and `repo_root` are defined but unused

### Docker Compose: Orchestrator Service
`docker-compose.yml` has all three agent services but **no orchestrator service**. The orchestrator currently runs locally via `speedster run` CLI.

- Missing `orchestrator` service definition with `depends_on: [em-agent, engineer-agent, qa-agent]`
- Missing orchestrator Dockerfile (reuses `agent/Dockerfile` context or needs its own)

### Orchestrator Watch Mode
`speedster run` processes a single task and exits. There is no polling loop to watch for new tasks.

- `orchestrator.py:57-71` — `run()` finds one pending task, processes it, and returns
- Needed: continuous loop that polls `tasks/` for new `pending` tasks, processes them sequentially

### tools/ CLI Wrappers (Path Discrepancy)
[PLAN.md](PLAN.md) and [README.md](README.md) reference validator CLIs under `tools/`, but they live in `speedster/cli/`:

| PLAN.md path | Actual path |
|---|---|
| `tools/validate_em_breakdown.py` | `speedster/cli/validate_em_breakdown.py` |
| `tools/validate_engineer_input.py` | `speedster/cli/validate_engineer_input.py` |
| `tools/validate_engineer_output.py` | `speedster/cli/validate_engineer_output.py` |
| `tools/validate_qa_input.py` | `speedster/cli/validate_qa_input.py` |
| `tools/validate_qa_output.py` | `speedster/cli/validate_qa_output.py` |
| `tools/normalize_em_breakdown.py` | `speedster/cli/normalize_em_breakdown.py` |

### AGENTS.md
Missing. [PLAN.md](PLAN.md) Iteration 6 calls for `AGENTS.md` with role prompt governance and operating guardrails.

## Resolved

The following items previously listed as pending are now implemented:

- **CLI (`speedster/main.py`):** `run`, `list`, `resume`, `status` commands all implemented (Iteration 6, pulled forward)
- **State projection (`speedster/state_projection.py`):** event replay, per-task state reconstruction, non-terminal resume (Iteration 2, pulled forward)
- **Docker Compose agents:** `docker-compose.yml` with `em-agent`, `engineer-agent`, `qa-agent` services
- **Agent Dockerfile:** `agent/Dockerfile` exists with role/model build args
- **Agent entry point:** `agent/main.py` starts FastAPI server with config validation
- **tools/ CLI validators:** all 6 exist in `speedster/cli/` (see path discrepancy above)

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
