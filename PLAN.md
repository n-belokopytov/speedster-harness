# Autonomous Agent System - Implementation Plan

## Overview

An autonomous agent system with three roles (EM, Engineer, QA) that processes tasks, breaks them down, implements code, and reviews quality. Each role runs as an independent OpenCode container with its own model, communicating via Redis pub/sub and HTTP APIs. Designed for unlimited-token machines with open-weight models, where quality is paramount and operations may span multiple hours.

**Key principles:**
- Unlimited token consumption (no cost constraints) — context window management and token tracking only
- Quality-first — QA has no hard retry cap, iterates until approved
- Multi-hour autonomous operation — checkpoint/recovery, health monitoring, crash resilience
- Model agnostic — OpenCode wraps any model; each role configured with its own
- Fully parallelized — branch-per-group git strategy, orchestrator-managed merge

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Docker Compose Network                         │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   EM         │  │ Engineer     │  │   QA         │           │
│  │  Container   │  │  (N replicas)│  │  Container   │           │
│  │              │  │              │  │              │           │
│  │  OpenCode    │  │  OpenCode    │  │  OpenCode    │           │
│  │  ACP server  │  │  ACP server  │  │  ACP server  │           │
│  │  HTTP API    │  │  HTTP API    │  │  HTTP API    │           │
│  │  Redis client│  │  Redis client│  │  Redis client│           │
│  │  Git client  │  │  Git client  │  │  Git client  │           │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘           │
│         │                 │                  │                   │
│         └─────────────────┼──────────────────┘                   │
│                           │                                      │
│                    ┌──────▼──────┐         ┌──────────────┐      │
│                    │    Redis    │◄────────│   Orchestrator│      │
│                    │  Broker +   │         │   Container   │      │
│                    │  KV Store   │         │              │      │
│                    └─────────────┘         └──────┬───────┘      │
│                                                   │               │
│                                    ┌──────────────▼──────────┐   │
│                                    │  Git Server (GitHub/    │   │
│                                    │  GitLab/self-hosted)    │   │
│                                    │  (repo + SSH)           │   │
│                                    └─────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

## Communication Model

Agents communicate via **hybrid shared state + orchestrator assembly**:

### Artifact Flow

```
Agent A (OpenCode ACP server in container)
         │
         │ writes artifacts to Git branch
         │ reports metadata to Redis
         ▼
tasks/task-001/group-N/
    ├── diff                    ← git diff for orchestrator
    ├── qa-reviews/
    │   └── ses_yyy/review.json ← QA output
    └── checkpoints/
        └── ses_xxx/output.log  ← raw agent session log

Orchestrator reads Redis state + Git artifacts, assembles prompt for next agent
         │
         ▼
Agent B (OpenCode ACP server in container) receives assembled prompt
    - Previous agent's output (via file contents embedded in prompt)
    - Task context + acceptance criteria
    - Role-specific system prompt
    - Context window limits enforced by orchestrator
```

### Redis Key Schema

```
# Agent registration (heartbeat every 30s)
agents:em          → "http://em-agent:8080"
agents:em:health   → {"status":"healthy","last_heartbeat":"2026-04-17T10:00:00Z"}
agents:engineer    → ["http://eng1:8080", "http://eng2:8080", ...]
agents:qa          → "http://qa-agent:8080"

# Task state (versioned for checkpoint/recovery)
tasks:task-001          → {"status":"in_progress","current_group":1,...}
tasks:task-001:breakdown → {"subtasks":[...],"groups":[...],"version":1}
tasks:task-001:group-1  → {"status":"done","branch":"speedster/task-001/group-1"}
tasks:task-001:subtask-N → {"status":"done","qa_rounds":2,...}

# Artifacts
tasks:task-001:group-1:diff → "<git diff between groups>"
tasks:task-001:subtask-N:qa-N → {"approved":false,"feedback":"..."}

# Performance tracking (no upper limit, just tracking)
perf:metrics → {"total_calls":41,"total_tokens":152000,...}
perf:calls:call-001 → {"role":"qa","model":"...","tokens":3200,"latency_ms":4500,"approved":false}

# Checkpoint (for resume after crash)
checkpoint:orchestrator → {"last_checkpoint":"2026-04-17T10:00:00Z","active_tasks":["task-001"]}
```

## File Structure

