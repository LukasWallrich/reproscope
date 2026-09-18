"""Independent checks of declared Stage 1 computations and their method fields."""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import reference

VERSION = "execution-evidence-3"


def direct_plan(plan):
    """Only scalar column references enter the direct reference adapter."""
    if isinstance(plan, dict) and plan.get("family") in {"paired_t_family", "correlation_family", "likelihood_ratio", "partial_correlation", "linear_regression"}:
        return plan.get("status") == "supported"
    return (isinstance(plan, dict) and plan.get("status") != "unsupported"
            and isinstance(plan.get("family"), str) and plan["family"] in {"paired_t", "correlation", "independent_t", "one_sample_t"}
            and isinstance(plan.get("file"), str) and isinstance(plan.get("x"), str)
            and (plan["family"] in {"independent_t","one_sample_t"} or isinstance(plan.get("y"), str)))


def check_replica(work: Path, packet: dict, *, regenerated_plan: dict | None = None) -> dict:
    path = work / "out/analysis_plan.json"
    if not path.exists():
        return {"version": VERSION, "status": "unverified", "analyses": {}, "reason": "missing regenerated structured analysis plan"}
    try:
        plan_doc = json.loads(path.read_text())
        if "protocol_version" in plan_doc:
            from .plan_protocol import validate_document
            validate_document(plan_doc)
        plans = plan_doc["analyses"]
        if not isinstance(plans, list) or not all(isinstance(p, dict) and isinstance(p.get("analysis_id"), str) and p["analysis_id"] for p in plans):
            raise ValueError("plans require a list of objects with nonempty scalar analysis IDs")
        ids = [p["analysis_id"] for p in plans]
        rows = json.loads((work / "out/results.json").read_text())["results"]
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise ValueError("results must be a list of objects")
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
        return {"version": VERSION, "status": "unverified", "analyses": {}, "reason": "unreadable verification output: " + str(exc)}
    expected = {a["analysis_id"]: a for a in packet.get("analyses", [])}
    # An explicitly unavailable contract may be documented as an unsupported
    # placeholder. It must never carry computed results or satisfy a required duty.
    unavailable = set(packet.get("analyses_without_data", [])) | set(packet.get("analyses_abstained", {}))
    placeholders = {p["analysis_id"] for p in plans if p["analysis_id"] in unavailable
                    and p["analysis_id"] not in expected and p.get("status") == "unsupported"
                    and not any(r.get("analysis_id") == p["analysis_id"] for r in rows)}
    if len(set(ids)) != len(ids) or set(ids) - placeholders != set(expected):
        return {"status": "invalid", "analyses": {}, "reason": "plan must cover each requested analysis exactly once"}
    plans = [p for p in plans if p["analysis_id"] not in placeholders]
    checked = {}
    from .plan_protocol import normalise as normalise_plan
    for raw_plan in plans:
        if plan_doc.get("protocol_version") in {"direct-plan-2", "direct-plan-3"}:
            plan, protocol, unsupported = raw_plan, {"version": plan_doc["protocol_version"], "schema_validated": True, "rules": []}, []
        else:
            plan, protocol, unsupported = normalise_plan(raw_plan)
        aid = plan["analysis_id"]
        analysis = expected[aid]
        errors = []
        design = analysis.get("design") or {}
        if plan.get("status") == "unsupported":
            checked[aid] = {"status": "unverified", "reason": plan.get("reason") or "reference adapter unavailable"}
            continue
        if analysis.get('covariates') and plan.get('family') in {'correlation','correlation_family','paired_t','paired_t_family','independent_t','one_sample_t'}:
            checked[aid]={'status':'unverified','support_status':'unsupported',
                          'reason':'The source analysis includes covariates; an unadjusted direct reference cannot verify that adjusted analysis.'}
            continue
        if plan.get('family') in {'partial_correlation','linear_regression'}:
            from .adjusted_reference import check
            if plan.get('family')=='linear_regression' and any(q.get('quantity_kind') in {'coefficient','t','ci_bound'} for q in analysis.get('quantities',[])) and not analysis.get('coefficient_target'):
                checked[aid]={'status':'unverified','reason':'Requested coefficient identity lacks independent source-only resolution.'}
                continue
            try: checked[aid]=check(work,plan,analysis,rows,regenerated_plan==plan_doc)
            except (ValueError,TypeError,KeyError,OSError,ZeroDivisionError) as exc:
                checked[aid]={'status':'unverified','reason':str(exc)}
            continue
        if plan.get("family") in {"paired_t_family", "correlation_family", "likelihood_ratio"}:
            from .extended_reference import check as check_extended
            try:
                checked[aid] = check_extended(work, plan, analysis, rows, regenerated_plan == plan_doc)
            except (ValueError, TypeError, KeyError, OSError, ZeroDivisionError) as exc:
                checked[aid] = {"status":"unverified", "reason":str(exc)}
            continue
        if not direct_plan(plan):
            checked[aid] = {"status": "unverified", "reason": "direct reference requires a supported family, file and scalar x/y column names; family/vector operations need a separate adapter"}
            continue
        if unsupported:
            checked[aid] = {"status": "unverified", "plan_status": "parsed", "support_status": "unsupported",
                            "computation_status": "not_run", "reason": "; ".join(unsupported), "protocol_normalisation": protocol}
            continue
        for key in ("family", "alternative"):
            if design.get(key) not in (None, "unknown") and plan.get(key) != design[key]:
                errors.append(f"declared {key} differs from contract")
        columns = {c for b in analysis.get("variable_bindings", []) for c in (b.get("input_columns") or ([b["chosen"]] if b.get("chosen") else []))}
        named = analysis.get("members") or []
        if len(named) == 1:
            member = named[0]
            columns |= {member.get("x"), member.get("y")}
            if any(plan.get(k) != member.get(k) for k in ("x", "y", "table")) or Path(plan["file"]).name != Path(member["file"]).name:
                errors.append("scalar member differs from intake pairing")
        if not columns or plan.get("x") not in columns or (plan.get("family") not in {"independent_t","one_sample_t"} and plan.get("y") not in columns):
            errors.append("reference columns not established by intake bindings")
        try:
            _, frame = reference.read_data(work, plan)
            selection = analysis.get("sample_selection") or {}
            for declared in (selection, analysis.get("grouping") or {}):
                if declared and (Path(declared["file"]).name != Path(plan["file"]).name or declared.get("table") != plan.get("table")):
                    errors.append("sample/group binding refers to a different data table")
            # An executor cannot authorise its own exclusions. In the absence of
            # a machine-readable intake selection only the whole deposit is verified.
            ids_selected = plan.get("included_ids")
            if ids_selected is not None:
                identifier = plan.get("id_column")
                if not identifier or identifier not in frame:
                    raise ValueError("sample selection requires a deposited identifier")
                required_ids = selection.get("included_ids")
                if required_ids is None:
                    eligible = reference.numeric_sample(frame, plan)
                    required_ids = eligible[identifier].tolist()
                if set(ids_selected) != set(required_ids) or len(ids_selected) != len(set(ids_selected)):
                    errors.append("declared sample differs from intake-authorised sample")
                if selection.get("id_column", identifier) != identifier:
                    errors.append("declared identifier differs from intake")
            elif selection.get("included_ids") is not None:
                errors.append("intake sample restriction not implemented")
            if plan.get('family')=='one_sample_t' and (design.get('null_value') is None or design['null_value']!=plan.get('null_value')):
                errors.append('one-sample null value not established by intake')
            if plan.get("family") == "independent_t":
                grouping = analysis.get("grouping") or {}
                if not grouping or any(plan.get(k) != grouping.get(k) for k in ("group_column", "group_values")):
                    errors.append("group coding/order not established by intake")
            bound_files = {Path(b["file"]).name for b in analysis.get("variable_bindings", []) if b.get("file")}
            if bound_files and Path(plan["file"]).name not in bound_files:
                errors.append("reference file differs from intake binding")
            independent = reference.from_plan(work, plan)
            quantities = {q["claim_id"]: q for q in analysis.get("quantities", [])}
            compared = 0
            for row in rows:
                if row.get("analysis_id") != aid or row.get("value") is None:
                    continue
                q = quantities.get(row.get("claim_id"), {})
                if q.get("quantity_role") == "supplied_fact":
                    continue
                kind = q.get("quantity_kind")
                metric = {"d": "dz" if plan.get("family") == "paired_t" else "d", "p_value": "p_raw"}.get(kind, kind)
                if metric not in independent or q.get("aggregation", "scalar") != "scalar":
                    continue
                if not math.isclose(float(row["value"]), independent[metric], rel_tol=1e-5, abs_tol=1e-10):
                    errors.append(f"{row['claim_id']}: independently computed {metric} differs")
                if row.get("n") is not None and row["n"] != independent["n"]:
                    errors.append(f"{row['claim_id']}: independently computed sample size differs")
                compared += 1
            status = "invalid" if errors else "verified" if compared and regenerated_plan == plan_doc else "unverified"
            checked[aid] = {**{k: plan.get(k) for k in ("family", "x", "y", "alternative", "included_ids")},
                "n": independent["n"], "df":independent.get("df"), "effect_metric": design.get("effect_metric"),
                "status": status, "problems": errors, "quantities_checked": compared,
                "plan_status": "parsed", "support_status": "supported",
                "computation_status": "recomputed_mismatch" if any("independently computed" in e for e in errors) else "recomputed_match" if compared else "not_run",
                "protocol_normalisation": protocol,
                "method_scope": "contract family/tail, bound columns/file and authorised sample/grouping; independently recalculated supported outputs"}
        except (ValueError, TypeError, KeyError, OSError, ZeroDivisionError) as exc:
            checked[aid] = {"status": "unverified", "reason": str(exc), "problems": errors}
    for aid,analysis in expected.items():
        required={q['claim_id'] for q in analysis.get('quantities',[]) if q.get('quantity_role')!='supplied_fact'}
        supplied={r.get('claim_id') for r in rows if r.get('analysis_id')==aid and r.get('value') is not None}
        missing=sorted(required-supplied)
        item=checked.get(aid,{})
        if missing:
            item['status']='invalid'
            item.setdefault('problems',[]).append('Missing requested computed values: '+', '.join(missing))
        elif item.get('status')=='verified' and item.get('quantities_checked',0)<len(required):
            item['status']='unverified'
            item.setdefault('problems',[]).append('Independent verification did not check every requested quantity.')
    return {"version": VERSION, "analyses": checked,
            "status": "invalid" if any(a["status"] == "invalid" for a in checked.values()) else
                      "verified" if checked and all(a["status"] == "verified" for a in checked.values()) else "partial"}


