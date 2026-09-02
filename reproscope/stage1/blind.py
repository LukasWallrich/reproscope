"""Assemble the blind working directory for one replica.

The replica sees only the redacted methods, the value-free contract, the data and
the task. The deterministic value scan runs over the methods, the contract and any
prose shipped with the data; a hit blocks the launch.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .. import artifacts, paths


PROSE_SUFFIXES = {".txt", ".md", ".rtf", ".do", ".log"}


class LeakDetected(RuntimeError):
    pass


# --- leak scan ------------------------------------------------------------


def _local_scan(files: list[Path], claims: list[artifacts.ClaimRecord]) -> list[str]:
    """Fallback for stage0.leakcheck.scan: reported values as bounded tokens.

    Every numeric claim value is searched at its own precision, rounded to 1-3
    decimals, and as its absolute value. A digit or decimal point either side of
    the match disqualifies it, so 4.09 does not fire on 14.091.
    """
    tokens: set[str] = set()
    for c in claims:
        v = c.value
        if isinstance(v, str):
            m = re.search(r"-?(?:\d+\.?\d*|\.\d+)", v)
            v = float(m.group()) if m else None
        if not isinstance(v, (int, float)):
            continue
        for x in {float(v), abs(float(v))}:
            tokens.add(f"{x:g}")
            for dp in (1, 2, 3):
                s = f"{x:.{dp}f}"
                tokens.add(s)
                if s.startswith("0."):
                    tokens.add(s[1:])  # APA style: .42
                elif s.startswith("-0."):
                    tokens.add("-" + s[2:])
    hits: list[str] = []
    for path in files:
        text = Path(path).read_text()
        for tok in sorted(tokens):
            for m in re.finditer(re.escape(tok), text):
                before = text[m.start() - 1] if m.start() else ""
                after = text[m.end()] if m.end() < len(text) else ""
                if before.isdigit() or before == "." or after.isdigit() or after == ".":
                    continue
                hits.append(f"{Path(path).name}: {tok!r} at offset {m.start()}")
    return hits


def scan(files: list[Path], claims: list[artifacts.ClaimRecord]) -> list[str]:
    try:
        from ..stage0 import leakcheck  # type: ignore
    except ImportError:
        return _local_scan(files, claims)
    return list(leakcheck.scan(files, claims))


# --- assembly -------------------------------------------------------------


def stage0_dir(paper_id: str) -> Path:
    return paths.run_dir(paper_id, 0)


def replica_dir(paper_id: str, replica_id: str) -> Path:
    return paths.run_dir(paper_id, 1) / "replicas" / replica_id


def claims(paper_id: str) -> list[artifacts.ClaimRecord]:
    loaded = artifacts.load(artifacts.ClaimRecord, stage0_dir(paper_id) / "claims.json")
    return loaded if isinstance(loaded, list) else [loaded]


def contracts(paper_id: str) -> list[artifacts.EstimandContract]:
    loaded = artifacts.load(artifacts.EstimandContract, stage0_dir(paper_id) / "contracts.json")
    return loaded if isinstance(loaded, list) else [loaded]


def paper_text(paper_id: str) -> str:
    """Full paper text for the unblinded steps: corpus copy, stage0 copy, or pdftotext."""
    for candidate in (paths.corpus_dir(paper_id) / "paper.txt", stage0_dir(paper_id) / "paper.txt"):
        if candidate.exists():
            return candidate.read_text()
    man = paths.manifest(paper_id)
    pdf = man.path(man.pdf)
    if pdf.exists() and shutil.which("pdftotext"):
        import subprocess

        out = paths.run_dir(paper_id, 0) / "paper.txt"
        subprocess.run(["pdftotext", "-layout", str(pdf), str(out)], check=True)
        return out.read_text()
    raise FileNotFoundError(
        f"no paper text for {paper_id}: expected corpus/{paper_id}/paper.txt, "
        f"runs/{paper_id}/stage0/paper.txt, or a convertible {man.pdf}"
    )


def copy_data(paper_id: str, dest: Path) -> list[str]:
    """Copy the manifest's data files and codebook into dest. Never original code."""
    man = paths.manifest(paper_id)
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for rel in list(man.data_files) + ([man.codebook] if man.codebook else []):
        src = man.path(rel)
        if not src.exists():
            raise FileNotFoundError(f"manifest lists {rel} but {src} is missing")
        shutil.copy2(src, dest / src.name)
        copied.append(src.name)
    return copied


def assemble(paper_id: str, replica_id: str) -> Path:
    """Create runs/<paper_id>/stage1/replicas/<replica_id>/work/ and return it."""
    s0 = stage0_dir(paper_id)
    methods_src, contract_src = s0 / "redacted_methods.md", s0 / "blind_contract.json"
    for p in (methods_src, contract_src):
        if not p.exists():
            raise FileNotFoundError(f"stage0 output missing: {p}")

    claim_records = claims(paper_id)
    hits = scan([methods_src, contract_src], claim_records)
    if hits:
        raise LeakDetected(
            f"{len(hits)} reported value(s) found in the blind material; launch blocked:\n  "
            + "\n  ".join(str(h) for h in hits[:20])
        )

    work = replica_dir(paper_id, replica_id) / "work"
    (work / "out").mkdir(parents=True, exist_ok=True)
    shutil.copy2(methods_src, work / "METHODS.md")
    shutil.copy2(contract_src, work / "CONTRACT.json")
    (work / "TASK.md").write_text(artifacts.load_prompt("stage1_replica_task"))
    copy_data(paper_id, work / "data")

    # Prose shipped with the data (author notes, READMEs) can state the results.
    # Data tables are not scanned: a reported value also occurring as a cell is not leakage.
    notes = [p for p in sorted((work / "data").iterdir()) if p.suffix.lower() in PROSE_SUFFIXES]
    note_hits = scan(notes, claim_records) if notes else []
    if note_hits:
        shutil.rmtree(work)
        raise LeakDetected(
            f"{len(note_hits)} reported value(s) found in the data folder's notes; launch "
            "blocked. Redact the file or drop it from manifest.data_files:\n  "
            + "\n  ".join(str(h) for h in note_hits[:20])
        )
    return work
