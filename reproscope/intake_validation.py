"""Check proposed bindings against data facts before they authorise a blind task."""
from __future__ import annotations

from pathlib import Path


METHOD_AMBIGUITIES = {
    "alternative", "tail", "correlation_type", "correlation_method", "covariate_set",
    "aggregation", "multiple_comparisons", "model_fitting", "effect_size", "baseline_correction",
    "contrast_set", "trial_scoring", "sessions", "t0_bounds", "pg_bounds", "exclusion_rule",
    "artifact_window", "trial_selection", "interpolation_padding",
}
SOURCE_AMBIGUITIES = {"figure_marker", "which_contrast", "table_cell", "source_location", "v_source"}


def source_identity_problems(contracts) -> dict[str, list[dict]]:
    """An assignment cannot settle an open source identity by making it executable.

    Explicit kinds take precedence. Legacy fields use a fixed compatibility map;
    unfamiliar untyped fields require review instead of silently becoming methods.
    Original notes and options stay in this audit, outside the blind packet.
    """
    problems = {}
    for contract in contracts:
        for ambiguity in contract.ambiguities:
            item = ambiguity.model_dump() if hasattr(ambiguity, "model_dump") else dict(ambiguity)
            field = item["field"].strip().casefold()
            kind = item.get("kind") or ("method" if field in METHOD_AMBIGUITIES else "source_identity")
            if kind == "source_identity":
                problems.setdefault(contract.analysis_id, []).append({**item,
                    "classification": "explicit" if item.get("kind") else "legacy_field" if field in SOURCE_AMBIGUITIES else "unclassified_field",
                    "kind": kind})
    return problems


def gate_source_identity(record, contracts):
    problems = source_identity_problems(contracts)
    record.source_identity_problems = problems
    record.per_analysis_outcome = dict(getattr(record, "per_analysis_outcome", {}) or {})
    record.per_analysis_reasons = dict(getattr(record, "per_analysis_reasons", {}) or {})
    for aid, items in problems.items():
        record.per_analysis_state[aid] = "abstained"
        record.per_analysis_outcome[aid] = "source_unresolved"
        record.per_analysis_reasons[aid] = "source identity unresolved: " + ", ".join(i["field"] for i in items)
    if problems:
        record.state = "abstained"
    return record


def validate_bindings(contracts: list, bindings: list[dict], schema: dict) -> dict[str, list[str]]:
    tables = {}
    for file in schema.get("files", []):
        for table in file.get("tables", []):
            tables[(file.get("path"), table.get("table"))] = table
    problems = {c.analysis_id: [] for c in contracts}
    for contract in contracts:
        own = [b for b in bindings if b.get("analysis_id") == contract.analysis_id]
        if not own:
            problems[contract.analysis_id].append("no executable variable bindings for this analysis")
        required = ({"outcome"} if contract.outcome else set())
        required |= {f"predictors[{i}]" for i in range(len(contract.predictors))}
        required |= {f"covariates[{i}]" for i in range(len(contract.covariates))}
        missing = required - {b.get("contract_field") for b in own}
        if missing:
            problems[contract.analysis_id].append("unbound contract fields: " + ", ".join(sorted(missing)))
        for binding in own:
            candidates = [t for (path, name), t in tables.items()
                          if (path == binding.get("file") or (binding.get("file") and Path(path).name == binding["file"]))
                          and (name or None) == (binding.get("table") or None)]
            if len(candidates) != 1:
                problems[contract.analysis_id].append("binding does not identify one data file and table")
                continue
            table = candidates[0]
            columns = {c["name"]: c for c in table.get("columns", [])}
            if binding.get("chosen") and binding["chosen"] not in columns:
                problems[contract.analysis_id].append("chosen must be one exact deposited column name, not a formula or invented derived name; use chosen=null for an explicitly derived binding")
            elif binding.get("chosen") and binding.get("input_columns") and binding["chosen"] not in binding["input_columns"]:
                problems[contract.analysis_id].append("direct chosen column cannot be mixed with a different derived input set; record item-scoring provenance in note, or declare chosen=null and a derived transformation")
            names = binding.get("input_columns") or ([binding["chosen"]] if binding.get("chosen") else [])
            if not names or any(name not in columns for name in names):
                problems[contract.analysis_id].append("binding has missing or unknown source columns")
                continue
            if not binding.get("chosen") and not binding.get("transformation"):
                problems[contract.analysis_id].append("derived binding lacks a transformation")
            derived = bool(binding.get("input_columns") and binding.get("chosen") not in names)
            if derived and binding.get("allowed_range"):
                problems[contract.analysis_id].append("Ambiguous derived range: allowed_range cannot describe raw inputs and a derived output. Resolve its source-supported scope into input_ranges or derived_range; retain the transformation and do not infer a data violation.")
            input_ranges = binding.get("input_ranges") or []
            if len({x.get('column') for x in input_ranges}) != len(input_ranges) or any(x.get('column') not in names for x in input_ranges):
                problems[contract.analysis_id].append("input_ranges must identify distinct bound source columns")
            for bounds in [binding.get('allowed_range'), binding.get('derived_range'), *[x.get('bounds') for x in input_ranges]]:
                if bounds:
                    import math
                    if len(bounds)!=2 or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in bounds) or bounds[0]>bounds[1]:
                        problems[contract.analysis_id].append("range bounds must be two finite ordered numbers")
            for name in names:
                column = columns[name]
                numeric = any(kind in column.get("dtype", "").lower()
                              for kind in ("float", "int", "double"))
                profile = column.get("numeric_parse") or {}
                parser = binding.get("numeric_parsing")
                parsed_numeric = (parser in {"strict_float", "strict_float_blank_missing"}
                                  and profile.get("n_invalid") == 0
                                  and profile.get("n_numeric", 0) > 0
                                  and (profile.get("n_blank", 0) == 0
                                       or parser == "strict_float_blank_missing"))
                if binding.get("expected_type") == "numeric" and not (numeric or parsed_numeric):
                    problems[contract.analysis_id].append(f"{name}: numeric data or a validated explicit numeric parser required")
                if parsed_numeric:
                    column = {**column, "min": profile.get("min"), "max": profile.get("max")}
                bounds = next((x.get('bounds') for x in input_ranges if x.get('column')==name), None)
                if bounds is None and not derived:bounds=binding.get("allowed_range")
                if bounds and len(bounds) == 2 and (column.get("min") is not None and column.get("max") is not None):
                    if column["min"] < bounds[0] or column["max"] > bounds[1]:
                        problems[contract.analysis_id].append(f"{name}: input range check failed; declared={bounds}, observed_min={column['min']}, observed_max={column['max']}")
            design = contract.design
            if design and design.n_total and table.get("rows") and design.n_total > table["rows"]:
                problems[contract.analysis_id].append("declared independent sample exceeds available rows")
    return problems


