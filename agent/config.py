"""Agent configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """Configuration for an agent container."""

    role: str = field(default_factory=lambda: os.getenv("ROLE", "em"))
    model: str = field(default_factory=lambda: os.getenv("MODEL", "vllm/default"))
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8080")))
    git_ssh_key: str = field(
        default_factory=lambda: os.getenv("GIT_SSH_KEY", "")
    )
    repo_root: str = field(
        default_factory=lambda: os.getenv("REPO_ROOT", "/workspace")
    )
    repo_url: str = field(
        default_factory=lambda: os.getenv("REPO_URL", "")
    )
    mock_mode: bool = field(
        default_factory=lambda: os.getenv("MOCK_MODE", "1") == "1"
    )

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def validate(self) -> None:
        """Validate configuration."""

        valid_roles = {"em", "engineer", "qa"}
        if self.role not in valid_roles:
            raise ValueError(
                f"Invalid role: {self.role}. Must be one of {valid_roles}"
            )

        if not self.model:
            raise ValueError("MODEL environment variable is required")
