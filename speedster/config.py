"""Configuration models for the orchestrator and agents."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


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
    snapshot_dir: Path = Path("state/snapshots")
    fsync_on_append: bool = True


class AgentConfig(BaseModel):
    """Top-level orchestrator configuration."""

    connectivity: ConnectivityConfig = Field(default_factory=ConnectivityConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    max_qa_rounds: int | None = None  # None = unlimited; int = circuit breaker
    track_performance: bool = True
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


class RunConfig(BaseModel):
    """Harness-supplied run parameters."""

    repo_url: str
    repo_default_branch: str = "main"
    task_id: str
    config: AgentConfig | None = None


def default_config() -> AgentConfig:
    """Build a default AgentConfig with sensible defaults."""

    return AgentConfig()
