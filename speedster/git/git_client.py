"""Git client — shared between agent and orchestrator layers.

Re-exports from agent.git_client which contains the canonical
implementation (kept in agent/ so agent containers can import it).
"""

from agent.git_client import GitClient, GitError

__all__ = ["GitClient", "GitError"]
