"""Clone/update repositories for indexing without writing the token to disk or argv."""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path


def _git_env(token: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                    "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}", "GIT_TERMINAL_PROMPT": "0"})
    return env


def ensure_clone(repo: str, branch: str, cache_dir: str | Path, token: str | None) -> Path:
    """Blobless clone (full history for ownership, file contents only for the checked-out branch)."""
    target = Path(cache_dir) / repo.replace("/", "__")
    env = _git_env(token)
    if (target / ".git").exists():
        subprocess.run(["git", "-C", str(target), "fetch", "--filter=blob:none", "origin", branch], env=env, check=True)
        subprocess.run(["git", "-C", str(target), "checkout", "-q", "-B", branch, f"origin/{branch}"], env=env, check=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--branch", branch,
                        f"https://github.com/{repo}.git", str(target)], env=env, check=True)
    return target
