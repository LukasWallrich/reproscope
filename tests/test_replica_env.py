"""Offline tests for the per-replica environments a replica agent declares.

Every `subprocess.run` is mocked: no installer and no interpreter is invoked.
"""

from __future__ import annotations

import subprocess

import pytest

from reproscope.stage1 import blind, replicas


@pytest.fixture
def rdir(tmp_path, monkeypatch):
    """A replica run directory with its work copy, isolated from /private/tmp."""
    monkeypatch.setattr(blind, "ISOLATION_ROOT", tmp_path / "iso")
    d = tmp_path / "runs" / "P" / "stage1" / "replicas" / "r1"
    (d / "work" / "out").mkdir(parents=True)
    return d


def recorder(exit_codes: dict[str, int] | None = None):
    """A subprocess.run stand-in that records commands and fails the named ones.

    A key of `exit_codes` matches when it appears in the command line.
    """
    calls: list[dict] = []

    def run(cmd, **kw):
        calls.append({"cmd": list(cmd), "env": kw.get("env") or {}, "cwd": kw.get("cwd")})
        joined = " ".join(cmd)
        code = next((c for k, c in (exit_codes or {}).items() if k in joined), 0)
        return subprocess.CompletedProcess(cmd, code, stdout="pandas==3.0.5\n", stderr="")

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_no_declarations_run_in_the_base_interpreter(rdir, monkeypatch):
    run = recorder()
    monkeypatch.setattr(subprocess, "run", run)

    info = replicas.prepare_env(rdir / "work" / "out", rdir)

    assert run.calls == []
    assert info == {"interpreter": None, "env": {}, "installed": [], "env_dir": None,
                    "error": None, "log": ""}
    script = rdir / "work" / "out" / "analysis.py"
    assert replicas.script_command(script, script.parent, info["interpreter"])[0] == (
        replicas.base_python()
    )


def test_requirements_build_a_venv_and_pick_its_interpreter(rdir, monkeypatch):
    (rdir / "work" / "out" / "requirements.txt").write_text("scipy==1.18.1\n# a note\n")
    run = recorder()
    monkeypatch.setattr(subprocess, "run", run)

    info = replicas.prepare_env(rdir / "work" / "out", rdir)

    assert info["error"] is None
    assert info["installed"] == ["scipy==1.18.1"]
    assert info["env_dir"] == str(rdir / "env")
    assert info["interpreter"] == str(rdir / "env" / "bin" / "python")
    # The base stack is frozen from the repo venv and installed alongside the extras.
    assert run.calls[0]["cmd"][:4] == ["uv", "pip", "freeze", "--python"]
    assert (rdir / "base_requirements.txt").read_text() == "pandas==3.0.5\n"
    assert run.calls[1]["cmd"] == ["uv", "venv", str(rdir / "env"), "--python", "3.14"]
    # Base first, then the declarations, so a declared pin replaces the base one.
    prefix = ["uv", "pip", "install", "--python", info["interpreter"], "-r"]
    assert run.calls[2]["cmd"] == prefix + [str(rdir / "base_requirements.txt")]
    assert run.calls[3]["cmd"] == prefix + [str(rdir / "work" / "out" / "requirements.txt")]

    script = rdir / "work" / "out" / "analysis.py"
    assert replicas.script_command(script, script.parent, info["interpreter"]) == [
        info["interpreter"], "analysis.py"
    ]


def test_a_failed_install_abstains_with_the_package_names(rdir, monkeypatch):
    (rdir / "work" / "out" / "requirements.txt").write_text("nosuchpkg==9.9\nscipy\n")
    monkeypatch.setattr(subprocess, "run", recorder({"pip install": 1}))

    info = replicas.prepare_env(rdir / "work" / "out", rdir)

    assert info["error"] == "environment: nosuchpkg==9.9, scipy could not be installed"
    assert info["interpreter"] is None


def test_a_failed_install_ends_the_check_as_abstained(rdir, monkeypatch):
    (rdir / "work" / "out" / "requirements.txt").write_text("nosuchpkg\n")
    monkeypatch.setattr(subprocess, "run", recorder({"pip install": 1}))
    script = rdir / "work" / "out" / "analysis.py"
    script.write_text("print(1)\n")

    checks = replicas.rerun_script(rdir / "work", script, rdir)

    assert checks["env_error"] == "environment: nosuchpkg could not be installed"
    assert checks["exit_code"] is None and checks["regenerated_results"] is False
    assert "pip install" in (rdir / "check.log").read_text()


def test_r_packages_install_into_a_per_replica_library(rdir, monkeypatch):
    (rdir / "work" / "out" / "r_packages.txt").write_text("lme4==1.1-37\nsandwich\n")
    run = recorder()
    monkeypatch.setattr(subprocess, "run", run)

    info = replicas.prepare_env(rdir / "work" / "out", rdir)

    assert info["error"] is None
    assert info["installed"] == ["lme4", "sandwich"]
    assert info["env"] == {"R_LIBS_USER": str(rdir / "rlib")}
    assert (rdir / "rlib").is_dir()
    code = run.calls[0]["cmd"][2]
    assert run.calls[0]["cmd"][:2] == ["Rscript", "-e"]
    assert '"lme4", "sandwich"' in code and replicas.CRAN in code
    # The library is on the path for the install itself, so a package already there
    # from an earlier run is not fetched again.
    assert run.calls[0]["env"]["R_LIBS_USER"] == str(rdir / "rlib")


def test_a_failed_r_install_abstains(rdir, monkeypatch):
    (rdir / "work" / "out" / "r_packages.txt").write_text("nosuchpkg\n")
    monkeypatch.setattr(subprocess, "run", recorder({"Rscript": 1}))

    info = replicas.prepare_env(rdir / "work" / "out", rdir)

    assert info["error"] == "environment: nosuchpkg could not be installed"
