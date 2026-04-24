"""Configuration models for the orchestrator and agents."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """Model identifier in OpenCode format: provider/model_name"""

    model: str  # e.g. "vllm/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K"
    variant: str | None = None  # e.g. "high", "max", "minimal"


class RoleConfig(BaseModel):
    """Per-role configuration: model, prompt, tools, timeout."""

    model: ModelConfig
    system_prompt: str
    tools: list[str] = [
        "read",
        "edit",
        "write",
        "bash",
        "grep",
        "glob",
        "webfetch",
    ]
    timeout_seconds: int = 600


class AgentEndpoint(BaseModel):
    """Network endpoint for a remote agent container."""

    role: str
    url: str  # e.g. "http://em-agent:8080"
    status: str = "unknown"  # "healthy", "unhealthy", "unknown"


class EventLogConfig(BaseModel):
    """Configuration for the durable CSV event log."""

    path: Path = Path("state/events.csv")
    snapshot_dir: Path = Path("state/snapshots")
    fsync_on_append: bool = True


class AgentConfig(BaseModel):
    """Top-level orchestrator configuration."""

    roles: dict[str, RoleConfig] = Field(default_factory=dict)
    event_log: EventLogConfig = Field(default_factory=EventLogConfig)
    max_qa_rounds: int | None = None  # None = unlimited; int = circuit breaker
    context_windows: dict[str, int] = {
        "em": 32768,
        "engineer": 131072,
        "qa": 32768,
    }
    task_dir: Path = Path("tasks")
    track_performance: bool = True
    repo_url: str | None = None
    repo_default_branch: str | None = None
    em_url: str = Field(
        default_factory=lambda: os.getenv(
            "EM_AGENT_URL", "http://localhost:8081"
        )
    )
    eng_url: str = Field(
        default_factory=lambda: os.getenv(
            "ENG_AGENT_URL", "http://localhost:8082"
        )
    )
    qa_url: str = Field(
        default_factory=lambda: os.getenv(
            "QA_AGENT_URL", "http://localhost:8083"
        )
    )


class RunConfig(BaseModel):
    """Harness-supplied run parameters."""

    repo_url: str
    repo_default_branch: str = "main"
    task_id: str
    model_overrides: dict[str, str] = Field(default_factory=dict)
    config: AgentConfig | None = None


def load_role_prompt(prompt_path: Path) -> str:
    """Read a system prompt file and return its contents."""

    return prompt_path.read_text(encoding="utf-8")


def default_config(prompts_dir: Path | None = None) -> AgentConfig:
    """Build a default AgentConfig with sensible defaults.

    Loads system prompts from the given prompts directory if available.
    """

    cfg = AgentConfig()

    if prompts_dir and prompts_dir.is_dir():
        prompt_map = {
            "em": prompts_dir / "em_system_prompt.txt",
            "engineer": prompts_dir / "engineer_system_prompt.txt",
            "qa": prompts_dir / "qa_system_prompt.txt",
        }

        for role, path in prompt_map.items():
            if path.is_file():
                system_prompt = load_role_prompt(path)
                cfg.roles[role] = RoleConfig(
                    model=ModelConfig(model="vllm/default"),
                    system_prompt=system_prompt,
                )

    return cfg
