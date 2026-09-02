"""Build corpus/<paper_id>/ from the Multi100 sweep directory: copies data, code and PDF,
and writes manifest.json from the sweep's claim rows, analyst stats and DOI lookups.

Usage: .venv/bin/python -m reproscope.corpus_setup <sweep_dir> <paper_id> [<paper_id> ...]
"""
import json
import shutil
import sys
from pathlib import Path

from .paths import ROOT

DATA_EXT = {".csv", ".xls", ".xlsx", ".sav", ".dta", ".rds", ".rdata", ".tsv", ".txt"}
CODE_EXT = {".r", ".py", ".do", ".sps", ".inp", ".sas"}


def setup(sweep: Path, paper_id: str) -> Path:
    src = sweep / paper_id
    claims = json.load(open(sweep / "claims_rows.json"))[paper_id]
    stats = json.load(open(sweep / "analyst_stats.json"))[paper_id]
    doi = json.load(open(src / "doi_oa.json"))
    dst = ROOT / "corpus" / paper_id
    (dst / "data").mkdir(parents=True, exist_ok=True)
    (dst / "code").mkdir(exist_ok=True)
    data_files, code_files, codebook = [], [], None
    seen: set[str] = set()
    for f in sorted((src / "files").glob("*")):
        if not f.is_file() or f.name.endswith("_file_list.tsv"):
            continue
        name = f.name.split("__", 1)[-1]  # strip the "component:Data__" prefix
        ext = f.suffix.lower()
        if name in seen or name.startswith("author_notes"):
            continue  # author correspondence is not data and may mention results
        seen.add(name)
        if "codebook" in name.lower() or "dictionary" in name.lower():
            shutil.copy(f, dst / "data" / name); codebook = f"data/{name}"
        elif ext in DATA_EXT:
            shutil.copy(f, dst / "data" / name); data_files.append(f"data/{name}")
        elif ext in CODE_EXT or "syntax" in name.lower():
            shutil.copy(f, dst / "code" / name); code_files.append(f"code/{name}")
    pdfs = sorted(src.glob("paper*.pdf"))
    if pdfs:
        shutil.copy(pdfs[0], dst / "paper.pdf")
    manifest = {
        "paper_id": paper_id,
        "title": doi.get("title") or doi.get("crossref", {}).get("title"),
        "doi": doi.get("crossref", {}).get("doi"),
        "pdf": "paper.pdf" if pdfs else None,
        "pdf_source": pdfs[0].name if pdfs else None,
        "licence": doi.get("unpaywall", {}).get("license") or "unknown",
        "oa_status": doi.get("unpaywall", {}).get("oa_status"),
        "data_files": data_files,
        "codebook": codebook,
        "original_code": code_files,
        "focal_claim": {
            "text": claims["claim"],
            "source": "multi100",
            "reported": {
                "statistic": claims.get("orig_stat"),
                "family": claims.get("family"),
                "value": _num(claims.get("stat")),
                "df": _num(claims.get("df1")),
                "n": _num(claims.get("N")),
                "page": claims.get("page"),
            },
        },
        "multi100": {
            "paper_id": paper_id,
            "n_analysts": stats["n_analysts"],
            "analyst_d": {"min": stats["d_min"], "median": stats["d_med"], "max": stats["d_max"]},
            "processed_stat": stats.get("orig_stat"),
            "processed_df": stats.get("df1"),
            "processed_n": stats.get("N"),
        },
        "environment": {"language_hint": "R", "versions_named": {}},
    }
    json.dump(manifest, open(dst / "manifest.json", "w"), indent=2, ensure_ascii=False)
    return dst


def _num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    sweep = Path(sys.argv[1])
    for pid in sys.argv[2:]:
        d = setup(sweep, pid)
        print(d, json.load(open(d / "manifest.json"))["data_files"])
