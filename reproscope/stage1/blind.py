"""Assemble the blind working directory for one replica.

The replica sees only the redacted methods, the value-free contract, the data and
the task. The deterministic value scan runs over the methods, the contract and any
prose shipped with the data; a hit blocks the launch.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .. import artifacts, config, paths
from ..stage0.leakcheck import LeakDetected, result_claim_ids, scan


PROSE_SUFFIXES = {".txt", ".md", ".rtf", ".do", ".log"}



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
        if rel==man.codebook and src.suffix.lower() in {'.xlsx','.xls'}:
            from ..codebooks import text
            name=src.stem+'.codebook.txt'
            (dest/name).write_text(text(src))
            copied.append(name)
        else:
            shutil.copy2(src, dest / src.name)
            copied.append(src.name)
    return copied


PACKET_NOTE = (
    "One block per analysis. Fit each analysis once and write every quantity in its "
    "`quantities` list from that single fit. Analyses listed under analyses_without_data "
    "were abstained at intake; consult analyses_abstained for the precise reason; do not attempt them."
)


def blind_packet(paper_id: str, contract_src: Path) -> dict:
    """The replica's CONTRACT.json: one block per estimand contract, quantities inside it.

    Analyses the data-readiness check could not bind are dropped and listed by id, so
    replicas do not spend effort re-discovering that the data are absent. Claims that no
    contract claims go into `unassigned`.
    """
    doc = json.loads(contract_src.read_text())
    contracts = list(doc.get("contracts", []))
    dropped: list[str] = []

    readiness = stage0_dir(paper_id) / "readiness.json"
    states = json.loads(readiness.read_text()).get("per_analysis_state") or {} if readiness.exists() else {}
    if states:
        keep = {a for a, st in states.items() if st == "complete"}
        contracts = [c for c in contracts if c.get("analysis_id") in keep]
        dropped = sorted(a for a in states if a not in keep)

    from ..source_integrity import source_status
    source_claims=claims(paper_id)
    source = source_status(source_claims)
    recorded_versions=sorted({c.meta.inputs.get("source_integrity_version","unrecorded") for c in source_claims if c.meta})
    by_id = {c.get("claim_id"): c for c in doc.get("claims", [])
             if c.get("claim_id") in source["accepted_claim_ids"]}
    descriptive_ids = []
    if config.config().descriptive_readouts:
        from ..descriptive_reproduction import is_readout
        descriptive_ids = [cid for cid,c in by_id.items() if is_readout(c)]
        by_id = {cid:c for cid,c in by_id.items() if cid not in descriptive_ids}
    # A claim belongs to an analysis even when that analysis was dropped for want of data,
    # so it must not resurface as unassigned.
    claimed = {cid for c in doc.get("contracts", []) for cid in c.get("claim_ids", [])}
    analyses = []
    for contract in contracts:
        # Selection is supplied by intake's executable sample_selection and the
        # audited methods, not retrospective participant-count narratives.
        block = {k: v for k, v in contract.items() if k not in {"claim_ids", "sample_rule"}}
        readiness_doc = json.loads(readiness.read_text()) if readiness.exists() else {}
        for field, name in (("sample_selection", "sample_selections"), ("grouping", "groupings"), ("likelihood_binding", "likelihood_bindings")):
            if contract.get("analysis_id") in readiness_doc.get(name, {}):
                block[field] = {k: v for k, v in readiness_doc[name][contract["analysis_id"]].items() if k != "evidence"}
        scope=readiness_doc.get("binding_scope",{}).get(contract.get("analysis_id"),{})
        # Source justifications can quote the finding that motivated a binding.
        # Execution needs the fixed protocol, while the unblinded report keeps
        # the full assumptions and competing interpretations for inspection.
        block["binding_scope"]={k:scope[k] for k in ('basis','convention_id') if scope.get(k) is not None}
        family = readiness_doc.get("analysis_families", {}).get(contract.get("analysis_id"))
        binding_fields = {"analysis_id", "contract_field", "file", "table", "chosen", "input_columns",
                          "transformation", "numeric_parsing", "expected_type"}
        block["variable_bindings"] = [{k:v for k,v in b.items() if k in binding_fields}
            for b in readiness_doc.get("variable_bindings", []) if b.get("analysis_id") == contract.get("analysis_id")]
        if family:
            # Sample rules are already delivered as operational selection fields.
            # Intake prose can disclose observed N and must not be reintroduced.
            block["members"] = [{k: v for k, v in m.items() if k not in {"evidence", "sample_rule"}} for m in family["members"]]
        block["quantities"] = [
            by_id[cid] for cid in contract.get("claim_ids", []) if cid in by_id
        ]
        # Quantity prose cannot override the canonical analysis definition.
        for quantity in block["quantities"]:
            source_claim=next((c for c in source_claims if c.claim_id==quantity.get('claim_id')),None)
            if source_claim:
                description=(source_claim.description or '').lower()
                if quantity.get('quantity_kind')=='coefficient':
                    if re.search(r'(?<!un)standardi[sz]ed',description):quantity['quantity_kind_raw']='beta'
                    elif re.search(r'unstandardi[sz]ed',description):quantity['quantity_kind_raw']='b'
                if quantity.get('quantity_kind')=='other' and re.search(r'r[- ]squared|r²|r\^2|\br2\b',description):
                    quantity['quantity_kind_raw']='r2'
                from ..statistic_metadata import canonical_aggregation
                quantity['aggregation']=canonical_aggregation(source_claim)
            for key in list(quantity):
                if key not in {"claim_id", "quantity_kind", "quantity_kind_raw", "quantity_role", "aggregation", "member_ids", "uncertainty_metric"}:
                    quantity.pop(key)
            if family and quantity.get("aggregation") in {"all", "any", "vector", "min", "max"}:
                quantity["member_ids"] = [m["member_id"] for m in family["members"]]
            quantity["description"] = f"{quantity.get('quantity_kind', 'quantity')} for {block.get('analysis_label') or block.get('analysis_id')}"
        if block["quantities"]:
            analyses.append(block)

    assignment_path = stage0_dir(paper_id) / "contract_assignments.json"
    assignment_abstentions = json.loads(assignment_path.read_text()).get("unassigned", []) if assignment_path.exists() else []
    excluded_assignments = {u["claim_id"] for u in assignment_abstentions}
    unassigned = [c for cid, c in by_id.items() if cid not in claimed and cid not in excluded_assignments]
    packet = {"analyses": analyses, "note": PACKET_NOTE,
              "source_gate_version": recorded_versions[0] if len(recorded_versions)==1 else recorded_versions,
              "source_excluded_claim_ids": sorted(source["invalid_claims"])}
    if descriptive_ids:
        packet["descriptive_claim_ids"] = sorted(descriptive_ids)
        packet["descriptive_scope"] = "These quantities are routed to independently verified descriptive readouts, not omitted computations."
    if excluded_assignments:
        packet["assignment_excluded_claim_ids"] = sorted(excluded_assignments)
    if unassigned:
        packet["unassigned"] = unassigned
    if dropped:
        packet["analyses_without_data"] = dropped  # compatibility ID list
        readiness_doc = json.loads(readiness.read_text()) if readiness.exists() else {}
        packet["analyses_abstained"] = {aid: {
            "outcome": readiness_doc.get("per_analysis_outcome", {}).get(aid, "unbound"),
            "reason": readiness_doc.get("per_analysis_reasons", {}).get(aid, "binding unresolved")}
            for aid in dropped}
    return packet


def bound_claim_ids(packet: dict) -> set[str]:
    """Every claim_id a replica was asked about, across all blocks of a blind packet."""
    ids = {q.get("claim_id") for a in packet.get("analyses", []) for q in a.get("quantities", [])}
    ids |= {c.get("claim_id") for c in packet.get("unassigned", [])}
    return {cid for cid in ids if cid}


def assemble(paper_id: str, replica_id: str) -> Path:
    """Create runs/<paper_id>/stage1/replicas/<replica_id>/work/ and return it."""
    s0 = stage0_dir(paper_id)
    methods_src, contract_src = s0 / "redacted_methods.md", s0 / "blind_contract.json"
    for p in (methods_src, contract_src):
        if not p.exists():
            raise FileNotFoundError(f"stage0 output missing: {p}")

    claim_records = claims(paper_id)
    # Every claim of an analysis that reports a result is forbidden, not only the
    # inferential ones: a mean printed beside a test recovers the test.
    result_ids = result_claim_ids(claim_records, contracts(paper_id))
    work = replica_dir(paper_id, replica_id) / "work"
    (work / "out").mkdir(parents=True, exist_ok=True)
    shutil.copy2(methods_src, work / "METHODS.md")
    (work / "CONTRACT.json").write_text(
        json.dumps(blind_packet(paper_id, contract_src), indent=2, ensure_ascii=False)
    )

    # The scan runs over the files the replica receives, not their stage 0 sources.
    hits = scan(
        [work / "METHODS.md", work / "CONTRACT.json"],
        claim_records,
        paper_id=paper_id,
        result_claim_ids=result_ids,
    )
    if hits:
        shutil.rmtree(work)
        raise LeakDetected(
            f"{len(hits)} reported value(s) found in the blind material; launch blocked:\n  "
            + "\n  ".join(str(h) for h in hits[:20])
        )

    (work / "TASK.md").write_text(replica_task(paper_id))
    copy_data(paper_id, work / "data")

    # Prose shipped with the data (author notes, READMEs) can state the results.
    # Data tables are not scanned: a reported value also occurring as a cell is not leakage.
    notes = [p for p in sorted((work / "data").iterdir()) if p.suffix.lower() in PROSE_SUFFIXES]
    note_hits = scan(notes, claim_records, result_claim_ids=result_ids) if notes else []
    if note_hits:
        shutil.rmtree(work)
        raise LeakDetected(
            f"{len(note_hits)} reported value(s) found in the data folder's notes; launch "
            "blocked. Redact the file or drop it from manifest.data_files:\n  "
            + "\n  ".join(str(h) for h in note_hits[:20])
        )
    from .. import provenance
    audit_path = s0 / "leak_audit.json"
    validate_packet_audit(paper_id)
    (replica_dir(paper_id, replica_id) / "packet_provenance.json").write_text(json.dumps({
        "files": provenance.files({name: work / name for name in ("METHODS.md", "CONTRACT.json", "TASK.md")}),
        "blinding_audit": str(audit_path),
        "isolation": "working-directory separation; OS access restrictions not established"}, indent=2))
    return work


ISOLATION_ROOT = Path("/private/tmp/reproscope_blind")


def isolate(work: Path, paper_id: str, replica_id: str) -> Path:
    """Copy the blind work directory to a location outside the repository and return it."""
    iso = ISOLATION_ROOT / paper_id / replica_id
    if iso.exists():
        shutil.rmtree(iso)
    shutil.copytree(work, iso)
    return iso


def collect(iso: Path, work: Path) -> None:
    """Copy everything the agent produced back into the repository work directory."""
    shutil.copytree(iso, work, dirs_exist_ok=True)


def transcript_hits(agent_log: str) -> list[str]:
    """Lines of the agent transcript that reference material outside the blind directory."""
    # "../data/" from inside out/ stays within the work directory; two levels up does not.
    pattern = re.compile(
        r"\.\./(?!(data|out)/|METHODS\.md|CONTRACT\.json|TASK\.md)|stage0|claims\.json|paper\.(pdf|txt)|/corpus/|/runs/",
        re.IGNORECASE,
    )
    return [ln[:200] for ln in agent_log.splitlines() if pattern.search(ln)]


def replica_task(paper_id: str) -> str:
    task=artifacts.load_prompt("stage1_replica_task")
    if any(c.covariates for c in contracts(paper_id)):
        task+='\n\n'+artifacts.load_prompt('stage1_adjusted_protocol')
    return task


def packet_fingerprint(paper_id: str) -> dict[str, str]:
    import hashlib
    s0 = stage0_dir(paper_id)
    content = {
        "METHODS.md": (s0 / "redacted_methods.md").read_text(),
        "CONTRACT.json": json.dumps(blind_packet(paper_id, s0 / "blind_contract.json"), indent=2, ensure_ascii=False),
        "TASK.md": replica_task(paper_id),
    }
    return {k: hashlib.sha256(v.encode()).hexdigest() for k, v in content.items()}


def validate_packet_audit(paper_id: str) -> None:
    path = stage0_dir(paper_id) / "leak_audit.json"
    audit = json.loads(path.read_text()) if path.exists() else {}
    if not audit.get("packet_fingerprint"):
        raise LeakDetected("final replica packet has no versioned blinding audit; rerun Stage 0 redaction")
    if (audit["packet_fingerprint"] != packet_fingerprint(paper_id)
            or audit.get("blinding_status") not in {"limited", "no_leak_detected"}):
        raise LeakDetected("delivered replica packet differs from its accepted blinding audit")
