"""Step 5: a deterministic schema summary of every data file, then the readiness call."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import artifacts, llm, paths, response_cache

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
    if not pd.api.types.is_numeric_dtype(series) and not non_null.empty:
        text = non_null.astype(str).str.strip()
        blank = text.eq("")
        parsed = pd.to_numeric(text[~blank], errors="coerce")
        finite = parsed.notna() & parsed.map(math.isfinite)
        out["numeric_parse"] = {
            "n_blank": int(blank.sum()), "n_invalid": int((~finite).sum()),
            "n_numeric": int(finite.sum()),
            "min": _jsonable(parsed[finite].min()) if finite.any() else None,
            "max": _jsonable(parsed[finite].max()) if finite.any() else None,
        }
    if pd.api.types.is_numeric_dtype(series) and not non_null.empty:
        out["min"] = _jsonable(non_null.min())
        out["max"] = _jsonable(non_null.max())
        out["mean"] = _jsonable(float(non_null.mean()))
        out["sd"] = _jsonable(float(non_null.std()))
        out["skewness"] = _jsonable(float(non_null.skew()))
        out["n_nonfinite"] = int((~non_null.map(math.isfinite)).sum())
        out["diagnostic_status"] = "computed from deposited column; not an optimizer diagnosis"
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
        rec["deposited_labels"] = (getattr(manifest, "data_labels", {}) or {}).get(p.name, {})
        files.append(rec)
    return {"paper_id": manifest.paper_id, "files": files}


def codebook_text(manifest, summary: dict[str, Any]) -> str:
    """The codebook if the manifest names one, else the free-text notes shipped with the data."""
    if manifest.codebook:
        p = manifest.path(manifest.codebook)
        if p.exists():
            from ..codebooks import text
            return text(p)
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


class InputRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    bounds: list[float] = Field(min_length=2, max_length=2)


RANGE_GUIDANCE = """\nRange scope: allowed_range describes a directly chosen deposited column ONLY. For a derived binding, allowed_range must be []; input_ranges names each raw input column with its documented bounds, and derived_range describes only a source-documented output range. For five items scored 1–5 and summed, each raw input has bounds [1,5]; [5,25] is never an input range. Do not invent bounds or widen them to observed minima/maxima. A derived output range is deferred until that variable is independently materialized, never checked against its individual items.
The reconstruction starting point is the deposited dataset. When a deposited total/subscale column is uniquely identified by the source and labels, bind that column directly (chosen, input_columns=[]). Record its item-scoring provenance and upstream uncertainty separately in note; do not substitute a newly derived variable merely to describe how the source defines the measure. If no deposited column represents the required variable, retain an explicit derived binding. Do not choose a column or scoring rule by numerical agreement.\n"""


class SlimBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_field: str
    analysis_id: str | None = None
    candidate_columns: list[str] = []
    chosen: str | None = None
    note: str | None = None
    file: str | None = None
    table: str | None = None
    input_columns: list[str] = []
    transformation: str | None = None
    expected_type: str | None = None
    numeric_parsing: Literal["strict_float", "strict_float_blank_missing"] | None = None
    allowed_range: list[float] = Field(default=[], description="Source-documented bounds of the directly chosen column; empty for derived bindings.")
    input_ranges: list[InputRange] = []
    derived_range: list[float] = Field(default=[], description="Source-documented bounds of a derived output; deferred at intake, never applied to raw inputs.")


from ..sample_filters import RowFilter

class SampleSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str
    table: str | None = None
    id_column: str
    included_ids: list[str | int] | None = None
    filters: list[RowFilter] = []
    evidence: str


class Grouping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str
    table: str | None = None
    group_column: str
    group_values: list[str | int | float]
    evidence: str


from ..binding_policy import Convention

class SlimAnalysisState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    outcome: Literal["bound", "no_data", "unbound"] | None = None
    binding_basis: Literal["source_determined", "conventional_reconstruction", "unresolved"] = "source_determined"
    convention: Convention | None = None
    assumptions: list[str] = []
    alternatives: list[str] = []
    sample_selection: SampleSelection | None = None
    grouping: Grouping | None = None
    state: Literal['complete', 'abstained']
    abstain_reason: str | None = None

    @field_validator('state', mode='before')
    @classmethod
    def canonical_state(cls, value):
        # Earlier model responses used these exact synonyms for an executable
        # binding. All source/sample/field checks still run after normalisation.
        return 'complete' if value in {'ready', 'bound'} else value


class CorrelationMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member_id: str
    file: str
    table: str | None = None
    x: str
    y: str
    condition: str
    exposure: str | None = None
    sample_rule: str
    numeric_parsing: Literal["strict_float", "strict_float_blank_missing"]
    evidence: str


class AnalysisFamily(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_id: str
    members: list[CorrelationMember]


class IntegrityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_id: str
    file: str
    table: str | None = None
    kind: Literal["unique_id", "paired_complete", "nested_loglikelihood"]
    columns: list[str]
    assumption_evidence: str | None = None


class LikelihoodBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_id: str
    file: str
    table: str | None = None
    x: str
    y: str
    full_parameters_per_subject: int = Field(gt=0)
    reduced_parameters_per_subject: int = Field(gt=0)
    aggregation: Literal["sum_subject_loglikelihoods"]
    evidence: str
    assumption: str


class ReadinessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[SlimFile] = []
    unit_of_observation: str | None = None
    keys: list[str] = []
    missing_sentinels: list[str] = []
    variable_bindings: list[SlimBinding] = []
    analysis_families: list[AnalysisFamily] = []
    likelihood_bindings: list[LikelihoodBinding] = []
    integrity_checks: list[IntegrityRequest] = []
    scale_direction_notes: list[str] = []
    weights_columns: list[str] = []
    derived_variables_needed: list[str] = []
    per_analysis: list[SlimAnalysisState] = []
    open_ambiguities: list[str] = []
    confidence: str | None = None


class ReadinessPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    per_analysis: list[SlimAnalysisState] = []
    variable_bindings: list[SlimBinding] = []
    analysis_families: list[AnalysisFamily] = []
    likelihood_bindings: list[LikelihoodBinding] = []
    integrity_checks: list[IntegrityRequest] = []


def read_response(path, fingerprint, schema, prompt, tier, options=None):
    """Reuse an intact pre-enum response after strict status normalisation."""
    saved=response_cache.read(path,fingerprint,schema)
    if saved:return saved
    class UnscopedRangesSchema:
        @staticmethod
        def model_json_schema():
            previous=schema.model_json_schema()
            binding=previous.get('$defs',{}).get('SlimBinding',{}).get('properties',{})
            binding.pop('input_ranges',None);binding.pop('derived_range',None)
            if 'allowed_range' in binding:binding['allowed_range'].pop('description',None)
            previous.get('$defs',{}).pop('InputRange',None)
            return previous
    old_prompt=prompt.replace(RANGE_GUIDANCE,'')
    old_range_key=response_cache.key(old_prompt,UnscopedRangesSchema,[],tier,options)
    saved=response_cache.read(path,old_range_key,schema)
    if saved:
        # Preserve every old range verbatim. Derived ambiguous ranges now fail
        # validation and require source-only model repair; no scope is inferred.
        response_cache.write(path,fingerprint,saved[0],saved[1])
        receipt_path=Path(path).parent/'readiness_initial_batches.json'
        if receipt_path.exists():
            receipt=json.loads(receipt_path.read_text())
            if receipt.get('response_key')==old_range_key:
                receipt['response_key']=fingerprint
                receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
        return saved
    class PreviousSchema:
        @staticmethod
        def model_json_schema():
            previous=schema.model_json_schema()
            previous['$defs']['SlimAnalysisState']['properties']['state'].pop('enum',None)
            return previous
    old_key=response_cache.key(prompt,PreviousSchema,[],tier,options)
    saved=response_cache.read(path,old_key,schema)
    if saved:
        response_cache.write(path,fingerprint,saved[0],saved[1])
        receipt_path=Path(path).parent/'readiness_initial_batches.json'
        if receipt_path.exists():
            receipt=json.loads(receipt_path.read_text())
            if receipt.get('response_key')==old_key:
                receipt['response_key']=fingerprint
                receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
    return saved


def apply_patch(candidate, patch, allowed):
    """Replace only explicitly supplied records for the requested analyses."""
    output=candidate.model_copy(deep=True)
    for field in ReadinessPatch.model_fields:
        updates=getattr(patch,field)
        if any(x.analysis_id not in allowed for x in updates):
            raise ValueError('readiness repair changed an unrequested analysis')
        key=lambda x:(x.analysis_id,x.contract_field) if field=='variable_bindings' else x.analysis_id
        keys=[key(x) for x in updates]
        if field!='integrity_checks' and len(keys)!=len(set(keys)):
            raise ValueError('readiness repair contains duplicate records')
        touched=set(keys)
        setattr(output,field,[x for x in getattr(output,field) if key(x) not in touched]+updates)
    if {x.analysis_id for x in patch.per_analysis}!=allowed:
        raise ValueError('readiness repair must account for every requested analysis')
    return output


def repair_batches(candidate, contracts, errors, repair_ids, summary, paper, codebook, folder, paper_id, depth):
    """Bound output size by required binding fields, retaining exact analysis scope."""
    from concurrent.futures import ThreadPoolExecutor
    groups=[];group=[];size=0
    for contract in contracts:
        if contract.analysis_id not in repair_ids:continue
        need=1+len(contract.predictors)+len(contract.covariates)
        if group and size+need>40:groups.append(group);group=[];size=0
        group.append(contract);size+=need
    if group:groups.append(group)
    def one(entry):
        index,group=entry;ids={c.analysis_id for c in group}
        payload={'errors':{aid:errors[aid] for aid in sorted(ids)},
            'contracts':[c.model_dump(exclude={'meta','claim_ids'},exclude_none=True) for c in group],
            'candidate':{key:[x.model_dump() for x in getattr(candidate,key) if x.analysis_id in ids] for key in ReadinessPatch.model_fields},
            'shared_candidate_bindings':[b.model_dump() for b in candidate.variable_bindings if b.analysis_id is None],
            'schema':summary,'codebook':codebook,'paper':paper}
        prompt=("Repair the exact requested readiness analyses. No reproduction results are supplied. Return one per_analysis record per requested ID and complete replacement bindings for EVERY outcome, predictors[i] and covariates[i], using each analysis_id explicitly. "
            "Shared prose descriptions, null analysis_id and free-text contract_field are not executable bindings. Duplicate a shared column binding under each actual contract field that needs it; do not omit covariates that also occur as predictors. "
            "Use exact deposited columns and source-supported coding. Do not infer exclusions, recodings or scale identities from reported numerical agreement. Return source_determined when directly established; otherwise abstain with a precise missing-input/source reason. "
            "Integrity checks must name a requested analysis_id. Existing unaffected analyses and their bindings are not part of this repair. Return only the schema.\n"+json.dumps(payload,separators=(',',':'))+RANGE_GUIDANCE)
        def validate(patch):
            apply_patch(candidate,patch,ids)
            missing={}
            for contract in group:
                state=next(a for a in patch.per_analysis if a.analysis_id==contract.analysis_id)
                if state.state!='complete':continue
                required={'outcome'}|{f'predictors[{i}]' for i in range(len(contract.predictors))}|{f'covariates[{i}]' for i in range(len(contract.covariates))}
                actual={b.contract_field for b in patch.variable_bindings if b.analysis_id==contract.analysis_id}
                if required-actual:missing[contract.analysis_id]=sorted(required-actual)
            if missing:raise ValueError('Missing executable fields: '+json.dumps(missing,sort_keys=True))
            if summary.get('files'):
                from ..intake_validation import validate_bindings
                complete={a.analysis_id for a in patch.per_analysis if a.state=='complete'}
                invalid=validate_bindings([c for c in group if c.analysis_id in complete],
                    [b.model_dump() for b in patch.variable_bindings],summary)
                invalid={aid:errors for aid,errors in invalid.items() if errors}
                if invalid:raise ValueError('Binding/schema validation failed: '+json.dumps(invalid,sort_keys=True))
        # Previously accepted repairs remain reusable even when their failed
        # first attempt was not cached by an earlier controller.
        for attempt in (1,2):
            old_prompt=prompt if attempt==1 else prompt+'\nThe previous response did not supply exact requested per-analysis/field coverage. Required IDs: '+json.dumps(sorted(ids))
            path=folder/f'readiness_patch{depth+1}_batch{index}_attempt{attempt}.response.json'
            saved=read_response(path,response_cache.key(old_prompt,ReadinessPatch,[],'strong'),ReadinessPatch,old_prompt,'strong')
            if saved:
                try:validate(saved[0])
                except (ValueError,StopIteration):pass
                else:return saved[0],ids,saved[1]
        from .. import config
        repair_tier='contract_repair' if 'contract_repair' in config.config().tiers else 'strong'
        feedback=''
        for attempt,tier in enumerate(('strong','strong',repair_tier),1):
            shown=prompt+feedback
            path=folder/f'readiness_patch{depth+1}_batch{index}_attempt{attempt}.response.json'
            key=response_cache.key(shown,ReadinessPatch,[],tier)
            path=folder/f'readiness_patch{depth+1}_batch{index}_attempt{attempt}_{key[:12]}.response.json'
            saved=read_response(path,key,ReadinessPatch,shown,tier)
            if saved:patch,cid=saved
            else:
                result=llm.call('readiness:binding_batch_repair',shown,paper_id=paper_id,stage='0',tier=tier,schema=ReadinessPatch,
                    timeout_s=1800,large_context=True,log_path=path.with_suffix('.log'))
                patch,cid=result.parsed,result.ledger_id
            if patch is None:
                feedback='\nA prior request returned no structured response. Return every required analysis and field.'
                continue
            response_cache.write(path,key,patch,cid or '')
            try:
                validate(patch)
            except (ValueError,StopIteration) as exc:
                feedback='\nValidation failed: '+str(exc)+'\nReturn a complete corrected patch for this same batch. Bind each indexed field separately, even when a column also occurs under another role. Previous response:\n'+patch.model_dump_json()
                continue
            return patch,ids,cid
        raise ValueError(f'readiness binding repair batch {index} failed exact scope')
    with ThreadPoolExecutor(max_workers=3) as pool:patches=list(pool.map(one,enumerate(groups,1)))
    repaired=candidate
    for patch,ids,_ in patches:repaired=apply_patch(repaired,patch,ids)
    return repaired,[cid for _,_,cid in patches if cid]


def scoped_integrity_requests(requests, selections):
    """A declared dataset-wide ID check applies to each analysis using that table."""
    expanded=[]
    for request in requests:
        if request.analysis_id=='global' and request.kind=='unique_id':
            matches=[aid for aid,s in selections.items() if Path(s['file']).name==Path(request.file).name and s.get('table')==request.table]
            if not matches:raise ValueError('global ID check has no source-bound analysis sample')
            expanded.extend(request.model_copy(update={'analysis_id':aid}).model_dump() for aid in matches)
        else:expanded.append(request.model_dump())
    return expanded


def run(
    manifest,
    contract_records: list[artifacts.EstimandContract],
    inputs: dict[str, str] | None = None,
    force: bool = False,
    tier: str = "mid",
    _candidate=None,
    _call_ids=None,
    _repair_depth=0,
) -> tuple[artifacts.DataReadinessRecord, list[str]]:
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    schema_path = stage_dir / "schema.json"
    out_path = stage_dir / "readiness.json"
    paper_path=manifest.dir/"paper.txt"
    paper_source=paper_path.read_text() if paper_path.exists() else ""

    # Profiling is deterministic and must follow the actual data, even when the shape
    # or the outer step's inputs happen to be unchanged.
    schema_path.write_text(json.dumps(schema_summary(manifest), indent=2) + "\n")
    summary = json.loads(schema_path.read_text())
    from .. import provenance
    inputs = {**(inputs or {}), "schema": artifacts.sha256_file(schema_path),
              "contracts": artifacts.content_hash(contract_records), "paper_text":provenance.digest(paper_source),
              "codebook": provenance.digest(codebook_text(manifest, summary)), "readiness_tier": tier}

    if out_path.exists() and not force and _candidate is None:
        existing = artifacts.load(artifacts.DataReadinessRecord, out_path)
        if (
            not artifacts.prompt_stale(existing, PROMPTS)  # type: ignore[arg-type]
            and existing.meta is not None  # type: ignore[union-attr]
            and existing.meta.inputs == (inputs or {})  # type: ignore[union-attr]
        ):
            return existing, []  # type: ignore[return-value]

    # Source wording constrains within-condition scope; choices must be made before any reproduction results exist.
    contract_payload = [c.model_dump(exclude={"meta","claim_ids"}, exclude_none=True) for c in contract_records]
    schema_text = json.dumps(summary, indent=1)
    contracts_text = json.dumps(contract_payload, indent=1)
    # Preserve small cached requests; remove formatting overhead from wide deposits
    # without dropping columns, source evidence, or analysis duties.
    if len(schema_text) + len(contracts_text) + len(paper_source) > 200000:
        schema_text = json.dumps(summary, separators=(",", ":"))
        contracts_text = json.dumps(contract_payload, separators=(",", ":"))
    prompt = artifacts.load_prompt(
        "stage0_readiness",
        paper=paper_source,
        schema=schema_text,
        codebook=codebook_text(manifest, summary),
        contracts=contracts_text,
    ) + RANGE_GUIDANCE
    response_options={"source_inputs": {k:v for k,v in inputs.items() if k == "pdf" or k.startswith("data:")}}
    response_key = response_cache.key(prompt, ReadinessOut, [], tier,response_options)
    response_path = stage_dir / "logs" / f"readiness.{tier}.response.json"
    cached = read_response(response_path,response_key,ReadinessOut,prompt,tier,response_options) if not force and _candidate is None else None
    if cached is None and not force and _candidate is None:
        cached = read_response(stage_dir / "logs" / "readiness.response.json",response_key,ReadinessOut,prompt,tier,response_options)
        if cached:response_cache.write(response_path, response_key, cached[0], cached[1])
    batch_receipt=stage_dir/'logs/readiness_initial_batches.json'
    if cached and batch_receipt.exists():
        receipt=json.loads(batch_receipt.read_text())
        if receipt.get('response_key')==response_key:_call_ids=receipt['model_calls']
    if cached is None and _candidate is None and sum(1+len(c.predictors)+len(c.covariates) for c in contract_records)>40:
        # Every per-analysis binding is a bounded task from the outset. File
        # metadata comes from the parsed deposit; analytical identities remain
        # source-reviewed within each batch rather than inferred by the controller.
        candidate=ReadinessOut(files=[SlimFile(path=f['path'],format=f.get('format'),
            rows=(f.get('tables') or [{}])[0].get('rows') if len(f.get('tables',[]))==1 else None,
            cols=len((f.get('tables') or [{}])[0].get('columns',[])) if len(f.get('tables',[]))==1 else None)
            for f in summary['files']],
            per_analysis=[SlimAnalysisState(analysis_id=c.analysis_id,state='abstained',outcome='unbound',
                abstain_reason='Initial source binding task.') for c in contract_records])
        requested={c.analysis_id for c in contract_records}
        candidate,cids=repair_batches(candidate,contract_records,{aid:['Establish all required source-grounded bindings and sample rules.'] for aid in requested},
            requested,summary,paper_source,codebook_text(manifest,summary),stage_dir/'logs',manifest.paper_id,0)
        response_cache.write(response_path,response_key,candidate,cids[-1])
        batch_receipt.write_text(json.dumps({'response_key':response_key,'model_calls':cids,'max_fields_per_batch':40},indent=2)+'\n')
        return run(manifest,contract_records,inputs,force=False,tier=tier,_candidate=candidate,_call_ids=cids,_repair_depth=1)
    r = (llm.LLMResult(text="",parsed=_candidate,ledger_id=(_call_ids or [''])[-1]) if _candidate is not None else
         llm.LLMResult(text="", parsed=cached[0], ledger_id=cached[1]) if cached else llm.call(
        "readiness",
        prompt,
        paper_id=manifest.paper_id,
        stage="0",
        tier=tier,
        schema=ReadinessOut,
        cwd=manifest.dir / "data",
        timeout_s=3600,
        large_context=True,
        log_path=stage_dir / "logs" / "readiness.log",
    ))
    if r.parsed is None:
        raise llm.LLMError(f"readiness failed: {r.error}")
    if not cached and _candidate is None:
        response_cache.write(response_path, response_key, r.parsed, r.ledger_id or "")
    out: ReadinessOut = r.parsed  # type: ignore[assignment]

    record = artifacts.DataReadinessRecord.model_validate(
        {
            "meta": artifacts.ArtifactMeta(
                artifact="DataReadinessRecord",
                stage="0",
                inputs=inputs or {},
                prompt_versions={n: artifacts.prompt_version(n) for n in PROMPTS},
                model_calls=_call_ids or [r.ledger_id or ""],
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
    record.per_analysis_outcome = {
        a.analysis_id: ("bound" if a.state == "complete" else a.outcome or "unbound")
        for a in out.per_analysis}
    from ..intake_validation import validate_bindings, separate_sample_context
    # A declared likelihood adapter defines a derived outcome from two columns.
    # Its pair is not an unresolved choice between two scalar outcomes.
    likelihoods={b.analysis_id:b for b in out.likelihood_bindings}
    for b in record.variable_bindings:
        lr=likelihoods.get(b.analysis_id)
        if (lr and b.contract_field=='outcome' and not b.chosen and not b.input_columns
                and set(b.candidate_columns or [])=={lr.x,lr.y}
                and b.file==lr.file and b.table==lr.table):
            b.input_columns=[lr.x,lr.y]
            b.transformation='2 * (sum(full_loglikelihood) - sum(restricted_loglikelihood)); columns ordered full, restricted'
            b.note=(b.note or '')+' Derived outcome defined by the declared likelihood_bindings protocol.'
    declared_selections={a.analysis_id:a.sample_selection.model_dump() for a in out.per_analysis if a.sample_selection is not None}
    executable_bindings, sample_context = separate_sample_context([b.model_dump() for b in record.variable_bindings], declared_selections)
    record.upstream_sample_context = sample_context
    context_ids={(b["analysis_id"],b["contract_field"]) for b in sample_context}
    record.variable_bindings = [b for b in record.variable_bindings if (b.analysis_id,b.contract_field) not in context_ids]
    binding_problems = validate_bindings(contract_records, executable_bindings, summary)
    from ..intake_validation import validate_family
    families = {f.analysis_id: f.model_dump() for f in out.analysis_families}
    if len(families) != len(out.analysis_families) or not families.keys() <= {c.analysis_id for c in contract_records}:
        raise ValueError("analysis families require exact unique known analysis IDs")
    for ct in contract_records:
        if ct.analysis_id in families:
            binding_problems[ct.analysis_id] = validate_family(ct, families[ct.analysis_id], summary)
    tables = {(Path(f['path']).name, t.get('table')): t for f in summary.get('files', []) for t in f.get('tables', [])}
    record.sample_selections, record.groupings = {}, {}
    record.binding_scope={a.analysis_id:{"basis":a.binding_basis,"assumptions":a.assumptions,"alternatives":a.alternatives,"convention_id":a.convention.convention_id if a.convention else None} for a in out.per_analysis}
    for analysis in out.per_analysis:
        if analysis.state=='complete' and (analysis.binding_basis=='unresolved' or (analysis.binding_basis=='conventional_reconstruction' and not analysis.assumptions)):
            binding_problems.setdefault(analysis.analysis_id,[]).append('executable reconstruction requires a declared basis and explicit assumptions')
        if analysis.binding_basis=='conventional_reconstruction':
            from ..binding_policy import check as check_convention
            bound={name for b in record.variable_bindings if b.analysis_id==analysis.analysis_id for name in (b.input_columns or ([b.chosen] if b.chosen else []))}
            bound|={m[k] for m in families.get(analysis.analysis_id,{}).get('members',[]) for k in ('x','y')}
            if analysis.convention is None and analysis.analysis_id in likelihoods and analysis.assumptions:
                # This method has its own closed declaration and mandatory nesting
                # checks below; it does not choose between condition-column pairs.
                record.binding_scope[analysis.analysis_id]['convention_id']='subject_loglikelihood_sum'
            else:
                binding_problems.setdefault(analysis.analysis_id,[]).extend(check_convention(analysis.convention,paper_source,bound))
        for field, collection, column_key in (("sample_selection", record.sample_selections, "id_column"),
                                              ("grouping", record.groupings, "group_column")):
            item = getattr(analysis, field)
            if item is None:
                continue
            value = item.model_dump()
            table = tables.get((Path(item.file).name, item.table), {})
            columns = {c['name']: c for c in table.get('columns', [])}
            problems = binding_problems.setdefault(analysis.analysis_id, [])
            if not item.evidence.strip() or value[column_key] not in columns:
                problems.append(f"{field}: source evidence or column unresolved")
                continue
            if field == "grouping" and (len(item.group_values) != 2 or len(set(item.group_values)) != 2):
                problems.append("grouping requires two distinct ordered group codes")
                continue
            if field == "sample_selection" and item.included_ids is not None and len(set(item.included_ids)) != len(item.included_ids):
                problems.append("sample selection contains duplicate IDs")
                continue
            if field=='sample_selection' and item.filters:
                try:
                    from ..reference import read_data
                    from ..sample_filters import select
                    _,frame=read_data(manifest.dir,{'file':item.file,'table':item.table})
                    selected=select(frame,item.filters)
                    if selected[item.id_column].isna().any() or selected[item.id_column].duplicated().any():raise ValueError('sample predicates must select unique nonmissing participant IDs')
                    selected_ids=selected[item.id_column].tolist()
                    if item.included_ids is not None and set(item.included_ids)!=set(selected_ids):raise ValueError('explicit IDs disagree with source-defined predicates')
                    value['included_ids']=selected_ids
                    value['selection_protocol']='column_filters_1'
                except (ValueError,TypeError,KeyError,OSError) as exc:
                    problems.append('sample selection: '+str(exc));continue
            collection[analysis.analysis_id] = value
    record.likelihood_bindings = {}
    for item in out.likelihood_bindings:
        problems = binding_problems.setdefault(item.analysis_id, [])
        bound = {c for b in out.variable_bindings if b.analysis_id == item.analysis_id for c in (b.input_columns or ([b.chosen] if b.chosen else []))}
        if (item.analysis_id not in {c.analysis_id for c in contract_records}
                or item.analysis_id in record.likelihood_bindings or not item.evidence.strip()
                or not item.assumption.strip() or item.full_parameters_per_subject <= item.reduced_parameters_per_subject
                or item.x not in bound or item.y not in bound):
            problems.append("likelihood parameter counts, columns, evidence or aggregation assumption unresolved")
        else:
            record.likelihood_bindings[item.analysis_id] = item.model_dump()
    record.analysis_families = families
    record.convention_evidence={a.analysis_id:a.convention.model_dump() for a in out.per_analysis if a.convention}
    record.reproduction_scope = {"starting_point": "deposited_data", "upstream_recomputed": False,
                                "note": "Binding deposited summaries does not verify their preprocessing or fitting."}
    for aid, problems in binding_problems.items():
        if problems:
            record.per_analysis_state[aid] = "abstained"
            if record.per_analysis_outcome.get(aid) != "no_data":
                record.per_analysis_outcome[aid] = "no_data" if not manifest.data_files else "unbound"
            if record.per_analysis_outcome.get(aid) != "no_data" or not record.per_analysis_reasons.get(aid):
                record.per_analysis_reasons[aid] = "; ".join(problems)
    from .. import data_checks
    requests = data_checks.require_likelihood_checks(scoped_integrity_requests(out.integrity_checks,record.sample_selections), record.likelihood_bindings)
    record.data_integrity = data_checks.run(manifest, requests,
                                           bindings=record.variable_bindings, families=families,
                                           sample_selections=record.sample_selections)
    for diagnostic in record.data_integrity:
        aid = diagnostic["analysis_id"]
        if aid not in {c.analysis_id for c in contract_records}:
            raise ValueError("integrity check identifies unknown analysis")
        if diagnostic["status"] == "unverified" and aid in record.likelihood_bindings and diagnostic["kind"] == "nested_loglikelihood":
            record.per_analysis_state[aid] = "abstained"
            record.per_analysis_outcome[aid] = "unbound"
            record.per_analysis_reasons[aid] = "required nested-likelihood diagnostic could not execute"
        if diagnostic["status"] == "anomaly" and record.per_analysis_outcome.get(aid) not in {"no_data", "unbound"}:
            record.per_analysis_state[aid] = "abstained"
            record.per_analysis_outcome[aid] = "data_invalid"
            record.per_analysis_reasons[aid] = "deposit anomaly in " + diagnostic["kind"] + "; inspect data_integrity evidence"
    record.binding_validation = binding_problems
    if any(record.per_analysis_state.get(c.analysis_id) != "complete" for c in contract_records):
        record.state = "abstained"
    from ..intake_validation import gate_source_identity
    gate_source_identity(record, contract_records)
    repair_ids={aid for aid,errors in binding_problems.items() if errors and record.per_analysis_outcome.get(aid)
                not in {'no_data','data_invalid','source_unresolved'}}
    if repair_ids and paper_source and _repair_depth<2:
        if sum(1+len(c.predictors)+len(c.covariates) for c in contract_records if c.analysis_id in repair_ids)>40:
            repaired,cids=repair_batches(out,contract_records,binding_problems,repair_ids,summary,paper_source,
                codebook_text(manifest,summary),stage_dir/'logs',manifest.paper_id,_repair_depth)
            return run(manifest,contract_records,inputs,force=False,tier=tier,_candidate=repaired,
                       _call_ids=[*record.meta.model_calls,*cids],_repair_depth=_repair_depth+1)
        fields=ReadinessPatch.model_fields
        candidate={k:[x.model_dump() for x in getattr(out,k) if x.analysis_id in repair_ids] for k in fields}
        repair_prompt=("Repair only the requested data-readiness records using source evidence. No reproduction outputs are supplied. "
            "Return every requested per_analysis record; other collections contain only complete replacement entries that change. "
            "Preserve all unaffected analyses. Do not change binding to fit a printed result. Resolve validator failures, or abstain "
            "with a specific missing-input/source reason. A scope quotation must be literal (normalised typography is allowed); "
            "choose a short contiguous per-condition clause, not a reconstructed sentence containing different reported statistics. "
            "A declared likelihood_bindings recipe defines its derived outcome; its summation assumption can be an explicit conventional "
            "reconstruction under the subject_loglikelihood_sum adapter without a condition-matching convention. "
            "Binding identity is distinct from reproducing upstream fitting: a source-identified paired contrast with uniquely corresponding measure/condition-labelled deposited columns is source_determined for that binding, even when the original fitting code is unavailable. Document the labels and source conditions; retain upstream uncertainty separately. "
            "condition_matched_columns is only for matching two different measures within the SAME literal condition index; it cannot describe a paired contrast BETWEEN conditions, and index is not the participant ID. Do not force such a contrast into this convention. If source and column labels do not uniquely establish its identity, abstain and name the competing interpretation. "
            "Never change data to repair a nesting anomaly.\n"+json.dumps({'errors':{a:binding_problems[a] for a in sorted(repair_ids)},
                'candidate':candidate,'contracts':[c.model_dump(exclude={'meta','claim_ids'}) for c in contract_records if c.analysis_id in repair_ids],
                'schema':summary,'paper':paper_source}))+RANGE_GUIDANCE
        path=stage_dir/'logs'/f'readiness_patch{_repair_depth+1}.response.json'
        key=response_cache.key(repair_prompt,ReadinessPatch,[],'strong')
        saved=read_response(path,key,ReadinessPatch,repair_prompt,'strong')
        if saved:patch,cid=saved
        else:
            result=llm.call('readiness:validation_repair',repair_prompt,paper_id=manifest.paper_id,stage='0',tier='strong',
                schema=ReadinessPatch,timeout_s=600,log_path=path.with_suffix('.log'))
            patch,cid=result.parsed,result.ledger_id
            if patch is not None:response_cache.write(path,key,patch,cid or '')
        if patch is not None:
            repaired=apply_patch(out,patch,repair_ids)
            return run(manifest,contract_records,inputs,force=False,tier=tier,_candidate=repaired,
                       _call_ids=[*record.meta.model_calls,cid or ''],_repair_depth=_repair_depth+1)
    artifacts.save(record, out_path)
    return record, record.meta.model_calls