```
tasks/                          speedster/                    agent/
├── task-001/                   ├── __init__.py               ├── __init__.py
│   ├── task.json               ├── main.py                   ├── main.py        # Entry: starts ACP + HTTP server
│   ├── context/                ├── config.py                 ├── config.py      # Role config + model + Redis
│   │   ├── README.md           ├── orchestrator.py           ├── server.py      # HTTP API (FastAPI) wrapping OpenCode ACP
│   │   └── ...                 ├── redis_client.py           ├── worker.py      # Redis subscriber for async work
│   ├── breakdown.json          ├── agent_client.py           ├── git_client.py  # Clone/push to central repo
│   ├── engineer-output/        ├── task_manager.py           ├── tools/
│   │   └── ses_xxx/            ├── message_builder.py        │   ├── em.yaml        # Read-only + bash (analysis)
│   │       ├── diff            ├── git_handler.py            │   ├── engineer.yaml  # Full tools (read,edit,write,bash)
│   │       └── output.log      ├── performance_tracker.py    │   └── qa.yaml        # Read-only + bash (validation)
│   └── qa-reviews/             ├── output_validator.py       ├── Dockerfile
│       └── ses_yyy/            ├── checkpoint.py             └── requirements.txt
│           └── review.json     └── utils.py
├── task-002/
│   ├── task.json
│   └── context/
│       └── ...
```

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
  redis:
    image: redis:7-alpine
    volumes: ["redis-data:/data"]

  em-agent:
    build:
      context: ./agent
      args:
        - ROLE=em
        - MODEL=vllm/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K
    environment:
      - REDIS_URL=redis://redis:6379
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
      - REDIS_URL=redis://redis:6379
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
      - REDIS_URL=redis://redis:6379
      - GIT_SSH_KEY=/secrets/gitkey
      - TOOLS_CONFIG=/etc/opencode/tools/qa.yaml
    volumes: ["gitkey:/secrets"]

  orchestrator:
    build: ./speedster
    environment:
      - REDIS_URL=redis://redis:6379
      - GIT_SSH_KEY=/secrets/gitkey
    volumes: ["gitkey:/secrets"]
    depends_on: [em-agent, engineer, qa-agent]

volumes:
  redis-data:
  gitkey:
```

## Module Descriptions

### `speedster/config.py` - Configuration Models

```python
class ModelConfig(BaseModel):
    """Model identifier in OpenCode format: provider/model_name"""
    model: str  # e.g. "vllm/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K"
    variant: str | None = None  # e.g. "high", "max", "minimal"
    context_window: int = 131072  # per-role context window limit

class RoleConfig(BaseModel):
    model: ModelConfig
    system_prompt: str
    tools: list[str] = ["read", "edit", "write", "bash", "grep", "glob", "webfetch"]
    timeout_seconds: int = 600  # per-call timeout for multi-hour operations

class AgentEndpoint(BaseModel):
    role: str
    url: str  # e.g., "http://em-agent:8080"
    status: str = "unknown"  # "healthy", "unhealthy", "unknown"

class RedisConfig(BaseModel):
    url: str = "redis://localhost:6379"
    max_connections: int = 10

class AgentConfig(BaseModel):
    roles: dict[str, RoleConfig] = {"em": ..., "engineer": ..., "qa": ...}
    redis: RedisConfig = RedisConfig()
    max_qa_rounds: int = 20  # quality-first: no hard limit, but cap for safety
    context_windows: dict[str, int] = {"em": 32768, "engineer": 131072, "qa": 32768}
    task_dir: Path = Path("tasks")
    # Performance tracking (no budget cap, just tracking)
    track_performance: bool = True
```

### `speedster/redis_client.py` - Redis Client

Pub/sub subscriber + KV operations + health heartbeats. Manages agent registration, task state persistence, and checkpoint saving.

### `speedster/checkpoint.py` - Checkpoint Manager

Formalizes Redis as a durable state machine. Every step (EM done, subtask-1 started, QA-1 done, etc.) persists to Redis with a versioned key. On restart, orchestrator scans for non-terminal tasks and resumes from the last persisted step.

```python
class CheckpointManager:
    def save_checkpoint(self, task_id, state):
        """Save task state to Redis for crash recovery."""
        data = {
            "task_id": task_id,
            "state": state,
            "timestamp": now(),
            "retries": self._get_retry_count(task_id, state)
        }
        redis.setex(f"checkpoint:{task_id}", 3600, json.dumps(data))

    def resume(self):
        """On startup, find non-terminal tasks and resume from checkpoint."""
        active = redis.smembers("checkpoint:orchestrator:active_tasks")
        for task_id in active:
            cp = redis.get(f"checkpoint:{task_id}")
            if cp and cp["state"] not in terminal_states:
                yield resume_from_state(task_id, cp)
