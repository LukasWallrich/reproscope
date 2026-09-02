"""Install the Stage 3 fixture as paper `_fixture3` under a reproscope root.

Run:  .venv/bin/python tests/fixtures/stage3/install.py     (installs into the repo)

Tests call `install(tmp_path)` to get the same tree under a sandbox root.
Reruns are safe: the target corpus/ and runs/stage0|stage1 trees are replaced, and
runs/_fixture3/stage3 (the outputs Stage 3 itself writes) is left alone.
"""

from __future__ import annotations

import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAPER_ID = "_fixture3"


def install(root: Path | str) -> str:
    root = Path(root)
    corpus = root / "corpus" / PAPER_ID
    runs = root / "runs" / PAPER_ID
    shutil.rmtree(corpus, ignore_errors=True)
    shutil.copytree(HERE / "corpus", corpus)
    for stage in ("stage0", "stage1"):
        shutil.rmtree(runs / stage, ignore_errors=True)
        shutil.copytree(HERE / "runs" / stage, runs / stage)
    (runs / "stage3").mkdir(parents=True, exist_ok=True)
    return PAPER_ID


if __name__ == "__main__":
    repo_root = HERE.parents[2]
    install(repo_root)
    print(f"installed fixture as {PAPER_ID} under {repo_root}")
