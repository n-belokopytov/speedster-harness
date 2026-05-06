# AGENTS.md — Role Prompt Governance and Operating Guardrails

This document defines the rules for how each agent role operates within the Speedster harness. It is the single source of truth for prompt governance, model selection, and quality expectations.

## Role Definitions

Each role has a distinct purpose, prompt, output schema, and model class. The orchestrator routes tasks to the appropriate agent based on the current workflow phase.

### EM (Engineering Manager)

| Attribute | Value |
|---|---|
| **System prompt** | `prompts/em_system_prompt.txt` |
| **Output schema** | `speedster/schemas/em_breakdown.schema.json` |
| **Validator CLI** | `speedster/cli/validate_em_breakdown.py` |
| **Normalizer CLI** | `speedster/cli/normalize_em_breakdown.py` |
| **Model class** | Mid-size (25B range) |
| **Timeout** | 600s |

**Purpose:** Decompose a task description into a structured breakdown with acceptance criteria, subtasks, dependency graph, and context file list.

**Guardrails:**
- Output must be valid JSON matching the schema
- `acceptance_criteria.functional` must have at least one criterion
- `target_model_class` must be one of: `mid-size-25B`, `small-3B`, `large-70B`
- `complexity_level` must be one of: `simple`, `moderate`, `complex`, `very_complex`
- `depends_on` must reference valid subtask IDs within the same breakdown
- EM re-runs are triggered when the engineer signals `needs_context`

### Engineer

| Attribute | Value |
|---|---|
| **System prompt** | `prompts/engineer_system_prompt.txt` |
| **Input schema** | `speedster/schemas/engineer_input.schema.json` |
| **Output schema** | `speedster/schemas/engineer_output.schema.json` |
| **Input validator** | `speedster/cli/validate_engineer_input.py` |
| **Output validator** | `speedster/cli/validate_engineer_output.py` |
| **Contract library** | `speedster/contracts/engineer_contract.py` |
| **Model class** | Mid-size to large (25B-70B range) |
| **Timeout** | 600s |

**Purpose:** Implement the task per the EM breakdown, push code to a dedicated branch, and return structured output with evidence.

**Guardrails:**
- `status` must be one of: `implemented`, `blocked`, `needs_context`
- `branch` must follow pattern `speedster/<task-id>`
- When `status` is `implemented`, `files_changed` must be non-empty
- When `status` is `blocked`, `blocked_reason` must be non-empty
- When `status` is `needs_context`, `requested_context` must be non-empty
- `acceptance_evidence` must address all four categories: `functional`, `solid`, `yagni_kiss`, `testing`
- Engineer may be re-dispatched with QA feedback up to `max_qa_rounds` times

### QA (Quality Assurance)

| Attribute | Value |
|---|---|
| **System prompt** | `prompts/qa_system_prompt.txt` |
| **Input schema** | `speedster/schemas/qa_input.schema.json` |
| **Output schema** | `speedster/schemas/qa_output.schema.json` |
| **Input validator** | `speedster/cli/validate_qa_input.py` |
| **Output validator** | `speedster/cli/validate_qa_output.py` |
| **Contract library** | `speedster/contracts/qa_contract.py` |
| **Model class** | Mid-size (25B range) |
| **Timeout** | 600s |

**Purpose:** Review engineer output against acceptance criteria and either approve or reject with actionable feedback.

**Guardrails:**
- `status` must be one of: `approved`, `rejected`
- When `status` is `approved`, all `findings` verdicts must be `met`
- When `status` is `rejected`, `rejection_reasons` must be non-empty
- `findings` must address all four categories: `functional`, `solid`, `yagni_kiss`, `testing`
- Each functional finding must map to a criterion from the EM breakdown

## Prompt Governance

### System Prompt Files

System prompts are stored under `prompts/` and are the single source of truth:

- `prompts/em_system_prompt.txt` — loaded at agent startup
- `prompts/engineer_system_prompt.txt` — loaded at agent startup
- `prompts/qa_system_prompt.txt` — loaded at agent startup

Changes to system prompts require:
1. Update the prompt file
2. Verify output still validates against the schema
3. Update `AGENTS.md` if guardrails change
4. Run full test suite: `pytest tests/`

### Model Configuration

Models are configured via environment variables per role. Each agent reads its model from the corresponding env var:

- **EM agent:** `EM_MODEL`
- **Engineer agent:** `ENGINEER_MODEL`
- **QA agent:** `QA_MODEL`

If a role's model env var is empty, `AgentConfig.validate()` raises a `ValueError` and the agent fails to start.

## Workflow Contract

The orchestrator enforces this sequence for each task:

```
TaskCreated -> PlanningCompleted -> ImplementationCompleted -> ReviewPassed -> TaskCompleted
                                                              -> ReviewFailed -> (retry to Engineer)
```

### Retry Behavior

- **QA rejection:** Engineer is re-dispatched with prior QA feedback appended to the prompt
- **Max QA rounds:** Configurable via `max_qa_rounds` in `AgentConfig`. Default is `None` (unlimited). Set to 20 for production guardrails.
- **Validation failure:** Agent is retried once with the validation error appended to the prompt
- **Timeout:** Agent subprocess is killed after 600s. Task moves to `TaskFailed`.

### Git Workflow (Iteration 3)

1. After EM planning, orchestrator prepares branch `speedster/<task-id>`
2. Engineer pushes code to the branch (via agent `git_client.py`)
3. Orchestrator records branch and commit SHA in `ImplementationCompleted` event
4. If QA approves, orchestrator merges branch into default branch
5. Merge is serial to ensure deterministic order

## Operating Procedures

### Starting Agents

```bash
# Start EM agent
ROLE=em EM_MODEL="vllm/Qwen3.6-35B" PORT=8081 python agent/main.py

# Start Engineer agent
ROLE=engineer ENGINEER_MODEL="vllm/Qwen3.6-70B" PORT=8082 python agent/main.py

# Start QA agent
ROLE=qa QA_MODEL="vllm/Qwen3.6-35B" PORT=8083 python agent/main.py
```

### Running the Orchestrator

```bash
# Process a specific task
speedster run --task-id task-001

# Resume from a specific step
speedster resume --task-id task-001 --step engineer

# List all tasks and status
speedster list

# Show status for a specific task
speedster status --task-id task-001
```

### Docker Compose Deployment

```bash
# Start all agents
docker compose up -d em-agent engineer-agent qa-agent

# Run orchestrator locally
speedster run --task-id task-001
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Agent returns 500 on `/work` | ACP subprocess failed | Check `opencode` CLI is on PATH and model is reachable |
| Validation errors on EM output | Schema mismatch | Run `speedster/cli/validate_em_breakdown.py` locally to debug |
| QA rejects everything | Prompt too strict | Review `prompts/qa_system_prompt.txt` criteria |
| Git merge conflicts | Branch divergence | `git fetch origin main && git rebase origin/main` on task branch |
| Task stuck in `pending` | Orchestrator crashed | Run `speedster resume --task-id <id>` to recover |
| Empty event log | Wrong `state/events.csv` path | Check `AgentConfig.event_log.path` |