def stable_method_payload(plan):
    """Compare operation settings; selected IDs are verified against each input sample."""
    from .plan_protocol import METHOD_FIELDS
    out={k:plan.get(k) for k in METHOD_FIELDS if k!='members'}
    if plan.get('members') is not None:
        out['members']=[stable_method_payload(member) for member in plan['members']]
    return out


def perturbation_checks(work: Path, script: Path, packet: dict, environment: dict, rdir: Path) -> dict:
    """Test data dependence and N provenance in fresh private copies.

    Row removal changes analysed N, row permutation must preserve the result, and
    outcome perturbation must agree with the independent reference. Unsupported
    plans remain unverified rather than being assigned guessed perturbations.
    """
    import os
    import subprocess
    import tempfile
    import copy
    import pandas as pd
    import numpy as np
    from .execution import copy_inputs, result_fields, equal
    from .isolation import command, clean_environment
    from .stage1.replicas import script_command
    plan_path = work / 'out/analysis_plan.json'
    if not plan_path.exists():
        return {'status':'unsupported','reason':'no structured plan','checks':[]}
    all_plans = json.loads(plan_path.read_text()).get('analyses', [])
    from .plan_protocol import normalise as normalise_plan, METHOD_FIELDS
    plans = [normalise_plan(p)[0] for p in all_plans if isinstance(p, dict) and not normalise_plan(p)[2]]
    from .plan_protocol import scalar_members
    plans = [p for p in plans if direct_plan(p) and all(m['file'].lower().endswith('.csv') for m in scalar_members(p))]
    initial=check_replica(work,packet,regenerated_plan=json.loads(plan_path.read_text()))
    plans=[p for p in plans if initial.get('analyses',{}).get(p['analysis_id'],{}).get('status')=='verified']
    scalar_plans = [m for p in plans for m in scalar_members(p)]
    if not plans:
        return {'status':'unsupported','reason':'perturbation needs directly bound CSV analyses','checks':[]}
    checks = []
    supported_ids = {p['analysis_id'] for p in plans}
    original = {k:v for k,v in result_fields(json.loads((work/'out/results.json').read_text()),packet).items() if k[0] in supported_ids}
    for operation in ('row_permutation','row_removal','outcome_change'):
        with tempfile.TemporaryDirectory(prefix='reproscope_metamorphic_') as folder:
            fresh=Path(folder)
            copy_inputs(work,fresh)
            test_packet=copy.deepcopy(packet)
            by_file = {}
            for plan in scalar_plans:
                path = (fresh/plan['file']).resolve()
                if not path.is_relative_to((fresh/'data').resolve()):
                    return {'status':'invalid','reason':'plan escapes supplied data','checks':checks}
                by_file.setdefault(path,set()).add(plan['x'])
                if plan.get('family') == 'likelihood_ratio': by_file[path].add(plan['y'])
            for path, columns in by_file.items():
                frame=pd.read_csv(path)
                if operation == 'row_permutation':
                    frame=frame.iloc[::-1]
                elif operation == 'row_removal':
                    if len(frame) < 4:
                        return {'status':'unsupported','reason':'too few rows for removal perturbation','checks':checks}
                    frame=frame.iloc[1:]
                    for analysis in test_packet.get('analyses',[]):
                        selection=analysis.get('sample_selection') or {}
                        if (selection.get('included_ids') is not None and selection.get('id_column') in frame
                                and (fresh/selection.get('file','')).resolve()==path):
                            present=set(frame[selection['id_column']])
                            selection['included_ids']=[i for i in selection['included_ids'] if i in present]
                else:
                    for i,column in enumerate(sorted(columns)):
                        policies = [p for p in scalar_plans if (fresh/p['file']).resolve() == path and (p['x'] == column or (p.get('family') == 'likelihood_ratio' and p['y'] == column))]
                        try:
                            parsed=[reference.numeric_sample(frame,{'family':'one_sample_t','x':column,'numeric_parsing':parser})[column]
                                    for parser in sorted({p.get('numeric_parsing') or 'strict_float' for p in policies})]
                            series=parsed[0]
                            if any(not np.array_equal(series.to_numpy(float),s.to_numpy(float),equal_nan=True) for s in parsed[1:]):
                                return {'status':'failed','reason':'declared parsers disagree on perturbation input values','checks':checks}
                        except (ValueError, TypeError, KeyError) as exc:
                            return {'status':'failed','reason':'perturbation input parser: ' + str(exc),'checks':checks}
                        frame[column]=(series*1.1 if any(p.get('family') == 'likelihood_ratio' for p in policies) else series+np.random.default_rng(571+i).normal(size=len(frame))*max(float(series.std()),1.))
                frame.to_csv(path,index=False)
            if operation=='row_removal' and (fresh/'CONTRACT.json').exists():
                # Revise only the private test packet's eligible IDs to reflect
                # the controller's deliberate removal from its private deposit.
                (fresh/'CONTRACT.json').write_text(json.dumps(test_packet))
            if checks and checks[-1].get('operation') == operation and checks[-1].get('status') == 'unsupported':
                continue
            try:
                cmd, boundary=command(script_command(fresh/'out'/script.name,fresh,environment.get('interpreter')),fresh,environment.get('env'))
                proc=subprocess.run(cmd,cwd=fresh,capture_output=True,text=True,timeout=120,
                    env=clean_environment({**os.environ,**environment.get('env',{})},fresh))
                output=json.loads((fresh/'out/results.json').read_text())
                regenerated=json.loads((fresh/'out/analysis_plan.json').read_text())
                # Stable method fields must survive perturbation. Sample IDs may
                # change only according to the externally authorised sample policy.
                def methods(doc):
                    return [stable_method_payload(p) for p in doc['analyses'] if p.get('analysis_id') in supported_ids]
                method_stable = methods(regenerated) == methods({'analyses': all_plans})
                reference_result=check_replica(fresh,test_packet,regenerated_plan=regenerated if method_stable else None)
                supported = {k:v for k,v in result_fields(output,packet).items() if k[0] in supported_ids}
                stable=equal(original,supported)
                verified = all(reference_result.get('analyses', {}).get(aid, {}).get('status')=='verified' for aid in supported_ids)
                okay=proc.returncode==0 and boundary.get('enforced', False) and method_stable and verified and (stable if operation=='row_permutation' else not stable)
                checks.append({'operation':operation,'status':'verified' if okay else 'failed',
                               'reference':reference_result,'isolation':boundary,
                               'method_stable':method_stable,
                               'execution_ok':proc.returncode==0 and boundary.get('enforced',False),
                               'result_relation_ok':stable if operation=='row_permutation' else not stable})
            except (ValueError,KeyError,OSError,RuntimeError,subprocess.TimeoutExpired) as exc:
                checks.append({'operation':operation,'status':'failed','reason':str(exc)})
    per_analysis={aid:{'status':'verified' if len(checks)==3 and all(
        c.get('execution_ok') and c.get('method_stable') and c.get('result_relation_ok')
        and c.get('reference',{}).get('analyses',{}).get(aid,{}).get('status')=='verified'
        for c in checks) else 'failed'} for aid in supported_ids}
    return {'status':'verified' if all(c['status']=='verified' for c in checks) else 'failed',
            'analysis_ids':sorted(supported_ids),'per_analysis':per_analysis,'checks':checks}
