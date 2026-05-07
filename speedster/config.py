"""Configuration models for the orchestrator and agents."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """Model identifier in OpenCode format: provider/model_name"""

    model: str  # e.g. "vllm/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q6_K"


class RoleConfig(BaseModel):
    """Per-role configuration: model, prompt, tools, timeout."""

    model: ModelConfig
    system_prompt: str


class RolesConfig(BaseModel):
    """Per-role configuration mapping."""

    roles: dict[str, RoleConfig] = Field(default_factory=dict)


class ConnectivityConfig(BaseModel):
    """Agent endpoint URLs."""

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


class StorageConfig(BaseModel):
    """Persistent storage configuration."""

    event_log: EventLogConfig = Field(default_factory=lambda: EventLogConfig())
    task_dir: Path = Path("tasks")


class EventLogConfig(BaseModel):
    """Configuration for the durable CSV event log."""

    path: Path = Path("state/events.csv")


class AgentConfig(BaseModel):
    """Top-level orchestrator configuration."""

    roles: RolesConfig = Field(default_factory=RolesConfig)
    connectivity: ConnectivityConfig = Field(default_factory=ConnectivityConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    max_qa_rounds: int | None = None  # None = unlimited; int = circuit breaker
    repo_url: str | None = Field(
        default_factory=lambda: os.getenv("REPO_URL", "") or None
    )
    git_ssh_key: str | None = Field(
        default_factory=lambda: os.getenv("GIT_SSH_KEY", "") or None
    )
    repo_default_branch: str | None = Field(
        default_factory=lambda: os.getenv("REPO_DEFAULT_BRANCH", "") or None
    )

    @property
    def event_log(self) -> EventLogConfig:
        return self.storage.event_log

    @property
    def task_dir(self) -> Path:
        return self.storage.task_dir

    @property
    def em_url(self) -> str:
        return self.connectivity.em_url

    @property
    def eng_url(self) -> str:
        return self.connectivity.eng_url

    @property
    def qa_url(self) -> str:
        return self.connectivity.qa_url


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
                cfg.roles.roles[role] = RoleConfig(
                    model=ModelConfig(model="vllm/default"),
                    system_prompt=system_prompt,
                )

    return cfg
