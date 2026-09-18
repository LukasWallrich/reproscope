"""Score independent source annotations without equating model agreement with truth.

Input JSON: gold and observed lists with source_id, quantity_role, source_kind,
value, comparator, study_id, target_outcome, target_contrast and target_model.
Gold must inventory complete selected pages to count targets both lanes missed.
"""
from __future__ import annotations
import argparse
import json
from collections import Counter
from pathlib import Path
from scipy.stats import beta

FIELDS = ("value", "comparator", "precision", "quantity_kind", "quantity_role", "aggregation", "study_id", "target_outcome", "target_contrast", "target_model")


def score(gold: list[dict], observed: list[dict]) -> dict:
    expected = {r["source_id"]: r for r in gold}
    if len(expected) != len(gold):
        raise ValueError("gold requires unique source occurrences")
    counts = Counter(r["source_id"] for r in observed)
    found = {r["source_id"]: r for r in observed}
    shared = expected.keys() & found.keys()
    errors = {sid: [f for f in FIELDS if expected[sid].get(f) != found[sid].get(f)] for sid in shared}
    errors = {sid: fields for sid, fields in errors.items() if fields}
    duplicates = {sid: n for sid, n in counts.items() if n > 1}
    correct = len([sid for sid in shared if sid not in errors and sid not in duplicates])
    n, wrong = len(observed), len(observed)-correct
    return {"gold": len(gold), "observed": n, "exact_correct": correct,
            "precision": correct/n if n else None,
            "recall": correct/len(gold) if gold else None,
            "both_lane_misses_require_gold": sorted(expected.keys()-found.keys()),
            "unexpected": sorted(found.keys()-expected.keys()), "field_errors": errors,
            "duplicates": duplicates,
            "critical_error_upper_95_if_independent": float(beta.ppf(.95, wrong+1, n-wrong)) if n and wrong < n else 1. if n else None,
            "uncertainty_limit": "Targets cluster within papers; this binomial bound does not establish between-paper generalisation."}


def stratified(gold: list[dict], observed: list[dict]) -> dict:
    return {"overall": score(gold, observed), "strata": {
        key: score([r for r in gold if f"{r.get('quantity_role')}/{r.get('source_kind')}" == key],
                   [r for r in observed if f"{r.get('quantity_role')}/{r.get('source_kind')}" == key])
        for key in sorted({f"{r.get('quantity_role')}/{r.get('source_kind')}" for r in gold+observed})}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotation", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.annotation.read_text())
    result = stratified(data["gold"], data["observed"])
    import hashlib
    result["annotation_sha256"] = hashlib.sha256(args.annotation.read_bytes()).hexdigest()
    result["annotation_provenance"] = data.get("provenance", "not supplied; independent annotation not established")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+"\n")


if __name__ == "__main__":
    main()
