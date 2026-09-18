"""Execute declared integrity checks without repairing deposited data."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd


def _numeric(frame, request, bindings, families):
    """Use the declared per-column parser; blanks are not silently coerced."""
    candidates = []
    for binding in bindings:
        b = binding.model_dump() if hasattr(binding, "model_dump") else binding
        candidates.append((b.get("analysis_id"), b.get("file"), b.get("table"),
                           b.get("input_columns") or [b.get("chosen")], b.get("numeric_parsing")))
    for aid, family in families.items():
        for member in family.get("members", []):
            candidates.append((aid, member.get("file"), member.get("table"),
                               [member.get("x"), member.get("y")], member.get("numeric_parsing")))
    parsed, policies = {}, {}
    for column in request["columns"]:
        choices = {parser for aid, file, table, columns, parser in candidates
                   if aid == request["analysis_id"] and file and
                   Path(file).name == Path(request["file"]).name and
                   (table or None) == (request.get("table") or None) and column in columns and parser}
        if len(choices) > 1:
            raise ValueError(f"conflicting numeric parsing policies for {column}")
        parser = next(iter(choices), "strict_float")
        series = frame[column]
        if parser == "strict_float_blank_missing":
            series = series.replace(r"^\s*$", np.nan, regex=True)
        elif parser != "strict_float":
            raise ValueError(f"unsupported numeric parser {parser}")
        parsed[column] = pd.to_numeric(series, errors="raise")
        policies[column] = parser
    return pd.DataFrame(parsed), policies


def run(manifest, requests: list[dict], *, bindings=(), families=None, sample_selections=None) -> list[dict]:
    results = []
    for request in requests:
        result = {**request, "status": "unverified"}
        try:
            rel = request["file"]
            if rel not in manifest.data_files and not any(Path(p).name == rel for p in manifest.data_files):
                raise ValueError("integrity input is not a declared deposit")
            source = next(manifest.path(p) for p in manifest.data_files if p == rel or Path(p).name == rel)
            frame = pd.read_csv(source, sep="\t" if source.suffix.lower() == ".tsv" else ",") if source.suffix.lower() in {".csv", ".tsv"} else pd.read_excel(source, sheet_name=request.get("table") or 0)
            result["input_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            selection=(sample_selections or {}).get(request['analysis_id'])
            if selection:
                if Path(selection['file']).name!=Path(rel).name or (selection.get('table') or None)!=(request.get('table') or None):
                    raise ValueError('integrity sample belongs to a different source table')
                original_n=len(frame)
                if selection.get('filters'):
                    from .sample_filters import select
                    frame=select(frame,selection['filters'])
                if selection.get('included_ids') is not None:
                    identifier=selection['id_column'];selected=set(selection['included_ids'])
                    if not selected<=set(frame[identifier]):raise ValueError('integrity sample IDs unavailable after declared filters')
                    frame=frame[frame[identifier].isin(selected)]
                result['sample_scope']={'basis':'validated_analysis_selection','deposit_rows':original_n,'selected_rows':len(frame)}
            kind, columns = request["kind"], request["columns"]
            if kind == "unique_id":
                bad = frame[columns].isna().any(axis=1) | frame.duplicated(columns, keep=False)
            elif kind == "paired_complete":
                if not request.get("assumption_evidence"):
                    raise ValueError("paired completeness requires evidence that complete pairs are required")
                numeric, result["numeric_parsing"] = _numeric(frame, request, bindings, families or {})
                missing = numeric.isna()
                bad = (missing.any(axis=1) & ~missing.all(axis=1)) | np.isinf(numeric).any(axis=1)
                result.update(n_complete=int(np.isfinite(numeric).all(axis=1).sum()),
                              n_all_missing=int(missing.all(axis=1).sum()))
                family = (families or {}).get(request["analysis_id"])
                if family:
                    # Different variables need not share a missingness pattern.
                    # Profile the declared correlation pairs; their sample rules
                    # determine inclusion and are checked during execution.
                    members = []
                    for member in family["members"]:
                        member_request = {**request, "file": member["file"], "table": member.get("table"),
                                          "columns": [member["x"], member["y"]]}
                        if Path(member["file"]).name != Path(rel).name or (member.get("table") or None) != (request.get("table") or None):
                            raise ValueError("correlation profile request spans different source tables")
                        pair, policies = _numeric(frame, member_request, bindings, families or {})
                        members.append({"member_id": member["member_id"], "columns": member_request["columns"],
                                        "numeric_parsing": policies, "sample_rule": member["sample_rule"],
                                        "n_complete": int(np.isfinite(pair).all(axis=1).sum()),
                                        "incomplete_row_positions": frame.index[~np.isfinite(pair).all(axis=1)].tolist()})
                    result.update(status="profiled", executed_kind="correlation_completeness_profile", members=members,
                                  n_checked=len(frame), interpretation="Observed per-member completeness; unequal missingness across correlation variables is not itself a deposit anomaly. Sample-rule compliance requires execution verification.")
                    results.append(result)
                    continue
            elif kind == "nested_loglikelihood":
                if not request.get("assumption_evidence") or len(columns) != 2:
                    raise ValueError("nested likelihood check needs explicit model-nesting evidence and restricted/full columns")
                numeric, result["numeric_parsing"] = _numeric(frame, request, bindings, families or {})
                bad = ~np.isfinite(numeric).all(axis=1) | (numeric.iloc[:, 1] + 1e-8 < numeric.iloc[:, 0])
            else:
                raise ValueError("unsupported integrity check")
            result.update(status="anomaly" if bad.any() else "passed", affected_row_positions=frame.index[bad].tolist(), n_checked=len(frame),
                          interpretation="observed deposit diagnostic under declared assumptions; no values repaired")
        except (ValueError, KeyError, TypeError, OSError) as exc:
            result["reason"] = str(exc)
        results.append(result)
    return results


def require_likelihood_checks(requests, likelihood_bindings):
    """Every executable likelihood binding requires its declared nesting check."""
    out=list(requests)
    def key(r):
        return (r['analysis_id'],r['kind'],Path(r['file']).name,r.get('table'),tuple(r['columns']))
    existing={key(r) for r in out}
    for aid,b in likelihood_bindings.items():
        request={'analysis_id':aid,'kind':'nested_loglikelihood','file':b['file'],
                 'table':b.get('table'),'columns':[b['y'],b['x']],
                 'assumption_evidence':b['evidence']+' '+b['assumption']}
        if key(request) not in existing:
            out.append(request);existing.add(key(request))
    return out
