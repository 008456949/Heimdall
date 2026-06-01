"""
interceptor/git_context.py — detect active git repo + branch.

Polls the frontmost app's working directory via macOS APIs,
then resolves the git context for that path.
Falls back gracefully when no git context is available.
"""

import subprocess
import logging
from pathlib import Path
from functools import lru_cache
import time

logger = logging.getLogger(__name__)

_cache: dict = {"repo": "", "branch": "", "ts": 0}
_CACHE_TTL = 5  # seconds


def get_git_context() -> tuple[str, str]:
    """Return (repo_name, branch_name) for the active git working tree."""
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL:
        return _cache["repo"], _cache["branch"]

    cwd = _get_active_cwd()
    if not cwd:
        return "", ""

    repo   = _git_repo_name(cwd)
    branch = _git_branch(cwd)

    _cache.update({"repo": repo, "branch": branch, "ts": now})
    return repo, branch


def _get_active_cwd() -> str | None:
    """
    Try to get the CWD of the frontmost terminal/IDE process.
    Uses macOS `lsappinfo` to find the frontmost app, then infers its CWD
    from /proc or lsof. Best-effort — returns None if unavailable.
    """
    # Simple heuristic: look for common dev processes and get their CWD
    dev_procs = ["cursor", "code", "python3", "node", "zsh", "bash"]
    for proc_name in dev_procs:
        try:
            result = subprocess.run(
                ["pgrep", "-n", proc_name],
                capture_output=True, text=True, timeout=1
            )
            pid = result.stdout.strip()
            if not pid:
                continue

            # Get CWD via lsof
            lsof = subprocess.run(
                ["lsof", "-p", pid, "-a", "-d", "cwd", "-Fn"],
                capture_output=True, text=True, timeout=1
            )
            for line in lsof.stdout.splitlines():
                if line.startswith("n"):
                    return line[1:]
        except Exception:
            continue
    return None


def _git_repo_name(cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).name
    except Exception:
        pass
    return ""


def _git_branch(cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""