```

### `speedster/output_validator.py` - Output Validator

Every agent output is validated against a JSON schema before the orchestrator consumes it. Invalid output triggers a retry with the error in the prompt.

```python
class OutputValidator:
    BREAKDOWN_SCHEMA = {...}
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

### `speedster/performance_tracker.py` - Performance Tracker

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

### `speedster/agent_client.py` - HTTP Agent Client

Client to call remote agent APIs. Handles connection pooling, retries on unhealthy agents, and health check integration.

### `speedster/task_manager.py` - Task Management (Redis-backed)

Replaces filesystem-based task management. Reads/writes task state from Redis. Watches for new tasks via Redis pub/sub (no file system watching).

### `speedster/git_handler.py` - Git Operations (Remote Repo)

Branch-per-group git strategy with orchestrator-managed merge.

```python
class GitHandler:
    def create_group_branch(self, task_id: str, group_num: int) -> str:
        """Create isolated branch for parallel group: speedster/task-{id}/group-{n}"""
        ...

    def merge_group(self, group_branch: str) -> bool:
        """Merge group branch into main task branch. Returns False if conflicts."""
        ...

    def get_group_diff(self, group_branch: str) -> str:
        """Get git diff between groups for QA context."""
        ...

    def clone_repo(self, branch: str, target_dir: Path):
        """Clone repo into agent working directory."""
        ...

    def push_changes(self, branch: str, commit_msg: str):
        """Push changes from agent container to central repo."""
        ...
```

### `speedster/message_builder.py` - Prompt Assembly with Context Window Enforcement

Orchestrator constructs each agent's prompt by:
1. Loading relevant context from Redis (breakdown.json, acceptance criteria, diffs, feedback)
2. Embedding previous artifacts (e.g., EM's breakdown, QA's feedback)
3. Respecting context window limits per role
4. Chunking if content exceeds window

```python
class MessageBuilder:
    def __init__(self, context_windows):
        self.context_windows = context_windows  # {"em": 32768, "engineer": 131072, "qa": 32768}

    def build_em_prompt(self, task: Task, codebase_context: str) -> str:
        """EM receives: system prompt + task description + targeted codebase scan results"""
        ...

    def build_engineer_prompt(self, subtask: SubTask, context_files_content: dict[str, str]) -> str:
        """Engineer receives: system prompt + subtask details + context files (chunked if needed)"""
        ...

    def build_qa_prompt(self, subtask: SubTask, diff: str, context_files_content: dict[str, str]) -> str:
        """QA receives: system prompt + subtask details + acceptance criteria + diff + changed files only"""
        ...

    def build_feedback_prompt(self, subtask: SubTask, qa_feedback: str, diff: str) -> str:
        """Engineer receives: system prompt + subtask details + acceptance criteria + previous diff + QA feedback"""
        ...

    def _chunked_prompt(self, base_prompt: str, content: dict[str, str], max_tokens: int) -> list[str]:
        """Split content into chunks if it exceeds context window. Agent processes sequentially."""
        ...
```

### `speedster/orchestrator.py` - Workflow Orchestrator (State Machine)

