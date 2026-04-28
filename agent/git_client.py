"""Git client for agent containers — re-exported from shared module.

Backwards compatibility shim. New code should import from
speedster.git.git_client directly.
"""

from speedster.git.git_client import GitClient, GitError

__all__ = ["GitClient", "GitError"]
