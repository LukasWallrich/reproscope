"""Step 5: a deterministic schema summary of every data file, then the readiness call."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths

MAX_VALUE_COUNTS = 12
N_EXAMPLES = 3
TEXT_SUFFIXES = {".txt", ".md"}
PROMPTS = ("stage0_readiness",)


# --- deterministic schema summary ----------------------------------------


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()  # numpy / pandas scalar -> Python scalar
        except (ValueError, AttributeError):
            pass
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 6)
    if isinstance(v, (int, str)):
        return v
    try:
        import pandas as pd

        if pd.isna(v):
            return None
    except Exception:  # noqa: BLE001
        pass
    return str(v)


def _column_summary(series, label: str | None = None) -> dict[str, Any]:
    import pandas as pd

    n = int(series.shape[0])
    n_missing = int(series.isna().sum())
    out: dict[str, Any] = {
        "name": str(series.name),
        "dtype": str(series.dtype),
        "n": n,
        "n_missing": n_missing,
        "n_distinct": int(series.nunique(dropna=True)),
    }
    if label:
        out["label"] = label
    non_null = series.dropna()
    if pd.api.types.is_numeric_dtype(series) and not non_null.empty:
        out["min"] = _jsonable(non_null.min())
        out["max"] = _jsonable(non_null.max())
        out["mean"] = _jsonable(float(non_null.mean()))
    if out["n_distinct"] <= MAX_VALUE_COUNTS:
        out["value_counts"] = {
            str(_jsonable(k)): int(v) for k, v in series.value_counts(dropna=False).items()
        }
    out["examples"] = [_jsonable(v) for v in non_null.head(N_EXAMPLES).tolist()]
    return out


def _unnamed_fraction(columns) -> float:
    if len(columns) == 0:
        return 0.0
    return sum(1 for c in columns if str(c).startswith("Unnamed:")) / len(columns)


def _group_labels(header_row) -> list[str | None]:
    """Forward-fill a merged-cell header row into a per-column label list."""
    labels: list[str | None] = []
    current: str | None = None
    for c in header_row:
        name = str(c)
        if not name.startswith("Unnamed:") and name.strip():
            current = name.strip()
        labels.append(current)
    return labels


def _table_summary(df, name: str | None, labels: list[str | None] | None = None) -> dict[str, Any]:
    cols = []
    for i, col in enumerate(df.columns):
        label = labels[i] if labels and i < len(labels) else None
        cols.append(_column_summary(df[col], label))
    return {"table": name, "rows": int(df.shape[0]), "cols": int(df.shape[1]), "columns": cols}


def _excel_tables(path: Path) -> list[dict[str, Any]]:
    import pandas as pd

    xl = pd.ExcelFile(path)
    tables = []
    for sheet in xl.sheet_names:
        df = xl.parse(sheet, header=0)
        labels = None
        note = None
        if _unnamed_fraction(df.columns) > 0.3:
            # Two header rows: row 0 carries merged group labels, row 1 the names.
            labels = _group_labels(list(df.columns))
            df = xl.parse(sheet, header=1)
            note = "two header rows; row 1 used as column names, row 0 kept as group labels"
        t = _table_summary(df, sheet, labels)
        if note:
            t["note"] = note
        tables.append(t)
    return tables


def summarise_file(path: Path) -> dict[str, Any]:
    import pandas as pd

    suffix = path.suffix.lower()
    rec: dict[str, Any] = {"path": path.name, "format": suffix.lstrip("."), "tables": []}
    try:
        if suffix in {".xls", ".xlsx", ".xlsm"}:
            rec["tables"] = _excel_tables(path)
        elif suffix == ".sav":
            import pyreadstat

            df, meta = pyreadstat.read_sav(str(path))
            labels = [meta.column_names_to_labels.get(c) for c in df.columns]
            rec["tables"] = [_table_summary(df, None, labels)]
            rec["value_labels"] = {
                k: {str(a): b for a, b in v.items()}
                for k, v in list(meta.variable_value_labels.items())[:40]
            }
        elif suffix == ".dta":
            df = pd.read_stata(path)
            rec["tables"] = [_table_summary(df, None)]
        elif suffix in {".csv", ".tsv"}:
            df = pd.read_csv(path, sep="\t" if suffix == ".tsv" else ",")
            rec["tables"] = [_table_summary(df, None)]
        elif suffix in TEXT_SUFFIXES:
            # Only a real delimiter makes a .txt tabular; prose otherwise.
            for sep in ("\t", ","):
                df = pd.read_csv(path, sep=sep)
                if df.shape[1] >= 2:
                    rec["tables"] = [_table_summary(df, None)]
                    break
            else:
                raise ValueError("not tabular")
        else:
            raise ValueError(f"unhandled format {suffix}")
    except Exception as e:  # noqa: BLE001 - free-text notes and odd files land here
        if suffix in TEXT_SUFFIXES:
            rec["format"] = "text"
            rec["text"] = path.read_text(errors="replace")[:4000]
        else:
            rec["error"] = f"{type(e).__name__}: {e}"
    return rec


def schema_summary(manifest) -> dict[str, Any]:
    files = []
    for rel in manifest.data_files:
        p = manifest.path(rel)
        if not p.exists():
            files.append({"path": rel, "error": "missing"})
            continue
        rec = summarise_file(p)
        rec["path"] = rel
        rec["bytes"] = p.stat().st_size
        files.append(rec)
    return {"paper_id": manifest.paper_id, "files": files}


def codebook_text(manifest, summary: dict[str, Any]) -> str:
    """The codebook if the manifest names one, else the free-text notes shipped with the data."""
    if manifest.codebook:
        p = manifest.path(manifest.codebook)
        if p.exists():
            return p.read_text(errors="replace")[:20000]
    parts = [
        f"--- {f['path']} ---\n{f['text']}" for f in summary["files"] if f.get("format") == "text"
    ]
    return "\n\n".join(parts) if parts else "(none)"


# --- the readiness call ---------------------------------------------------


class SlimFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    format: str | None = None
    role: str | None = None
    rows: int | None = None
    cols: int | None = None
    unit_of_observation: str | None = None


class SlimBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_field: str
    analysis_id: str | None = None
    candidate_columns: list[str] = []
    chosen: str | None = None
    note: str | None = None


class SlimAnalysisState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    state: str
    abstain_reason: str | None = None


class ReadinessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[SlimFile] = []
    unit_of_observation: str | None = None
    keys: list[str] = []
    missing_sentinels: list[str] = []
    variable_bindings: list[SlimBinding] = []
    scale_direction_notes: list[str] = []
    weights_columns: list[str] = []
    derived_variables_needed: list[str] = []
    per_analysis: list[SlimAnalysisState] = []
    open_ambiguities: list[str] = []
    confidence: str | None = None


def run(
    manifest,
    contract_records: list[artifacts.EstimandContract],
    inputs: dict[str, str] | None = None,
    force: bool = False,
) -> tuple[artifacts.DataReadinessRecord, list[str]]:
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    schema_path = stage_dir / "schema.json"
    out_path = stage_dir / "readiness.json"

    if not schema_path.exists() or force:
        schema_path.write_text(json.dumps(schema_summary(manifest), indent=2) + "\n")
    summary = json.loads(schema_path.read_text())

    if out_path.exists() and not force:
        existing = artifacts.load(artifacts.DataReadinessRecord, out_path)
        if not artifacts.prompt_stale(existing, PROMPTS):  # type: ignore[arg-type]
            return existing, []  # type: ignore[return-value]

    # The paper text is not part of this call: binding columns to contract fields
    # needs the data's own documentation and the contracts, nothing more.
    prompt = artifacts.load_prompt(
        "stage0_readiness",
        schema=json.dumps(summary, indent=1),
        codebook=codebook_text(manifest, summary),
        contracts=json.dumps(
            [c.model_dump(exclude={"meta"}, exclude_none=True) for c in contract_records], indent=1
        ),
    )
    r = llm.call(
        "readiness",
        prompt,
        paper_id=manifest.paper_id,
        stage="0",
        tier="mid",
        schema=ReadinessOut,
        cwd=manifest.dir / "data",
        timeout_s=3600,
        log_path=stage_dir / "logs" / "readiness.log",
    )
    if r.parsed is None:
        raise llm.LLMError(f"readiness failed: {r.error}")
    out: ReadinessOut = r.parsed  # type: ignore[assignment]

    record = artifacts.DataReadinessRecord.model_validate(
        {
            "meta": artifacts.ArtifactMeta(
                artifact="DataReadinessRecord",
                stage="0",
                inputs=inputs or {},
                prompt_versions={n: artifacts.prompt_version(n) for n in PROMPTS},
                model_calls=[r.ledger_id or ""],
            ).model_dump(),
            "files": [f.model_dump() for f in out.files],
            "unit_of_observation": out.unit_of_observation,
            "keys": out.keys,
            "missing_sentinels": out.missing_sentinels,
            "variable_bindings": [b.model_dump() for b in out.variable_bindings],
            "scale_direction_notes": out.scale_direction_notes,
            "weights_columns": out.weights_columns,
            "derived_variables_needed": out.derived_variables_needed,
            "per_analysis_state": {
                a.analysis_id: (a.state if a.state in {"complete", "abstained"} else "abstained")
                for a in out.per_analysis
            },
            "per_analysis_reasons": {
                a.analysis_id: a.abstain_reason for a in out.per_analysis if a.abstain_reason
            },
            "open_ambiguities": out.open_ambiguities,
            "state": "abstained"
            if any(a.state == "abstained" for a in out.per_analysis)
            else "complete",
            "confidence": out.confidence if out.confidence in {"high", "medium", "low"} else None,
        }
    )
    artifacts.save(record, out_path)
    return record, [r.ledger_id or ""]