def score_sets(expected: set, observed: set) -> dict:
    """Annotation scoring keeps coverage and false-positive binding rates separate."""
    correct = len(expected & observed)
    return {"expected": len(expected), "observed": len(observed), "correct": correct,
            "precision": correct / len(observed) if observed else None,
            "recall": correct / len(expected) if expected else None,
            "missing": sorted(expected - observed), "unexpected": sorted(observed - expected)}


def validate_family(contract, family: dict, schema: dict) -> list[str]:
    """Validate each condition-specific correlation instead of treating a list as a variable."""
    errors = []
    members = family.get("members", [])
    if not contract.design or contract.design.family not in {"correlation", "paired_t"}:
        errors.append("analysis-family adapter supports explicit paired tests or correlations")
    ids = [m.get("member_id") for m in members]
    if not ids or None in ids or len(set(ids)) != len(ids):
        errors.append("family requires unique nonempty member IDs")
    tables = {(Path(f["path"]).name, t.get("table")): t for f in schema.get("files", []) for t in f.get("tables", [])}
    for member in members:
        table = tables.get((Path(member.get("file") or "").name, member.get("table")))
        columns = {c["name"]: c for c in (table or {}).get("columns", [])}
        if not all(member.get(k) for k in ("x", "y", "condition", "sample_rule", "evidence")):
            errors.append(f"{member.get('member_id')}: pairing, sample or documentation unresolved")
        if member.get("x") == member.get("y"):
            errors.append("family member must identify two distinct variables")
        for name in (member.get("x"), member.get("y")):
            col = columns.get(name)
            if not col:
                errors.append(f"unknown member column {name}")
                continue
            numeric = any(k in col.get("dtype", "").lower() for k in ("float", "int", "double"))
            profile = col.get("numeric_parse", {})
            parser = member.get("numeric_parsing")
            parsed = parser in {"strict_float", "strict_float_blank_missing"} and profile.get("n_invalid") == 0 and profile.get("n_numeric", 0) > 0 and (not profile.get("n_blank") or parser == "strict_float_blank_missing")
            if not numeric and not parsed:
                errors.append(f"{name}: member needs a validated numeric parser")
    return errors


def separate_sample_context(bindings, selections):
    """An explicit sample selector owns execution; an empty upstream note is context.

    Without a matching documented selector the empty binding remains a blocking
    unresolved input. No interpretation of its free-text note is used here.
    """
    executable, context = [], []
    for b in bindings:
        selection=selections.get(b.get("analysis_id")) or {}
        is_context=(b.get("contract_field")=="sample_rule" and not b.get("chosen") and not b.get("input_columns")
            and selection.get("id_column") and selection.get("evidence")
            and selection.get("file")==b.get("file") and selection.get("table")==b.get("table"))
        (context if is_context else executable).append(b)
    return executable, context