```python
class Orchestrator:
    def __init__(self, config: AgentConfig):
        self.redis = RedisClient(config.redis)
        self.agent_client = AgentClient(self.redis)
        self.task_manager = TaskManager(self.redis)
        self.git_handler = GitHandler()
        self.checkpoint = CheckpointManager(self.redis)
        self.message_builder = MessageBuilder(config.context_windows)
        self.validator = OutputValidator()
        self.tracker = PerformanceTracker()

    async def run(self):
        # 1. Connect to Redis
        # 2. Subscribe to tasks queue
        # 3. Load checkpoint (resume if restarted)
        # 4. Start health check loop (ping agents every 30s)
        # 5. Watch for new tasks (pub/sub from Redis)

    async def process_task(self, task: Task):
        self.checkpoint.save(task.id, "planning")

        # EM breakdown (sequential, via HTTP)
        breakdown = await self._run_em(task)
        self.checkpoint.save(task.id, "breakdown-done")

        # Topological sort → parallel groups
        groups = topological_sort(breakdown.subtasks)

        # Execute groups in order, groups in parallel
        for i, group in enumerate(groups):
            self.checkpoint.save(task.id, f"group-{i}-started")
            await asyncio.gather(*[
                self._process_subtask(subtask) for subtask in group
            ])
            # Merge group after all subtasks complete
            merged = await self.git_handler.merge_group(f"speedster/{task.id}/group-{i}")
            if not merged:
                # Conflict resolution or manual intervention needed
                self.task_manager.update_status(task.id, "conflict")
                break

            self.checkpoint.save(task.id, f"group-{i}-done")

        self.checkpoint.save(task.id, "done")
        self.task_manager.update_status(task.id, "done")

    async def _process_subtask(self, subtask: SubTask):
        # Engineer implements (via HTTP to engineer replicas)
        engineer_result = await self._run_engineer(subtask)
        self.checkpoint.save(subtask.id, "engineer-done")

        # QA reviews with feedback loop (no hard cap, quality-first)
        for round_num in range(self.config.max_qa_rounds):
            qa_result = await self._run_qa(subtask, engineer_result)
            self.tracker.track_call("qa", qa_result.model, qa_result.tokens, qa_result.latency_ms, qa_result.approved, round_num)
            self.checkpoint.save(subtask.id, f"qa-round-{round_num}")

            if qa_result.approved:
                self.task_manager.update_subtask_status(subtask.id, "done")
                break

            # Feedback: engineer re-implements
            subtask.feedback = qa_result.feedback
            engineer_result = await self._run_engineer(subtask)
            self.checkpoint.save(subtask.id, f"engineer-fix-{round_num}")
        else:
            # Max rounds exceeded — task rejected
            self.task_manager.update_subtask_status(subtask.id, "rejected")
```

### `agent/server.py` - HTTP API Server

FastAPI server exposing `/work` and `/health` endpoints. Wraps OpenCode ACP calls.

### `agent/worker.py` - Redis Subscriber

Background worker that subscribes to Redis pub/sub channels for work items. Picks up tasks and delegates to `/work` endpoint.

### `agent/git_client.py` - Git Client

Handles clone/push operations into the central repo. Configured with SSH key for authentication. Each agent clones the repo on startup and pushes changes after each subtask.

### `agent/main.py` - Entry Point

Starts the OpenCode ACP server + HTTP API server + Redis heartbeat. Configurable via environment variables (`ROLE`, `MODEL`, `REDIS_URL`).

## Task File Format

### `tasks/task-001/task.json`

```json
{
  "id": "task-001",
  "status": "pending",
  "description": "Add user authentication endpoint with JWT tokens",
  "priority": "high",
  "created_at": "2025-01-15T10:00:00Z",
  "model_override": null,
  "checkpoint": null
}
```

### `tasks/task-001/breakdown.json` (generated by EM)

```json
{
  "task_id": "task-001",
  "subtasks": [
    {
      "id": "task-001-1",
      "description": "Create JWT authentication service module",
      "acceptance_criteria": ["Token generation", "Token validation", "Expiration handling"],
      "context_files": ["src/auth/", "src/config.py"],
      "depends_on": [],
      "parallel_group": 0,
      "status": "pending",
      "qa_rounds": 0,
      "feedback": null
    },
    {
      "id": "task-001-2",
      "description": "Create /api/auth/login endpoint",
      "acceptance_criteria": ["Accepts credentials", "Returns JWT", "Returns 401 on failure"],
      "context_files": ["src/routes/", "src/auth/"],
      "depends_on": ["task-001-1"],
      "parallel_group": 1,
      "status": "pending",
      "qa_rounds": 0,
      "feedback": null
    }
  ]
}
```

## Workflow

