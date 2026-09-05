"""The Python stack a replica agent writes against and the check re-executes with.

One shared environment under `~/.cache/reproscope/replica-env` holds the base stack at
the versions the repository pins. The agent gets it first on PATH, so `python3`, `python`
and `pip` resolve to it; the re-execution check runs the agent's script with the same
interpreter. The path carries no reference to the repository, and `agent_env` keeps the
repository path out of every variable the agent sees.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path

from . import paths

BASE_ENV = Path.home() / ".cache" / "reproscope" / "replica-env"
PYTHON_VERSION = "3.14"
BASE_PACKAGES = ("numpy", "pandas", "scipy", "statsmodels", "pyreadstat", "openpyxl")
BUILD_TIMEOUT_S = 900

_BUILD_LOCK = threading.Lock()


class RepoPathLeak(RuntimeError):
    """A variable handed to a blind agent carries the repository path."""


def base_python() -> str:
    return str(BASE_ENV / "bin" / "python")


def stamp_path() -> Path:
    return BASE_ENV / "stamp.json"


def base_pins() -> list[str]:
    """`name==version` for each base package, as pinned in the repository's own venv."""
    repo_python = paths.ROOT / ".venv" / "bin" / "python"
    proc = subprocess.run(
        ["uv", "pip", "freeze", "--python", str(repo_python)],
        capture_output=True,
        text=True,
        timeout=BUILD_TIMEOUT_S,
    )
    pins = {}
    for line in (proc.stdout or "").splitlines():
        name, sep, _ = line.strip().partition("==")
        key = name.strip().lower().replace("_", "-")
        if sep and key in BASE_PACKAGES:
            pins[key] = line.strip()
    return [pins.get(name, name) for name in BASE_PACKAGES]


def ensure_base_env() -> Path:
    """Create the shared environment when it is absent or its pins have moved.

    `stamp.json` inside the environment records the Python version and the pins it was
    built from; a matching stamp means the environment is current and nothing is run.
    """
    with _BUILD_LOCK:
        stamp = {"python": PYTHON_VERSION, "packages": base_pins()}
        current = stamp_path()
        if current.exists():
            try:
                if json.loads(current.read_text()) == stamp:
                    return BASE_ENV
            except json.JSONDecodeError:
                pass
        BASE_ENV.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(BASE_ENV, ignore_errors=True)
        for cmd in (
            ["uv", "venv", str(BASE_ENV), "--python", PYTHON_VERSION, "--seed"],
            ["uv", "pip", "install", "--python", base_python(), *stamp["packages"]],
        ):
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=BUILD_TIMEOUT_S
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"replica environment build failed: {' '.join(cmd)}\n"
                    f"{proc.stdout or ''}{proc.stderr or ''}"
                )
        BASE_ENV.mkdir(parents=True, exist_ok=True)
        stamp_path().write_text(json.dumps(stamp, indent=2, sort_keys=True))
        return BASE_ENV


def assert_no_repo_path(env: Mapping[str, str]) -> None:
    """Refuse an agent environment that names the repository directory."""
    root = str(paths.ROOT)
    leaks = sorted(key for key, value in env.items() if root in str(value))
    if leaks:
        raise RepoPathLeak(
            f"the repository path would reach a blind agent through {', '.join(leaks)}"
        )


def agent_env(cwd: Path, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment overrides for a blind agent: the shared stack, and no repository path.

    The shared environment goes first on PATH, entries under the repository are dropped
    from it, the working directory variables point at the agent's own directory, and any
    other variable naming the repository is blanked.
    """
    environ = os.environ if environ is None else environ
    root = str(paths.ROOT)
    path = [p for p in environ.get("PATH", "").split(os.pathsep) if p and root not in p]
    extra = {
        "PATH": os.pathsep.join([str(BASE_ENV / "bin"), *path]),
        "VIRTUAL_ENV": str(BASE_ENV),
        "PWD": str(cwd),
        "OLDPWD": str(cwd),
    }
    for key, value in environ.items():
        if key not in extra and root in value:
            extra[key] = ""
    assert_no_repo_path({**environ, **extra})
    return extra
