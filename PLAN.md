# Autonomous Agent System - Implementation Plan

## Overview

An autonomous agent system with three roles (EM, Engineer, QA) that processes tasks, implements code, and reviews quality. Each role runs as an independent OpenCode container with its own model, while the orchestrator remains the single source of progress state through a local CSV event log. Designed for unlimited-token machines with open-weight models, where quality is paramount and operations may span multiple hours.

**Key principles:**

- Unlimited token consumption (no cost constraints) — context window management and token tracking only
- Quality-first — QA has no hard retry cap, iterates until approved
- Multi-hour autonomous operation — event-log replay recovery, health monitoring, crash resilience
- Model agnostic — OpenCode wraps any model; each role configured with its own
- Crash semantics are explicit — in-flight uncommitted work can be lost; recovery resumes from last pushed git state + event log

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Docker Compose Network                         │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   EM         │  │ Engineer     │  │   QA         │           │
│  │  Container   │  │  Container   │  │  Container   │           │
│  │              │  │              │  │              │           │
│  │  OpenCode    │  │  OpenCode    │  │  OpenCode    │           │
│  │  ACP server  │  │  ACP server  │  │  ACP server  │           │
│  │  HTTP API    │  │  HTTP API    │  │  HTTP API    │           │
│  │  Git client  │  │  Git client  │  │  Git client  │           │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘           │
│         │                 │                  │                   │
│         └─────────────────┼──────────────────┘                   │
│                           │                                      │
│                    ┌──────▼──────────────────────────┐           │
│                    │        Orchestrator Container   │           │
│                    │  - Workflow state machine       │           │
│                    │  - CSV event log (local disk)  │           │
│                    │  - Resume/replay logic         │           │
│                    └──────┬──────────────────────────┘           │
│                           │                                      │
│                ┌──────────▼──────────┐                           │
│                │ Git Server           │                           │
│                │ (repo + SSH)         │                           │
│                └──────────────────────┘                           │
└──────────────────────────────────────────────────────────────────┘
```

## Communication Model

Agents communicate via **HTTP work calls**, while orchestrator progress is stored in a **single local append-only CSV event log**.

### Artifact Flow

```
Orchestrator creates task
         │
         │ appends: TaskCreated to `state/events.csv`
         ▼
EM role runs over HTTP
         │
         │ returns implementation plan/checklist + acceptance criteria
         │ appends: PlanningCompleted
         ▼
Engineer role runs over HTTP
         │
         │ commits + pushes to task branch
         │ appends: ImplementationCompleted (with branch + commit in message)
         ▼
QA role runs over HTTP
         │
         ├── approved  -> append: ReviewPassed -> append: TaskCompleted
         └── rejected  -> append: ReviewFailed -> loop back to Engineer
```

### CSV Event Log Schema (`state/events.csv`)

```
seq,ts,task_id,event_type,role,model,message
1,2026-04-20T10:00:00Z,task-001,TaskCreated,orchestrator,,Task accepted
2,2026-04-20T10:01:10Z,task-001,PlanningCompleted,em,vllm/qwen3.6-35b,Plan produced
3,2026-04-20T10:05:22Z,task-001,ImplementationCompleted,engineer,vllm/qwen3.6-35b,branch=speedster/task-001 commit=abc123
4,2026-04-20T10:06:30Z,task-001,ReviewFailed,qa,vllm/qwen3.6-35b,Missing error handling
5,2026-04-20T10:10:44Z,task-001,ImplementationCompleted,engineer,vllm/qwen3.6-35b,branch=speedster/task-001 commit=def456
6,2026-04-20T10:12:02Z,task-001,ReviewPassed,qa,vllm/qwen3.6-35b,All criteria met
7,2026-04-20T10:12:03Z,task-001,TaskCompleted,orchestrator,,Terminal state reached
```

## File Structure

```
tasks/                          speedster/                    agent/                    state/
├── task-001/                   ├── __init__.py  ✅           ├── __init__.py   ✅      ├── events.csv ✅
│   ├── task.json   ✅          ├── main.py      ✅           ├── main.py       ✅      └── snapshots/ ✅
│   ├── context/      ✅        ├── config.py    ✅           ├── config.py     ✅
│   │   ├── README.md ✅        ├── orchestrator.py ✅        ├── server.py     ✅
│   │   └── ...                     ├── event_log.py    ✅        ├── git_client.py ⏳
│   ├── breakdown.json ⏳            ├── state_projection.py ✅      ├── tools/        ✅
│   └── ...                       ├── agent_client.py ✅          │   ├── em.yaml   ✅
                                 ├── git_handler.py    ⏳          │   ├── engineer.yaml ✅
                                 ├── output_validator.py ✅        │   └── qa.yaml   ✅
                              ├── performance_tracker.py ⏳     ├── Dockerfile    ✅
                              ├── response_parser.py  ✅        └── requirements.txt ✅
                                 ├── task_manager.py     ✅
                                ├── events.py           ✅
                                ├── interfaces.py       ✅
                                ├── models.py           ✅
                                ├── exceptions.py       ✅
                                ├── contracts/          ✅
                                │   ├── em_breakdown.py ✅
                                │   ├── engineer_contract.py ✅
                                │   └── qa_contract.py  ✅
                                └── cli/                ✅
                                    ├── validate_em_breakdown.py ✅
                                    ├── validate_engineer_input.py ✅
                                    ├── validate_engineer_output.py ✅
                                    ├── validate_qa_input.py ✅
                                    ├── validate_qa_output.py ✅
                                    └── normalize_em_breakdown.py ✅