```
Orchestrator starts
       │
       ├── 1. Connect to Redis
       ├── 2. Subscribe to tasks queue
       ├── 3. Load checkpoint (resume if restarted)
       └── 4. Start health check loop (ping agents every 30s)
               │
               ▼
New task detected (watch or Redis pub/sub)
       │
       ▼
┌─────────────────────────────────────────────┐
│ MessageBuilder.build_em_prompt()             │
│  - Orchestrator scans relevant files first   │
│  - Passes targeted subset to EM              │
│  - Respects EM's context window              │
│  - Sends via HTTP → em-agent:8080/work       │
└──────────┬────────────────────────────────────┘
           │
           ▼
┌─────────────┐
│   EM role    │  ← HTTP → em-agent:8080/work
│  breakdown   │     Reads relevant files via OpenCode tools
│             │     Writes breakdown.json to output
└──────┬──────┘
       │ Orchestrator receives output
       │
       ├── Validate against JSON schema
       │     └── Invalid? Retry with error in prompt
       │
       ├── Save checkpoint to Redis
       │
       ▼
┌──────────────────┐
│  Topological sort │
│  → parallel groups│
└──────┬───────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  Group N (subtasks with no unmet deps)      │
│                                             │
│  GitHandler.create_group_branch()           │
│  Creates: speedster/task-XXX/group-N        │
│                                             │
│  ┌──────────────────────┐ ┌──────────────┐  │
│  │ MessageBuilder.build │ │ MessageBuild │  │
│  │ _engineer_prompt()   │ │ er.build()   │  │  ← Parallel via replicas
│  └──────────┬───────────┘ └──────┬───────┘  │
│             │                    │           │
│             ▼                    ▼           │
│  ┌──────────┐    ┌──────────┐               │
│  │ Engineer │    │ Engineer │    ...        │  ← HTTP → replicas
│  │ (sub 1)  │    │ (sub 2)  │               │
│  └────┬─────┘    └────┬─────┘               │
│       │ works on       │                      │
│       │ group branch   │                      │
│       │ pushes to repo │                      │
│  ┌────▼─────┐    ┌────▼─────┐               │
│  │MessageBuild│  │MessageBuild│              │
│  │er.build_qa│  │er.build_qa│               │
│  │_prompt()  │  │_prompt()  │               │
│  └────┬─────┘    └────┬─────┘               │
│       │               │                      │
│  ┌────▼─────┐    ┌────▼─────┐               │
│  │   QA     │    │   QA     │    ...        │  ← HTTP → qa-agent
│  │ review   │    │ review   │               │
│  └────┬─────┘    └────┬─────┘               │
│       │ writes:      │                      │
│       │ qa-reviews/  │                      │
│       │ to Redis     │                      │
│  ┌────▼─────┐    ┌────▼─────┐               │
│  │Approved? │    │Approved? │               │
│  └────┬─────┘    └────┬─────┘               │
│ Yes──┘│              │┌───┘ No               │
│       ▼              ▼                       │
│  ┌─────────────────────────┐                 │
│  │  Feedback loop           │                 │
│  │  (max 20 rounds,         │                 │
│  │   quality-first)         │                 │
│  │                         │                 │
│  │  MessageBuilder.build   │                 │
│  │  _feedback_prompt()     │                 │
│  │  (diff + QA feedback)   │                 │
│  │         │               │                 │
│  │         ▼               │                 │
│  │  ┌──────────┐          │                 │
│  │  │ Engineer │          │                 │
│  │  │ re-fix   │          │                 │
│  │  └────┬─────┘          │                 │
│  │       │                │                 │
│  │  ┌────▼─────┐          │                 │
│  │  │   QA     │          │                 │
│  │  │ review   │          │                 │
│  │  └────┬─────┘          │                 │
│  └───────┼────────────────┘                 │
│          │                                   │
│          ▼ Group N complete                  │
│          GitHandler.merge_group()            │
│          (resolve conflicts or fail)         │
│          Save checkpoint to Redis            │
└──────────┼──────────────────────────────────┘
           │
           ▼
┌─────────────┐
│  Checkpoint  │  ← Save final state to Redis
│  + notify    │
└─────────────┘
```

## Error Handling

- **Process timeout**: Kill agent after timeout_seconds (default 600 for multi-hour ops), mark subtask as `rejected` with timeout details
- **Model errors**: Handled by OpenCode internally; orchestrator checks for empty output and retries with exponential backoff (3 attempts)
- **Context overflow**: MessageBuilder enforces context window per role; if content exceeds window, chunks are sent sequentially
- **Git conflicts**: On merge, if conflicts exist, marks task as `conflict` (not rejected) — user can inspect branch
- **Deadlock detection**: If topological sort detects cycles in subtask dependencies, logs error and rejects task
- **Agent health failure**: Orchestrator pings agents every 30s; unhealthy agents are retried with a different replica or flagged
- **Invalid output**: OutputValidator checks JSON schema; invalid output triggers retry with error message in prompt
- **Crash recovery**: CheckpointManager persists state after each step; on restart, orchestrator resumes from last checkpoint
- **Redis failure**: Orchestrator fails fast with clear error message (no silent degradation)

