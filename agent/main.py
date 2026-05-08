"""Agent entry point.

Starts the FastAPI HTTP server with the configured role and model.
Environment variables:
    ROLE: Agent role (em, engineer, qa)
    MODEL: Model identifier (e.g., vllm/default)
    HOST: Bind address (default: 0.0.0.0)
    PORT: Bind port (default: 8080)
    GIT_SSH_KEY: Path to Git SSH key for authentication
    REPO_ROOT: Path to cloned repository workspace
"""

from __future__ import annotations

import logging
import sys

from agent.config import AgentConfig
from agent.server import AgentServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the agent server."""

    config = AgentConfig()

    try:
        config.validate()
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    logger.info(
        "Starting %s agent with model %s on %s",
        config.role,
        config.model,
        config.url,
    )

    server = AgentServer(config)
    server.run()


if __name__ == "__main__":
    main()