```

**Legend:** ✅ Implemented | ⏳ Not yet implemented

Additional implemented files:
- `docker-compose.yml` ✅ (agent services only; orchestrator service pending)
- `prompts/em_system_prompt.txt` ✅, `engineer_system_prompt.txt` ✅, `qa_system_prompt.txt` ✅
- `schemas/*.schema.json` ✅ (5 schemas)
- `.env.example` ✅
- `setup.sh` ✅
- `tests/` ✅ (12 test files)

## HTTP API (per agent container)

```python
# Each agent exposes a FastAPI server on port 8080

# POST /work
# Body: { "message": "...", "session_id": "..." }
# Response: { "session_id": "...", "output": "...", "tokens_used": 1234, "latency_ms": 4500 }

# GET /health
# Response: { "status": "healthy", "model": "unsloth/...", "gpu_mem": "45%" }
```

## Docker Compose

```yaml
services:
  em-agent:
    build:
      context: ./agent
      args:
        - ROLE=em
        - MODEL=vllm/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K
    environment:
      - GIT_SSH_KEY=/secrets/gitkey
      - TOOLS_CONFIG=/etc/opencode/tools/em.yaml
    volumes: ["gitkey:/secrets"]

  engineer:
    build:
      context: ./agent
      args:
        - ROLE=engineer
        - MODEL=vllm/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K
    environment:
      - GIT_SSH_KEY=/secrets/gitkey
      - TOOLS_CONFIG=/etc/opencode/tools/engineer.yaml
    volumes: ["gitkey:/secrets"]
    deploy:
      replicas: 3

  qa-agent:
    build:
      context: ./agent
      args:
        - ROLE=qa
        - MODEL=vllm/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K
    environment:
      - GIT_SSH_KEY=/secrets/gitkey
      - TOOLS_CONFIG=/etc/opencode/tools/qa.yaml
    volumes: ["gitkey:/secrets"]

  orchestrator:
    build: ./speedster
    environment:
      - EVENT_LOG_PATH=/app/state/events.csv
      - GIT_SSH_KEY=/secrets/gitkey
    volumes: ["gitkey:/secrets"]
    depends_on: [em-agent, engineer, qa-agent]

volumes:
  gitkey:
```

## Module Descriptions

### `speedster/config.py` - Configuration Models ✅

```python
class ConnectivityConfig(BaseModel):
    """Agent endpoint URLs."""
    em_url: str
    eng_url: str
    qa_url: str

class EventLogConfig(BaseModel):
    path: Path = Path("state/events.csv")
    snapshot_dir: Path = Path("state/snapshots")
    fsync_on_append: bool = True

class StorageConfig(BaseModel):
    event_log: EventLogConfig = Field(default_factory=EventLogConfig)
    task_dir: Path = Path("tasks")

class AgentConfig(BaseModel):
    connectivity: ConnectivityConfig
    storage: StorageConfig
    max_qa_rounds: int | None = None  # quality-first: no hard limit, but cap for safety
    track_performance: bool = True
    repo_url: str | None = None
    git_ssh_key: str | None = None
    repo_default_branch: str | None = None
```

### `speedster/event_log.py` - CSV Event Log ✅

Single-writer append-only CSV store managed by the orchestrator. This is the source of truth for workflow progress.

```python
class EventLog:
    HEADER = ["seq", "ts", "task_id", "event_type", "role", "model", "message"]

    def append(self, task_id: str, event_type: str, role: str, model: str, message: str):
        """Append one event row and fsync for durability."""
        ...

    def replay(self):
        """Yield events ordered by seq for state reconstruction."""
        ...
```

### `speedster/state_projection.py` - Replay + Current State ✅

Rebuilds current per-task state by replaying `state/events.csv`. On startup, orchestrator replays events and resumes all non-terminal tasks from their last durable event.

### `speedster/output_validator.py` - Output Validator ✅

Every agent output is validated against a JSON schema before the orchestrator consumes it. Invalid output triggers a retry with the error in the prompt.

```python
class OutputValidator:
    PLAN_SCHEMA = {...}
    QA_FEEDBACK_SCHEMA = {...}
    ENGINEER_SUMMARY_SCHEMA = {...}

    def validate(self, output: str, output_type: str) -> dict | None:
        try:
            data = json.loads(output)
            validate(data, self.SCHEMAS[output_type])
            return data
        except json.JSONDecodeError:
            return None  # signals retry needed
        except ValidationError as e:
            return {"error": str(e)}  # signals retry with error message
```

### `speedster/performance_tracker.py` - Performance Tracker ⏳

Tracks metrics per call (no budget cap, just tracking for quality analysis).

```python
class PerformanceTracker:
    def track_call(self, role, model, tokens, latency_ms, approved, round_num):
        self._record({
            "role": role, "model": model, "tokens": tokens,
            "latency_ms": latency_ms, "approved": approved,
            "round_num": round_num, "timestamp": datetime.now()
        })

    def get_metrics(self):
        return {
            "total_calls": ..., "total_tokens": ...,
            "avg_latency_ms": ..., "avg_qa_rounds": ...,
            "approval_rate": ..., "tokens_per_call": ...,
            "by_model": {model_name: {...}},
            "by_role": {"em": {...}, "engineer": {...}, "qa": {...}}
        }
```

### `speedster/agent_client.py` - HTTP Agent Client ✅

Client to call remote agent APIs. Handles connection pooling, retries on unhealthy agents, and health check integration.

### `speedster/task_manager.py` - Task Input + Status Projection ✅

Loads task definitions from `tasks/` and exposes read-model status derived from event replay. No external task tracker is required.

### `speedster/git_handler.py` - Git Operations (Remote Repo) ⏳

Branch-per-group git strategy with orchestrator-managed merge.

```python
class GitHandler:
    def create_task_branch(self, task_id: str) -> str:
        """Create isolated branch for task execution: speedster/task-{id}"""
        ...

    def merge_task_branch(self, task_branch: str) -> bool:
        """Merge task branch into main. Returns False if conflicts."""
        ...

    def get_task_diff(self, task_branch: str) -> str:
        """Get git diff for QA context."""
        ...

    def clone_repo(self, branch: str, target_dir: Path):
        """Clone repo into agent working directory."""
        ...

    def push_changes(self, branch: str, commit_msg: str):
        """Push changes from agent container to central repo."""
        ...
```

### Agent Prompt Assembly

Each agent container builds its own prompts. The orchestrator sends structured payloads (task description, plan, QA feedback, etc.) via HTTP, and the agent's `server.py:_build_message()` constructs the user message. The agent's `acp_client.py` prepends the role's system prompt when invoking the model.

### `speedster/orchestrator.py` - Workflow Orchestrator (State Machine) ✅

```python
class Orchestrator:
    def __init__(self, config: AgentConfig):
        self.event_log = EventLog(config.event_log)
        self.agent_client = AgentClient()
        self.task_manager = TaskManager()
        self.git_handler = GitHandler()
        self.state_projection = StateProjection(self.event_log)
        self.message_builder = MessageBuilder(config.context_windows)
        self.validator = OutputValidator()
        self.tracker = PerformanceTracker()

    async def run(self):
        # 1. Load/replay CSV event log
        # 2. Resume non-terminal tasks
        # 3. Start health check loop (ping agents every 30s)
        # 4. Poll task directory for new tasks

    async def process_task(self, task: Task):
        self.event_log.append(task.id, "TaskCreated", "orchestrator", "", "Task accepted")

        # EM planning (sequential, via HTTP)
        plan = await self._run_em(task)
        self.event_log.append(task.id, "PlanningCompleted", "em", plan.model, "Plan produced")

        # Single task unit: engineer -> qa feedback loop
        for round_num in range(self.config.max_qa_rounds):
            engineer_result = await self._run_engineer(task, plan)
            # `commit_sha` is read from git_client after the agent's push; the
            # agent itself does NOT self-report a SHA in its JSON response.
            self.event_log.append(
                task.id,
                "ImplementationCompleted",
                "engineer",
                engineer_result.model,
                f"branch={engineer_result.branch} commit={engineer_result.commit_sha}",
            )

            qa_result = await self._run_qa(task, engineer_result)
            self.tracker.track_call("qa", qa_result.model, qa_result.tokens, qa_result.latency_ms, qa_result.approved, round_num)
            if qa_result.approved:
                self.event_log.append(task.id, "ReviewPassed", "qa", qa_result.model, "All acceptance criteria met")
                self.event_log.append(task.id, "TaskCompleted", "orchestrator", "", "Terminal state reached")
                break

            self.event_log.append(task.id, "ReviewFailed", "qa", qa_result.model, qa_result.feedback)
        else:
            self.event_log.append(task.id, "TaskFailed", "orchestrator", "", "Max QA rounds exceeded")
```

### `agent/server.py` - HTTP API Server ✅

FastAPI server exposing `/work` and `/health` endpoints. Wraps OpenCode ACP calls.

### `agent/worker.py` - Optional Local Queue Worker ⏳

Optional helper for local queue mode only. It is not required for the base HTTP-orchestrated workflow.

### `agent/git_client.py` - Git Client ⏳

Handles clone/push operations into the central repo. Configured with SSH key for authentication. Each agent clones the repo on startup and pushes changes after each task attempt.

### `agent/main.py` - Entry Point ✅

Starts the OpenCode ACP server + HTTP API server. Configurable via environment variables (`ROLE`, `MODEL`).

### Additional Implemented Modules

The following modules are not described in this plan's original spec but have been implemented as part of the vertical slice:

- **`speedster/events.py`** ✅ — `EventType` enum, phase transitions, terminal event constants
- **`speedster/interfaces.py`** ✅ — `EventStore` and `AgentGateway` protocols for dependency injection
- **`speedster/models.py`** ✅ — `StepResult` dataclass for structured role output
- **`speedster/exceptions.py`** ✅ — Exception hierarchy (`ValidationError`, `OrchestratorError`, etc.)
- **`speedster/response_parser.py`** ✅ — JSON parsing + QA response to `StepResult` conversion
- **`speedster/contracts/`** ✅ — Schema validation modules (`em_breakdown.py`, `engineer_contract.py`, `qa_contract.py`)
- **`speedster/cli/`** ✅ — Standalone CLI validators (6 scripts)

## Harness run input (target repository)

The **target repository** is not part of `task.json` or the EM `breakdown.json`. It is supplied by the **harness** when a run is started, alongside the initial task, as:

- `**repo.url`** — Git clone URL (HTTPS or SSH) for the codebase under work.
- `**repo.default_branch`** — The integration line for this run (e.g. `main`, `develop`). After clone, check out the corresponding remote-tracking branch (e.g. `origin/<default_branch>`); all orchestrator-managed `speedster/<task-id>` branches are created from that base unless the plan specifies otherwise.

The orchestrator records `repo.url` and `repo.default_branch` in durable state (e.g. in the `TaskCreated` event message or a small run header the replay path understands) so recovery and audits know which remote and base branch were used. Agent JSON payloads to Engineer and QA still use `repo.branch` (always `speedster/...` on the task) and `repo.root` (absolute path inside the container) as defined in the input schemas; they do not embed the clone URL or default branch.

## Task File Format

### `tasks/task-001/task.json`

```json
{
  "id": "task-001",
  "status": "pending",
  "description": "Add user authentication endpoint with JWT tokens",
  "priority": "high",
  "created_at": "2025-01-15T10:00:00Z",
  "model_override": null
}
```

### `tasks/task-001/breakdown.json` (generated by EM)

The EM emits a recursive task tree rooted at a single Task object. The full
contract is in `schemas/em_breakdown.schema.json`; every node carries the
implementation-ready fields, and non-leaf nodes nest children under `tasks`.
Illustrative shape:

```json
{
  "id": "task-001",
  "description": "Add user authentication endpoint with JWT tokens.",
  "acceptance_criteria": {
    "functional": ["Login endpoint returns a JWT on valid credentials."],
    "solid": "The implementation adheres to SOLID principles by separating token issuance from the request handler.",
    "yagni_kiss": "The implementation adheres to YAGNI and KISS by reusing the existing config loader instead of adding a JWT-specific one.",
    "testing": "Well-designed unit tests cover token issuance and 401 handling, with minimum unit test coverage of 80%+ for touched modules."
  },
  "context_files": ["src/auth/__init__.py", "src/routes/auth.py", "src/config.py"],
  "context_rationale": "Only these modules need to change to add the JWT login endpoint.",
  "depends_on": [],
  "estimated_context_tokens": 6000,
  "estimated_work_tokens": 20000,
  "complexity_level": "straightforward",
  "target_model_class": "mid-size-25B",
  "status": "pending",
  "qa_rounds": 0,
  "feedback": null,
  "tasks": [
    {
      "id": "task-001-issuer",
      "description": "Add JWT issuer service with deterministic clock injection.",
      "acceptance_criteria": { "...": "..." },
      "context_files": ["src/auth/issuer.py"],
      "context_rationale": "Isolated module for token issuance.",
      "depends_on": [],
      "estimated_context_tokens": 2000,
      "estimated_work_tokens": 8000,
      "complexity_level": "simple",
      "target_model_class": "mid-size-25B",
      "status": "pending",
      "qa_rounds": 0,
      "feedback": null,
      "tasks": []
    }
  ]
}
```

## Workflow

```
Orchestrator starts
       │
       ├── 1. [x] Replay `state/events.csv` (state_projection.py)
       ├── 2. [x] Reconstruct current state for non-terminal tasks
       ├── 3. [ ] Start agent health check loop
       └── 4. [x] Pick pending task from `tasks/`
               │
               ▼
Append `TaskCreated` event  ✅
       │
       ▼
Run EM via HTTP (`/work`)  ✅
       │
       ├── [x] Validate EM output schema
       └── [x] Append `PlanningCompleted`
               │
               ▼
Run Engineer via HTTP (`/work`)  ✅
       │
       ├── [ ] Engineer pushes branch commit (blocked on git integration)
       └── [x] Append `ImplementationCompleted` *(branch + commit SHA pending git)*
               │
               ▼
Run QA via HTTP (`/work`)  ✅
       │
       ├── [x] Review passed  -> append `ReviewPassed`, then `TaskCompleted`
       └── [x] Review failed  -> append `ReviewFailed`, loop to Engineer
```

## Error Handling

- [ ] **Process timeout**: Kill agent after timeout_seconds (default 600), append `TaskFailed` with timeout details
- [ ] **Model errors**: Handled by OpenCode internally; orchestrator checks for empty output and retries with exponential backoff (3 attempts)
- [ ] **Context overflow**: MessageBuilder enforces context window per role; if content exceeds window, chunks are sent sequentially
- [ ] **Git conflicts**: On merge/rebase failure, append `TaskFailed` with conflict details and keep branch for inspection
- [ ] **Agent health failure**: Orchestrator pings agents every 30s; unhealthy agents are retried with a different replica or flagged
- [x] **Invalid output**: OutputValidator checks JSON schema; invalid output triggers retry with error message in prompt
- [x] **Crash recovery**: Event replay restores durable state; in-flight uncommitted edits are discarded by design *(resume logic exists via `speedster main.py resume`)*
- [x] **Event log write failure**: Orchestrator fails fast; no transition is considered complete until event append succeeds

## Prompt Design (system prompts for agents)

Each role has exactly one authoritative system prompt file under `prompts/`; these files are the single source of truth and override anything phrased in this plan.

- [x] EM: `[prompts/em_system_prompt.txt](prompts/em_system_prompt.txt)` — output validated by `[schemas/em_breakdown.schema.json](schemas/em_breakdown.schema.json)` via `[speedster/cli/validate_em_breakdown.py](speedster/cli/validate_em_breakdown.py)`.
- [x] Engineer: `[prompts/engineer_system_prompt.txt](prompts/engineer_system_prompt.txt)` — input validated by `[schemas/engineer_input.schema.json](schemas/engineer_input.schema.json)` and output by `[schemas/engineer_output.schema.json](schemas/engineer_output.schema.json)`, both enforced by `[speedster/contracts/engineer_contract.py](speedster/contracts/engineer_contract.py)` (CLIs `speedster/cli/validate_engineer_input.py`, `speedster/cli/validate_engineer_output.py`).
- [x] QA: `[prompts/qa_system_prompt.txt](prompts/qa_system_prompt.txt)` — input validated by `[schemas/qa_input.schema.json](schemas/qa_input.schema.json)` and output by `[schemas/qa_output.schema.json](schemas/qa_output.schema.json)`, both enforced by `[speedster/contracts/qa_contract.py](speedster/contracts/qa_contract.py)` (CLIs `speedster/cli/validate_qa_input.py`, `speedster/cli/validate_qa_output.py`).

Orchestrator contracts that the prompts rely on:

- Task ids are restricted to `[A-Za-z0-9._-]+` (git-ref-safe) by the EM schema; `repo.branch` is always `speedster/<root-task-id>`.
- **Execution semantics**: every task in the EM breakdown tree — leaf or non-leaf — is dispatched to the Engineer as exactly one invocation. A task becomes schedulable once every descendant has been implemented AND every `depends_on` target has been implemented. Non-leaf tasks are *integration* tasks: their commit wires already-implemented descendants together. Leaves are dispatched first (post-order); the root is dispatched last. The parent/child edge is an implicit structural dependency; `depends_on` therefore never names ancestors or descendants. The validator enforces all of this.
- Each Engineer invocation appends exactly one commit on `repo.branch` with message `<task_id>: <short imperative summary>` (optionally suffixed  `(round <N>)` for rework rounds). No amend, no force-push.
- QA's diff baseline for a dispatched task is `<prev-HEAD>..HEAD` of the task branch — the Engineer's newest commit only, not the cumulative diff of the subtree. The orchestrator owns squash-on-merge at root completion.
- The orchestrator reads the post-push HEAD from git; the Engineer does NOT self-report `commit_sha`.
- `status: "needs_context"` on the Engineer output is a first-class back-channel: the orchestrator re-dispatches EM planning with the requested paths added to `context_files`, rather than terminating the task. `status: "blocked"` is terminal for the task node and requires human or re-plan intervention.
- QA input carries the task node, the post-push `commit` SHA, the `<prev-HEAD>..HEAD` `diff`, the Engineer's JSON output for that commit, and the 1-based `round` counter. QA input schema guarantees `engineer_output.status == "implemented"`; the orchestrator never dispatches QA on `blocked` or `needs_context` outputs.
- QA output maps to event-log transitions deterministically: `status: "approved"` appends `ReviewPassed` and then `TaskCompleted`; `status: "rejected"` appends `ReviewFailed` and re-dispatches the Engineer with `prior_feedback.items = qa_output.rejection_reasons` and `prior_feedback.round = qa_output.round + 1`. The QA `rejection_reasons` list is consumed verbatim and satisfies the Engineer input schema's per-item length and count constraints.
- A single non-`met` verdict in any QA finding (functional/solid/yagni_kiss/testing) forces `status: "rejected"`; the structural validator rejects approval-with-uncertain outputs so the quality-first invariant is enforced end-to-end.
- Flavor-specific Engineer prompt overlays (backend/frontend/mobile/data-ML) are intentionally deferred; they will be reintroduced only when a concrete iteration requires a second prompt surface.

## Implementation Iterations

Each iteration must ship a usable increment, not just scaffolding. The core value is preserved from Iteration 1 onward: **EM, Engineer, and QA are separate roles with independently configurable models**.

**Current status overview:** Iterations 1 and 2 are largely implemented. Iteration 3 (Git) is the primary blocker for a fully functional deploy. Iterations 4-5 are pending. Iteration 6 CLI has been pulled forward and is implemented.

| Iteration | Status | Key blocker |
|-----------|--------|-------------|
| 1: Vertical Slice | ~95% | OpenCode ACP integration (agent server in mock mode) |
| 2: Durable State | ~80% | Crash recovery validation, health heartbeat |
| 3: Git Integration | 0% | `agent/git_client.py`, `speedster/git_handler.py` missing |
| 4: Parallelism | 0% | Deferred |
| 5: Context + Quality | ~10% | Context window enforcement, performance tracker |
| 6: Operations + DX | ~60% | Docker Compose orchestrator service, AGENTS.md, deployment docs |

### Iteration 1: Vertical Slice (single task, single engineer)

Goal: prove the full EM -> Engineer -> QA loop works end-to-end with three different role models.

**Status:** ~95% complete. All modules implemented and tested with 208 passing tests (including E2E HTTP tests). Blocked on OpenCode ACP integration — agent server currently returns mock responses.

Execution plan: to be regenerated by the EM agent against the current recursive schema at `schemas/em_breakdown.schema.json` and committed under `tasks/<task-id>/breakdown.json` when the orchestrator is available.

High-level requirements:

- [x] `pyproject.toml` and minimal dependencies (`pydantic`, `httpx`, `fastapi`, `uvicorn`, `typer`)
- [x] `speedster/config.py` with explicit per-role model mapping (`em.model`, `engineer.model`, `qa.model`)
- [x] `agent/server.py` exposing `/work` and `/health` only (single transport path)
- [x] `speedster/agent_client.py` for orchestrator -> agent HTTP calls
- [x] `speedster/output_validator.py` with strict schemas for EM plan and QA review output
- [x] `speedster/orchestrator.py` minimal state machine: one task -> QA approve/rework loop
- [x] `speedster/event_log.py` append-only CSV event writer + replay reader
- [x] `tasks/task-001/task.json` and one concrete example scenario
- [ ] End-to-end test: task is completed only when QA approves acceptance criteria *(test infrastructure exists; blocked on OpenCode ACP integration — agent server in mock mode)*

Exit criteria:

- [x] Distinct models are actually invoked per role and recorded in logs/metrics
- [x] A single failed QA round can be fed back to Engineer and then pass on next attempt

### Iteration 2: Durable State + Recovery

Goal: make the system restart-safe for multi-hour operation.

**Status:** Core logic implemented. `state_projection.py` and resume logic exist and are wired into the CLI. Crash recovery not yet validated with real scenarios. Health heartbeat missing.

- [x] `speedster/state_projection.py` to rebuild per-task state from `state/events.csv`
- [x] `state/snapshots/` optional periodic state snapshots for faster startup *(directory exists)*
- [x] Resume logic in orchestrator startup (recover non-terminal tasks) *(via `speedster main.py resume`)*
- [ ] Health heartbeat for agents and orchestrator
- [x] Failure handling for agent timeout, invalid output, and temporary network failures *(invalid output retry and httpx retries implemented)*

Exit criteria:

- [ ] Kill orchestrator mid-task, restart, and continue from last persisted step *(resume logic exists but not crash-tested)*
- [ ] No task duplication or lost progress across restart

### Iteration 3: Git Integration + Deterministic Merge

Goal: produce auditable code artifacts with predictable merge behavior.

- [ ] `agent/git_client.py` clone/push support using configured credentials
- [ ] `speedster/git_handler.py` with branch-per-task for deterministic isolation
- [ ] Orchestrator merge flow: approved task branch -> main branch serially
- [ ] Persist diff artifacts for QA context and audit trail

Exit criteria:

- [ ] Branch model validated across repeated task runs
- [ ] Merge conflicts are surfaced clearly and task status moves to `conflict` without corruption

### Iteration 4: Controlled Parallelism

Goal: increase throughput while keeping correctness stable.

- [ ] Optional batching of multiple tasks in FIFO priority order
- [ ] Multiple engineer replicas and queueing strategy
- [ ] Parallel execution of independent tasks
- [ ] Global concurrency cap so review quality remains stable

Exit criteria:

- [ ] Two or more independent tasks run concurrently and complete correctly
- [ ] Per-task QA loop remains isolated under concurrency

### Iteration 5: Context Management + Quality Hardening

Goal: improve correctness at scale without unnecessary complexity.

- [ ] `speedster/message_builder.py` with role-specific context windows and bounded prompt assembly
- [ ] Chunking/summarization protocol for overflow cases (with deterministic handoff format)
- [ ] `speedster/performance_tracker.py` for per-role metrics (tokens, latency, QA rounds, approval rate)
- [ ] Integration and regression tests for retry, resume, and QA feedback loops

Exit criteria:

- [ ] Large tasks no longer fail due to context overflow
- [ ] Metrics show model usage by role and QA loop behavior over time

### Iteration 6: Operations + Developer Experience

Goal: production usability and maintainability.

**Status:** CLI fully implemented and pulled forward from Iteration 6. Docker Compose has agent services but is missing the orchestrator service. AGENTS.md not yet created.

- [x] `speedster/main.py` CLI (`run`, `list`, `resume`, `status`)
- [ ] `docker-compose.yml` for local multi-container deployment *(agent services only; orchestrator service missing)*
- [ ] Documentation (`README.md`, task format docs, troubleshooting) *(README covers setup; deployment guide incomplete)*
- [ ] `AGENTS.md` with role prompt governance and operating guardrails

Exit criteria:

- [ ] New user can boot system and run a sample task from docs
- [ ] Operator can inspect status, resume failed runs, and diagnose conflicts quickly

## Iteration Checklists

Use these as release gates. An iteration is complete only when all checklist items are checked.

### Iteration 1 Checklist (Vertical Slice)

#### Build Checklist

- [x] Role configs support different models for `em`, `engineer`, and `qa`
- [x] Agent HTTP server responds on `/work` and `/health`
- [x] Orchestrator can execute EM -> Engineer -> QA loop for one task
- [x] Output validator rejects malformed EM/Engineer/QA JSON and triggers retry (EM: `speedster/cli/validate_em_breakdown.py`; Engineer: `speedster/cli/validate_engineer_output.py`; QA: `speedster/cli/validate_qa_output.py`)
- [x] Example task input exists and can be executed end-to-end

#### Acceptance Checklist

- [x] Logs show distinct model identifier used per role in a single run
- [x] QA can reject implementation with actionable feedback
- [x] Engineer can re-run with QA feedback and produce updated output
- [x] Task is marked `done` only after QA approval
- [ ] End-to-end run is reproducible across at least 2 consecutive runs *(blocked on OpenCode ACP integration — agent server currently in mock mode)*

### Iteration 2 Checklist (Durable State + Recovery)

#### Build Checklist

- [x] Task state is persisted durably in CSV event log
- [x] Event log schema stays stable and append-only
- [x] Orchestrator startup includes resume/recovery path (`speedster/main.py resume`, `orchestrator.py resume_from_step()`)
- [ ] Agent and orchestrator heartbeat/health status is persisted
- [x] Timeout and transient network error paths are handled deterministically (`_run_with_retry`, `AgentClient` with httpx retries)

#### Acceptance Checklist

- [ ] Forced orchestrator crash mid-task resumes from last durable event *(resume logic exists but crash recovery not validated)*
- [ ] No duplicate terminal completion events after restart
- [ ] No task state regression (cannot move backward to invalid state)
- [ ] Recovery behavior validated on at least 3 restart scenarios

### Iteration 3 Checklist (Git Integration + Deterministic Merge)

#### Build Checklist

- [ ] Agents can clone/pull/push with configured credentials
- [ ] Branch naming is per-task and unique
- [ ] Approved task branches merge serially into main branch
- [ ] Diff artifacts are persisted for QA/audit consumption
- [ ] Conflict state transition is explicit and queryable

#### Acceptance Checklist

- [ ] Two independent tasks produce isolated branches without cross-contamination
- [ ] Conflicting changes produce `conflict` status without data loss
- [ ] Non-conflicting tasks merge in deterministic order
- [ ] Audit trail links task -> branch -> diff -> QA decision

### Iteration 4 Checklist (Controlled Parallelism)

#### Build Checklist

- [ ] Task queue scheduling enforces deterministic dispatch order
- [ ] Engineer worker selection/queueing supports concurrent tasks
- [ ] Concurrency caps prevent over-scheduling
- [ ] Shared state updates are concurrency-safe

#### Acceptance Checklist

- [ ] At least 2 independent tasks run truly in parallel
- [ ] Each task preserves internal order: planning -> implementing -> reviewing
- [ ] Parallel runs produce stable final task state across repeated runs
- [ ] Throughput improves vs Iteration 3 baseline without correctness regressions

### Iteration 5 Checklist (Context + Quality Hardening)

#### Build Checklist

- [ ] Message builder applies role-specific context window limits
- [ ] Overflow strategy (chunk/summarize) uses deterministic handoff format
- [ ] Performance tracker records per-role tokens/latency/approval metrics *(module missing)*
- [x] Retry and QA feedback loop tests cover failure and success paths *(tests pass)*

#### Acceptance Checklist

- [ ] Large-context task completes without context-overflow failure
- [ ] QA loop metrics are queryable by task and by role
- [ ] Retry behavior does not create duplicate state transitions
- [ ] Regression suite passes for retry/resume/QA feedback scenarios

### Iteration 6 Checklist (Operations + DX)

#### Build Checklist

- [x] CLI commands implemented: `run`, `list`, `resume`, `status`
- [ ] Local deployment via `docker-compose.yml` works from clean checkout *(agent services only; orchestrator service missing)*
- [ ] Documentation includes setup, sample run, and failure recovery steps *(README covers setup; deployment guide incomplete)*
- [ ] `AGENTS.md` defines prompt and behavior guardrails by role

#### Acceptance Checklist

- [ ] New developer can complete first run via docs in one session
- [ ] Operator can identify blocked/conflict tasks from CLI status output
- [ ] Resume workflow is validated and documented with example
- [ ] Troubleshooting guidance covers top 5 likely operational failures