## Prompt Design (system prompts for agents)

Agents are configured with these system prompts:

### EM Agent
```
You are an Engineering Manager. Given a task description and the codebase,
break it down into independent subtasks that can be parallelized.

Rules:
- Each subtask must fit within context window limits
- Identify explicit dependencies between subtasks
- Group independent subtasks for parallel execution
- Define clear, testable acceptance criteria for each
- List only files that are relevant context
- Optimize for maximum parallel group count

Output: a structured JSON breakdown with subtasks, dependencies, and acceptance criteria.
```

### Engineer Agent
```
You are a Software Engineer. Implement the following subtask.

Input:
- Subtask description
- Acceptance criteria (must all be met)
- Context files (relevant code to read)

Your workflow:
1. Read the context files listed
2. Implement the changes using file edits
3. Report what was changed and how each acceptance criterion is met

Use your tools: read, edit, write, bash, grep, glob.

IMPORTANT: You are working on a shared branch. Only modify files relevant to your subtask.
Push your changes to the branch after completing.
```

### QA Agent
```
You are a QA Engineer. Review the implementation against:
1. Acceptance criteria - are ALL criteria met?
2. Code quality - patterns, edge cases, error handling, style

Your workflow:
1. Read the context files and the implementation changes (via diff)
2. Check each acceptance criterion explicitly
3. Review code quality

Output: approved: true/false with specific actionable feedback (no vague comments).
If approved: false, provide numbered feedback items the engineer can act on.

Use your tools: read, grep, glob, bash.

IMPORTANT: You only receive the diff + changed files, not the entire codebase.
```

## Implementation Phases

### Phase 1: Core Infrastructure + Redis State Machine
- [ ] `pyproject.toml` with dependencies (`pydantic`, `typer`, `rich`, `watchfiles`, `aiofiles`, `httpx`, `redis`, `fastapi`, `uvicorn`)
- [ ] `speedster/config.py` - Pydantic models (config, roles, model mapping, context windows, Redis config)
- [ ] `speedster/redis_client.py` - Pub/sub + KV + heartbeat management
- [ ] `speedster/checkpoint.py` - Crash recovery state machine
- [ ] `speedster/output_validator.py` - JSON schema validation
- [ ] `speedster/performance_tracker.py` - Metrics collection (no budget cap)

### Phase 2: Agent Container + Communication
- [ ] `agent/server.py` - HTTP API (FastAPI) wrapping OpenCode ACP
- [ ] `agent/worker.py` - Redis subscriber for async work
- [ ] `agent/git_client.py` - Clone/push to central repo
- [ ] `agent/config.py` - Role-specific tool permissions + model config
- [ ] `speedster/agent_client.py` - HTTP client to call remote agents
- [ ] `agent/Dockerfile` - Container image with OpenCode + agent code
- [ ] `agent/requirements.txt`

### Phase 3: Task Management + Git
- [ ] `speedster/task_manager.py` - Redis-backed task state
- [ ] `speedster/git_handler.py` - Branch-per-group, merge conflict resolution
- [ ] `speedster/message_builder.py` - Prompt assembly with context window enforcement + chunking
- [ ] `speedster/utils.py` - Token counting, topological sort, targeted scanning
- [ ] Task directory structure + example task in `tasks/`

### Phase 4: Roles + Orchestration
- [ ] `speedster/orchestrator.py` - Full workflow engine (EM → parallel groups → QA loop → merge)
- [ ] Role integration (EM orchestrates breakdown, Engineer orchestrates implementation, QA orchestrates review loop)
- [ ] Health check integration

### Phase 5: CLI + Docker
- [ ] `speedster/main.py` - CLI with typer (`run`, `list`, `init`, `reset`)
- [ ] `docker-compose.yml`
- [ ] `agent/Dockerfile`
- [ ] Integration test: end-to-end single task

### Phase 6: Polish
- [ ] Update `README.md` with agent documentation
- [ ] Example task + breakdown in `tasks/`
- [ ] `AGENTS.md` for ongoing agent instructions
