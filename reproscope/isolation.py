"""Enforced local verification boundary, with a denied-read canary.

Model generation routes have separate network/credential needs and are not claimed
as isolated by this verifier. The boundary restricts filesystem access and
network use; it does not isolate IPC or the process namespace. Unsupported hosts retain an explicit unverified status.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def command(cmd: list[str], work: Path, env: dict | None = None) -> tuple[list[str], dict]:
    runner = shutil.which("sandbox-exec") if sys.platform == "darwin" else None
    if not runner:
        return cmd, {"enforced": False, "reason": "no supported OS verifier sandbox on this host"}
    roots = {Path(p).resolve() for p in (sys.prefix, sys.base_prefix)}
    roots |= {Path(p).resolve() for p in sys.path if p and "site-packages" in p}
    executable = shutil.which(cmd[0]) or cmd[0]
    roots.add(Path(executable).resolve().parent.parent)
    # Resolving a venv's Python symlink finds the base interpreter, but Python
    # still reads pyvenv.cfg and site-packages from the invoked environment.
    invoked_env = Path(executable).absolute().parent.parent
    if (invoked_env / "pyvenv.cfg").is_file():
        roots.add(invoked_env.resolve())
    for name in ("R_LIBS_USER", "R_LIBS"):
        roots |= {Path(p).resolve() for p in (env or {}).get(name, "").split(os.pathsep) if p}
    forbidden = {Path(p) for p in ("/", "/Users", "/Volumes", "/private", "/private/tmp", "/private/var/folders")}
    if roots & forbidden:
        raise RuntimeError("verifier runtime allowlist contains an unsafe broad root")
    roots.add(work.resolve())
    def subpath(p):
        return '(subpath ' + json.dumps(str(p)) + ')'
    system = ["/System", "/Library", "/usr", "/bin", "/sbin", "/dev", "/opt", "/private/etc", "/private/var/db"]
    profile = '\n'.join(['(version 1)', '(allow default)',
        '(deny file-read* file-write* ' + ' '.join(subpath(p) for p in ['/Users', '/Volumes', '/private/tmp', '/private/var/folders']) + ')',
        '(deny file-write*)', '(allow file-read-metadata)',
        '(allow file-read* ' + ' '.join(subpath(p) for p in system + sorted(map(str, roots))) + ')',
        '(allow file-write* ' + subpath(work.resolve()) + ' (literal "/dev/null"))',
        '(deny network*)'])
    # An external harmless file must be denied under exactly this profile.
    with tempfile.NamedTemporaryFile(prefix="reproscope_denied_canary_") as canary:
        probe = subprocess.run([runner, '-p', profile, sys.executable, '-c',
            'import pathlib,sys;\ntry: pathlib.Path(sys.argv[1]).read_bytes()\nexcept PermissionError: sys.exit(0)\nelse: sys.exit(9)', canary.name],
            capture_output=True, timeout=20, cwd=work,
            env=clean_environment({**os.environ, **(env or {})},work))
    if probe.returncode != 0:
        raise RuntimeError(f"OS verifier sandbox failed its denied-read canary (exit {probe.returncode}): " + probe.stderr.decode(errors="replace")[-400:])
    return [runner, '-p', profile, *cmd], {"enforced": True, "mechanism": "macOS Seatbelt",
        "external_read_canary": "denied", "network": "denied", "write_root": str(work.resolve()),
        "runtime_read_roots": sorted(map(str, roots)),
        "scope": "verification subprocess; protected user/temporary files and network",
        "denied_roots_except_runtime_allowlist": ["/Users", "/Volumes", "/private/tmp", "/private/var/folders"]}


def clean_environment(env: dict, work: Path) -> dict:
    """Verifier scripts do not need model credentials or the invoking shell's secrets."""
    import re
    result = {k: v for k, v in env.items() if not re.search(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH", k, re.I)}
    # The launcher may use PYTHONPATH to import the pipeline. That path is not
    # part of the replica environment and can make pip inspect denied folders.
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        result.pop(name, None)
    result.update(TMPDIR=str(work.resolve()), PYTHONDONTWRITEBYTECODE="1")
    return result
