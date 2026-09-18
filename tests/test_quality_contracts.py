"""Adversarial regression cases for evidence, statistics, and artifact acceptance."""
import copy
import csv
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from reproscope import artifacts, cohort, execution, focal, paths, provenance, reference
from reproscope.intake_validation import score_sets, validate_bindings
from reproscope.stage1 import audit, replicas
from reproscope.stage2 import mde, review
from reproscope.stage3 import multiverse as mv
import reproscope.stage3 as stage3
from reproscope.statistical import AnalysisDesign, adjusted_p, monte_carlo_p, validate_result


def test_atomic_contract_identity_preserves_duplicate_source_records():
    from reproscope.stage0.contracts import AnalysisIdentity, SlimContract, validate_assignments
    claims = [artifacts.ClaimRecord(claim_id=cid, study_id="study1", quantity_kind="t", value=4.71)
              for cid in ("c1", "c2", "c3")]
    identity = AnalysisIdentity(study="study1", outcome="speed", contrast="cue_vs_none",
                                model="paired_t", sample="complete_pairs")
    speed = SlimContract(analysis_id="a1", identity=identity, study_id="study1", claim_ids=["c1", "c2"])
    # The same printed value for a different outcome must remain a separate analysis.
    threshold = SlimContract(analysis_id="a2", identity=identity.model_copy(update={"outcome": "threshold"}),
                             study_id="study1", claim_ids=["c3"])
    assert validate_assignments([speed, threshold], claims) == []
    threshold.identity = identity
    assert any("duplicate atomic" in e for e in validate_assignments([speed, threshold], claims))
    threshold.identity = identity.model_copy(update={"outcome": "threshold"})
    threshold.claim_ids = ["c2", "c3"]
    assert any("exactly one" in e for e in validate_assignments([speed, threshold], claims))
    threshold.claim_ids = ["c3"]
    threshold.study_id = "study2"
    assert any("study differs" in e for e in validate_assignments([speed, threshold], claims))


def test_numeric_string_binding_requires_explicit_parser_and_checks_all_rows():
    import pandas as pd
    from reproscope.stage0.readiness import _column_summary
    contract = artifacts.EstimandContract(analysis_id="a1", outcome="pupil")
    binding = {"analysis_id": "a1", "contract_field": "outcome", "file": "data.csv",
               "table": None, "chosen": "pupil", "expected_type": "numeric"}
    def check(values):
        column = _column_summary(pd.Series(values, name="pupil"))
        schema = {"files": [{"path": "data.csv", "tables": [{"table": None,
                  "rows": len(values), "columns": [column]}]}]}
        return validate_bindings([contract], [binding], schema)["a1"]
    assert check([".07", "-.04", " "])
    binding["numeric_parsing"] = "strict_float"
    assert check([".07", "-.04", " "])
    binding["numeric_parsing"] = "strict_float_blank_missing"
    assert check([".07", "-.04", " "]) == []
    assert check([".07", "-.04", " ", "not measured"])
    assert check([".07", "inf", " "])
    binding["allowed_range"] = [0, 1]
    assert any("input range check failed" in p for p in check([".07", "-.04", " "]))


def test_stage0_downstream_changes_do_not_invalidate_paid_upstream(monkeypatch):
    import reproscope.stage0 as s0
    state = {"version": "v1"}
    monkeypatch.setattr(s0, "input_hashes", lambda manifest: {
        "implementation": state["version"], "pdf": "pdf", "models": "models",
        "prompt:stage0_readiness": state["version"]})
    monkeypatch.setattr(artifacts, "prompt_version", lambda name:
                        state["version"] if name == "stage0_readiness" else "fixed")
    monkeypatch.setattr(provenance, "implementation", lambda *modules:
                        state["version"] if "intake_validation.py" in modules else "fixed")
    before = {step: s0.step_inputs(None, step) for step in ("arbitrate", "contracts", "readiness")}
    state["version"] = "v2"
    after = {step: s0.step_inputs(None, step) for step in before}
    assert before["arbitrate"] == after["arbitrate"]
    assert before["contracts"] == after["contracts"]
    assert before["readiness"] != after["readiness"]


def proposal():
    return {"factors": [{"name": "method", "paper_level": "a", "levels": [
        {"value": "a", "how": "use a"}, {"value": "b", "how": "use b"}]}]}


def screen():
    return {"factors": [{"name": "method", "levels": [
        {"value": "a", "verdict": "defensible"}, {"value": "b", "verdict": "defensible"}]}]}


def test_a_matching_replica_does_not_supply_an_author_level():
    grid = mv.build_grid(proposal(), screen())
    assert grid["factors"][0]["paper_level"] is None
    assert not any(s.get("is_paper_level") for s in mv.enumerate_specs(grid))


def test_rejected_reference_never_enters_summary_denominators():
    verdict = screen()
    verdict["factors"][0]["levels"][0]["verdict"] = "rejected"
    grid = mv.build_grid(proposal(), verdict, paper_levels={"method": "a"})
    rows = [{"_estimate": .4, "_converged": True, "_p": .01, "_role": "defensible"}]
    baseline = mv.rank_reported(rows, .4)
    rows.append({"_estimate": 999., "_converged": True, "_p": .99, "_role": "author_reference"})
    ranked = mv.rank_reported(rows, .4)
    for field in ("n_converged", "median", "min", "max", "share_significant", "extremeness"):
        assert ranked[field] == baseline[field]
    assert grid["n_specs"] == 1
    assert len(mv.enumerate_specs(grid)) == 2


@pytest.mark.parametrize("kind", ["merge_levels", "pin_level", "rewrite_how", "add_level"])
def test_structured_screen_amendments_change_the_executable_grid(kind):
    verdict = screen()
    change = {"kind": kind, "factor": "method", "levels": ["a", "b"],
              "canonical": "a", "how": "corrected computation", "rationale": "fixture evidence"}
    if kind == "add_level":
        change["canonical"] = "c"
        verdict["factors"][0]["levels"].append({"value": "c", "verdict": "defensible"})
    verdict["adjustments"] = [change]
    grid = mv.build_grid(proposal(), verdict)
    assert not grid["blocking_issues"]
    levels = grid["factors"][0]["levels"]
    if kind in {"merge_levels", "pin_level"}:
        assert [lv["value"] for lv in levels] == ["a"]
    elif kind == "rewrite_how":
        assert levels[0]["how"] == "corrected computation"
    else:
        assert levels[-1]["value"] == "c"


def test_unresolved_mandatory_amendment_and_missing_verdict_block():
    for verdict in [{"factors": []}, {**screen(), "adjustments": ["fix this somehow"]}]:
        grid = mv.build_grid(proposal(), verdict)
        assert grid["blocking_issues"]
        assert grid["n_specs"] == 0


def test_audit_unknown_is_distinct_from_execution_success():
    assert audit.acceptance({}) == "unresolved"
    assert audit.acceptance({"verdict": "suspicious"}) == "unresolved"
    assert audit.acceptance({"verdict": "hardcoded", "adjudication": {
        "decision": "accepted", "reason": "only a design constant was flagged"}}) == "accepted"
    assert audit.acceptance({"verdict": "hardcoded", "adjudication": {"decision": "accepted"}}) == "unresolved"


@pytest.mark.parametrize("model", ["mixed ANOVA with within-subject factors", "two-way ANOVA",
                                    "repeated measures interaction", "between-subject ANOVA"])
def test_complex_designs_do_not_become_simple_t_test_power(model):
    assert mde.classify_design(model) is None


def test_group_counts_are_not_guessed_or_inconsistent():
    with pytest.raises(ValidationError):
        AnalysisDesign(family="independent_t", contrast="x", independent_unit="person",
                       n_total=15, group_ns=[7, 7], evidence="test")


def test_focal_sample_uses_verified_analysis_and_rejects_disagreement():
    def replica(n, status="verified", verdict="clean"):
        return SimpleNamespace(results={"results": [{"claim_id": "effect", "n": 999}]},
            trace={"ran": True, "hardcoding_audit": {"verdict": verdict},
                   "execution_evidence": {"analyses": {"a1": {"status": status, "n": n}}}})
    inp = SimpleNamespace(focal={"analysis_id": "a1", "focal_quantity": {"claim_id": "effect"}},
                          focal_contract=None, replicas=[replica(29), replica(999, "unverified")])
    assert review._focal_n(inp)[0] == 29
    inp.replicas.append(replica(30))
    assert review._focal_n(inp)[0] is None
    inp.replicas = [replica(29, "unverified")]
    assert review._focal_n(inp)[0] is None


def valid_row():
    return {"_converged": True, "estimate": ".8", "effect_metric": "dz", "se": ".2",
            "se_metric": "dz", "p": ".03", "p_raw": ".01", "p_adjustment": "bonferroni",
            "p_family": "[0.01, 0.2, 0.3]", "p_index": "0", "p_threshold": ".05",
            "inference_method": "analytic", "n": "28"}


@pytest.mark.parametrize("field,value", [("p_threshold", ".016666667"), ("se_metric", "raw"),
                                        ("estimate", "inf"), ("p", "1.1"), ("n", "2.5")])
def test_result_contract_rejects_wrong_units_double_correction_and_invalid_numbers(field, value):
    row = valid_row()
    assert validate_result(row, strict=True) == []
    row[field] = value
    assert validate_result(row, strict=True)


def test_monte_carlo_zero_rejected_and_holm_enforced():
    assert monte_carlo_p(0, 9999) == .0001
    assert adjusted_p([.01, .03, .02], "holm") == pytest.approx([.03, .04, .04])
    row = valid_row()
    row.update(inference_method="monte_carlo", p="0", p_raw="0", p_adjustment="none",
               p_family="", draws="9999", exceedances="0")
    assert any("finite-simulation" in p for p in validate_result(row, strict=True))


def test_focal_binding_requires_unique_analysis_and_valid_override():
    man = paths.Manifest(paper_id="fixture", focal_claim={"text": "effect", "reported": {"value": 4.2}})
    claims = [artifacts.ClaimRecord(claim_id=cid, quantity_kind="t", value=4.2) for cid in ("a", "b")]
    contracts = [artifacts.EstimandContract(analysis_id=cid, claim_ids=[cid]) for cid in ("a", "b")]
    with pytest.raises(ValueError, match="ambiguous"):
        focal.bind_focal_claim(man, claims, contracts, allow_llm=False)
    man.focal_claim.claim_id = "absent"
    with pytest.raises(ValueError, match="does not exist"):
        focal.bind_focal_claim(man, claims, contracts, allow_llm=False)


def one_grid():
    return {"factors": [{"name": "method", "levels": [{"value": "a"}]}], "grid_size": 1, "n_specs": 1}


def test_noop_executor_cannot_reuse_existing_output(tmp_path, monkeypatch):
    out = tmp_path / "out"; out.mkdir()
    (out / "specs.csv").write_text("spec_id,estimate,se,p,n,converged,error\nspec_001,.8,.1,.01,28,TRUE,\n")
    (out / "multiverse.py").write_text("pass\n")
    monkeypatch.setattr(mv, "hardcoding_audit", lambda *a: {"verdict": "clean"})
    report = mv.verify_execution(tmp_path, one_grid(), "fixture")
    assert not report["ok"]
    assert not report["checks"]["regenerated_results"]


@pytest.mark.parametrize("field,value", [("se", "999"), ("p", ".04"), ("n", "29"),
                                        ("converged", "FALSE"), ("p_threshold", ".01")])
def test_rerun_compares_every_statistical_field(field, value):
    a = {"estimate": ".8", "se": ".1", "p": ".01", "n": "28", "converged": "TRUE", "p_threshold": ".05"}
    b = {**a, field: value}
    assert not mv.same_result(a, b)


def test_stage1_comparison_checks_uncertainty_and_sample():
    a = {"results": [{"claim_id": "c", "value": 1., "se": .1, "n": 28}]}
    b = copy.deepcopy(a); b["results"][0]["n"] = 29
    assert not execution.equal(execution.result_fields(a), execution.result_fields(b))


def test_fresh_copy_excludes_cached_tables(tmp_path):
    work = tmp_path / "work"; (work / "out").mkdir(parents=True)
    (work / "out/results.json").write_text("{}")
    (work / "out/cache.csv").write_text("1")
    (work / "out/analysis.py").write_text("pass")
    execution.copy_inputs(work, tmp_path / "fresh")
    assert sorted(p.name for p in (tmp_path / "fresh/out").iterdir()) == ["analysis.py"]


def test_reference_calculations_respond_to_relevant_data_only():
    x, y = [3., 5., 8., 9., 10.], [1., 2., 4., 7., 8.]
    result = reference.calculate("paired_t", x, y)
    differences = [a-b for a, b in zip(x, y)]
    mean = sum(differences)/len(differences)
    sd = math.sqrt(sum((d-mean)**2 for d in differences)/(len(differences)-1))
    assert result["dz"] == pytest.approx(mean/sd)
    assert result["t"] == pytest.approx(mean/sd*math.sqrt(len(x)))
    assert reference.calculate("paired_t", [30., *x[1:]], y)["dz"] != result["dz"]


def test_all_tied_curve_and_unsigned_statistics_have_honest_summaries():
    rows = [{"_estimate": .89, "_converged": True, "_p": .001}] * 9
    tied = mv.rank_reported(rows, .89, precision=2)
    assert tied["curve_state"] == "all_tied" and tied["extremeness"] is None
    assert tied["rank_interval"] == [1, 9]
    assert mv.rank_reported(rows, .9, precision=2)["extremeness"] == 0
    assert mv.rank_reported(rows, .89, quantity_kind="F")["share_same_sign"] is None


def test_step_cache_follows_immediate_artifact(tmp_path):
    cache = tmp_path / "screen.json"
    cache.write_text(json.dumps(stage3._stamp({}, {"proposed": "one"}, ("proposed",))))
    assert not stage3._step_stale(cache, False, {"proposed": "one"}, ("proposed",))
    assert stage3._step_stale(cache, False, {"proposed": "two"}, ("proposed",))


def test_done_marker_checks_output_integrity(tmp_path):
    output = tmp_path / "result.json"; output.write_text('{"value":1}')
    paths.mark_done(tmp_path, {"input": "same"})
    assert paths.is_done(tmp_path, {"input": "same"})
    output.write_text('{"value":2}')
    assert not paths.is_done(tmp_path, {"input": "same"})


@pytest.mark.parametrize("dependency", ["data", "prompt", "script", "model", "environment"])
def test_executor_cache_tracks_inputs_with_unchanged_grid(tmp_path, dependency):
    (tmp_path / "work/out").mkdir(parents=True)
    (tmp_path / "work/out/specs.csv").write_text("spec_id,estimate\n")
    (tmp_path / "execute.json").write_text(json.dumps({"grid_sha": "same", "_inputs": {dependency: "old"},
        "output_fingerprint": mv.executor_outputs(tmp_path / "work")}))
    assert not stage3.executor_stale(tmp_path, "same", force=False, dependencies={dependency: "old"})
    assert stage3.executor_stale(tmp_path, "same", force=False, dependencies={dependency: "new"})


def test_intake_rejects_wrong_file_column_type_and_sample():
    contract = artifacts.EstimandContract(analysis_id="a")
    schema = {"files": [{"path": "data/file.csv", "tables": [{"table": None, "rows": 8,
        "columns": [{"name": "score", "dtype": "float64", "min": 1, "max": 7}]}]}]}
    binding = {"analysis_id": "a", "file": "data/file.csv", "table": None,
               "chosen": "score", "expected_type": "numeric", "allowed_range": [1, 7]}
    assert validate_bindings([contract], [binding], schema) == {"a": []}
    for bad in [{**binding, "file": "other"}, {**binding, "chosen": "missing"},
                {**binding, "allowed_range": [1, 5]}]:
        assert validate_bindings([contract], [bad], schema)["a"]
    contract.design = AnalysisDesign(family="paired_t", contrast="change", independent_unit="person",
                                     n_total=10, evidence="fixture")
    assert validate_bindings([contract], [binding], schema)["a"]


def test_annotation_metrics_distinguish_false_positives_and_omissions():
    result = score_sets({"reversed_item", "derived_scale"}, {"reversed_item", "wrong_study"})
    assert result["precision"] == result["recall"] == .5
    assert result["missing"] == ["derived_scale"]
    assert result["unexpected"] == ["wrong_study"]


def test_cohort_rejects_duplicate_papers_and_ignores_archive_directories(tmp_path):
    entry = {"paper_id": "paper", "run_id": "paper_v2", "replicas": ["one"], "split": "development"}
    p = tmp_path / "cohort.json"; p.write_text(json.dumps({"papers": [entry]}))
    before = cohort.load(p)
    (tmp_path / "paper_old").mkdir()
    assert cohort.load(p) == before
    p.write_text(json.dumps({"papers": [entry, {**entry, "run_id": "paper_old"}]}))
    with pytest.raises(ValueError, match="duplicate paper_id"):
        cohort.load(p)


def test_unknown_incompatibility_blocks_instead_of_disappearing():
    verdict = screen()
    verdict['incompatible'] = [{'a': 'method=a', 'b': 'typo=b'}]
    grid = mv.build_grid(proposal(), verdict)
    assert grid['n_specs'] == 0
    assert 'unknown factor' in grid['blocking_issues'][0]


def test_equivalent_author_level_maps_to_one_canonical_branch():
    verdict = screen()
    verdict['adjustments'] = [{'kind': 'merge_levels', 'factor': 'method', 'levels': ['a', 'b'],
                              'canonical': 'a', 'rationale': 'algebraically identical'}]
    grid = mv.build_grid(proposal(), verdict, paper_levels={'method': 'b'})
    assert grid['n_specs'] == 1
    assert grid['factors'][0]['paper_level'] == 'a'
    assert not grid['reference_specs']


def test_pinned_out_author_choice_is_reference_only(tmp_path):
    verdict = screen()
    verdict['adjustments'] = [{'kind': 'pin_level', 'factor': 'method', 'canonical': 'a',
                              'rationale': 'b is redundant for the sensitivity question'}]
    grid = mv.build_grid(proposal(), verdict, paper_levels={'method': 'b'})
    assert grid['n_specs'] == 1
    assert grid['reference_specs'][0]['levels'] == {'method': 'b'}
    p = tmp_path / 'specs.csv'
    p.write_text('spec_id,estimate\nspec_001,1\nreference_author,999\n')
    assert '999' not in mv.defensible_csv(p, grid)


def test_pin_does_not_erase_explicit_screen_rejection():
    verdict = screen()
    verdict['factors'][0]['levels'][1].update(verdict='rejected', rationale='invalid null construction')
    verdict['adjustments'] = [{'kind': 'pin_level', 'factor': 'method', 'canonical': 'a',
                              'rationale': 'retain the valid method'}]
    grid = mv.build_grid(proposal(), verdict)
    assert grid['rejected_levels'] == [{'factor': 'method', 'level': 'b',
                                       'rationale': 'invalid null construction'}]


def test_reference_cannot_verify_an_empty_or_duplicate_output(tmp_path):
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out/analysis_plan.json').write_text(json.dumps({'specs': [
        {'spec_id': 'spec_001', 'status': 'unsupported', 'reason': 'no adapter', 'implemented_levels': {}}]}))
    assert reference.check(tmp_path, [], [{'spec_id': 'spec_001', 'levels': {}}])['status'] == 'invalid'


@pytest.mark.parametrize('mode', ['correct', 'partial', 'hardcoded', 'wrong_factor', 'dishonest_plan'])
def test_fresh_reference_and_perturbation_end_to_end(tmp_path, monkeypatch, mode):
    """The generated code and checker do not share a numerical implementation."""
    import subprocess
    work = tmp_path / 'work'; out = work / 'out'; out.mkdir(parents=True)
    (work / 'data').mkdir()
    (work / 'data/study.csv').write_text('group,x\na,1\na,2\na,4\na,7\nb,8\nb,15\nb,3\nb,6\nb,19\n')
    grid = {'factors': [{'name': 'variance', 'levels': [{'value': 'pooled', 'reference_settings': {'equal_var': True}}, {'value': 'welch', 'reference_settings': {'equal_var': False}}]}],
            'grid_size': 2, 'n_specs': 2, 'effect_metric': 't', 'result_contract_version': 1}
    specs = mv.enumerate_specs(grid)
    (work / 'GRID.json').write_text(json.dumps({'specs': specs}))
    code = '''import csv, json, math
from pathlib import Path
from scipy.stats import t as student
rows=list(csv.DictReader(open('data/study.csv')))
x=[float(r['x']) for r in rows if r['group']=='a']
y=[float(r['x']) for r in rows if r['group']=='b']
MODE=__MODE__
if MODE=='hardcoded': x,y=[1,2,4,7],[8,15,3,6,19]
def variance(z):
    m=sum(z)/len(z)
    return sum((a-m)**2 for a in z)/(len(z)-1)
result=[]; plans=[]
for spec in json.load(open('GRID.json'))['specs']:
    pooled=spec['levels']['variance']=='pooled'
    vx,vy=variance(x),variance(y); nx,ny=len(x),len(y)
    if pooled or MODE in {'wrong_factor','dishonest_plan'}:
        v=((nx-1)*vx+(ny-1)*vy)/(nx+ny-2)
        se=math.sqrt(v*(1/nx+1/ny)); df=nx+ny-2
    else:
        se=math.sqrt(vx/nx+vy/ny)
        df=(vx/nx+vy/ny)**2/((vx/nx)**2/(nx-1)+(vy/ny)**2/(ny-1))
    t=(sum(x)/nx-sum(y)/ny)/se; p=2*student.sf(abs(t),df)
    result.append(dict(spec_id=spec['spec_id'], estimate=t, effect_metric='t', se='', se_metric='',
        p=p,p_raw=p,p_adjustment='none',p_family='',p_index=0,p_threshold=.05,
        inference_method='analytic',n=nx+ny,converged='TRUE',error=''))
    plans.append(dict(spec_id=spec['spec_id'],implemented_levels=spec['levels'],status='supported',
        family='independent_t',file='data/study.csv',x='x',group_column='group',group_values=['a','b'],equal_var=True if MODE=='dishonest_plan' else pooled))
    if MODE=='partial' and pooled: plans[-1].update(status='unsupported',reason='declared adapter limitation')
with open('out/specs.csv','w') as f:
    writer=csv.DictWriter(f,fieldnames=list(result[0])); writer.writeheader(); writer.writerows(result)
Path('out/analysis_plan.json').write_text(json.dumps({'specs':plans}))
'''.replace('__MODE__', repr(mode))
    script = out / 'multiverse.py'; script.write_text(code)
    subprocess.run([sys.executable, str(script)], cwd=work, check=True)
    original = (out / 'specs.csv').read_bytes()
    monkeypatch.setattr(replicas, 'prepare_env', lambda *a: {'interpreter': sys.executable, 'env': {}, 'error': None})
    monkeypatch.setattr(mv, 'hardcoding_audit', lambda *a: {'verdict': 'clean'})
    report = mv.verify_execution(work, grid, 'fixture')
    assert report['checks']['rerun_reproduces']
    assert (out / 'specs.csv').read_bytes() == original
    if mode in {'correct', 'partial'}:
        assert report['ok'] == (mode == 'correct'), report['problems']
        assert report['reference']['status'] == report['perturbation']['status'] == ('partial' if mode == 'partial' else 'verified')
        assert report['perturbation']['checked'] == (1 if mode == 'partial' else 2)
        assert report['perturbation']['total'] == 2
        assert report['acceptance'] == ('accepted' if mode == 'correct' else 'rejected')
    else:
        assert not report['ok']
        if mode == 'hardcoded':
            assert report['perturbation']['status'] == 'failed'
        else:
            assert any('independent reference differs' in p or 'violates screened' in p for p in report['problems'])


def test_editing_executor_rechecks_without_regenerating(tmp_path):
    out = tmp_path / 'work/out'; out.mkdir(parents=True)
    (out / 'specs.csv').write_text('original')
    script = out / 'multiverse.py'; script.write_text('original')
    deps = {'grid': 'same', 'prompt': 'same'}
    (tmp_path / 'execute.json').write_text(json.dumps({'grid_sha': 'same', '_inputs': deps,
        'output_fingerprint': mv.executor_outputs(out.parent)}))
    script.write_text('corrected')
    assert stage3.executor_stale(tmp_path, 'same', force=False, dependencies=deps)
    assert not stage3.executor_stale(tmp_path, 'same', force=False, dependencies=deps, check_outputs=False)


def test_intake_requires_every_contract_field():
    contract = artifacts.EstimandContract(analysis_id='a', outcome='score', predictors=['group'])
    schema = {'files': [{'path': 'data/a.csv', 'tables': [{'table': None, 'columns': [{'name': 'score'}]}]}]}
    binding = {'analysis_id': 'a', 'contract_field': 'outcome', 'file': 'a.csv', 'table': '', 'chosen': 'score'}
    problems = validate_bindings([contract], [binding], schema)['a']
    assert problems == ['unbound contract fields: predictors[0]']


def test_fresh_execution_rejects_external_cached_paths_but_allows_out_parent_data(tmp_path):
    (tmp_path / 'out').mkdir()
    script = tmp_path / 'out/analysis.py'
    script.write_text("open('../data/study.csv')")
    assert not execution.external_file_literals(tmp_path)
    for path in ['/tmp/old/specs.csv', '../../other/results.json']:
        script.write_text(f'open({path!r})')
        assert execution.external_file_literals(tmp_path)


def test_packet_audit_is_required_and_exact(tmp_path, monkeypatch):
    from reproscope.stage1 import blind
    s0 = tmp_path / 'runs/fixture/stage0'; s0.mkdir(parents=True)
    monkeypatch.setattr(paths, 'ROOT', tmp_path)
    monkeypatch.setattr(blind, 'packet_fingerprint', lambda _: {'METHODS.md': 'new'})
    with pytest.raises(blind.LeakDetected, match='no versioned'):
        blind.validate_packet_audit('fixture')
    receipt = s0 / 'leak_audit.json'
    receipt.write_text(json.dumps({'packet_fingerprint': {'METHODS.md': 'old'}, 'blinding_status': 'no_leak_detected'}))
    with pytest.raises(blind.LeakDetected, match='differs'):
        blind.validate_packet_audit('fixture')
    receipt.write_text(json.dumps({'packet_fingerprint': {'METHODS.md': 'new'}, 'blinding_status': 'no_leak_detected'}))
    blind.validate_packet_audit('fixture')


def test_pdf_replacement_and_text_edits_invalidate_extraction_cache(tmp_path, monkeypatch):
    from reproscope.stage0 import extract
    paper = tmp_path / 'corpus/fixture'; paper.mkdir(parents=True)
    monkeypatch.setattr(paths, 'ROOT', tmp_path)
    (paper / 'paper.pdf').write_text('first PDF')
    manifest = paths.Manifest(paper_id='fixture')
    calls = []
    def fake_run(command, **kwargs):
        calls.append(command)
        Path(command[-1]).write_text((paper / 'paper.pdf').read_text())
    monkeypatch.setattr(extract.subprocess, 'run', fake_run)
    output = extract.extract_text(manifest)
    assert output.read_text() == 'first PDF'
    extract.extract_text(manifest)
    assert len(calls) == 1
    (paper / 'paper.pdf').write_text('replacement PDF')
    assert extract.extract_text(manifest).read_text() == 'replacement PDF'
    output.write_text('unverified edit')
    assert extract.extract_text(manifest).read_text() == 'replacement PDF'
    assert len(calls) == 3


def test_vision_extraction_tracks_page_bytes_not_just_prompt(tmp_path, monkeypatch):
    from reproscope.stage0 import extract
    paper = tmp_path / 'corpus/fixture'; paper.mkdir(parents=True)
    monkeypatch.setattr(paths, 'ROOT', tmp_path)
    (paper / 'paper.pdf').write_text('PDF')
    page = paper / 'p001.png'; page.write_bytes(b'first image')
    monkeypatch.setattr(extract.artifacts, 'prompt_version', lambda _: 'same prompt')
    monkeypatch.setattr(extract.config, 'tier', lambda _: SimpleNamespace(model_dump=lambda **kw: {'model': 'fixed'}))
    calls = []
    def chunk(*args):
        calls.append(1)
        return 0, extract.ClaimList(claims=[]), 'fixture'
    monkeypatch.setattr(extract, '_chunk_call', chunk)
    monkeypatch.setattr(extract, 'page_texts', lambda *a: [])
    manifest = paths.Manifest(paper_id='fixture')
    target = tmp_path / 'extract.json'
    extract.extract_one(manifest, 'fixture', [page], target)
    extract.extract_one(manifest, 'fixture', [page], target)
    assert len(calls) == 1
    page.write_bytes(b'replacement image')
    extract.extract_one(manifest, 'fixture', [page], target)
    assert len(calls) == 2


def test_model_config_cache_follows_content_at_the_same_path(tmp_path):
    from reproscope import config
    p = tmp_path / 'models.toml'
    p.write_text('[tiers.cheap]\nroute="test"\nmodel="first"\n')
    assert config.config(p).tiers['cheap'].model == 'first'
    p.write_text(p.read_text().replace('first', 'second'))
    assert config.config(p).tiers['cheap'].model == 'second'


def test_unrelated_verifier_revision_does_not_regenerate_enumeration(tmp_path):
    target = tmp_path / 'factors_proposed.json'
    inputs = {'implementation': 'old verifier', 'contracts': 'same', 'schema': 'same'}
    target.write_text(json.dumps(stage3._stamp({}, inputs, ('contracts', 'schema'), ('stage3_enumerate',))))
    inputs['implementation'] = 'new verifier'
    assert not stage3._step_stale(target, False, inputs, ('contracts', 'schema'), ('stage3_enumerate',))


def test_reference_dois_do_not_trigger_empty_claim_failure(monkeypatch):
    from reproscope.stage0 import extract
    references = '\n'.join(f'Author (2020). Title. https://doi.org/10.1016/j.cognition.{i:04d}' for i in range(30))
    monkeypatch.setattr(extract, 'page_paths', lambda _: ['page'])
    monkeypatch.setattr(extract, 'page_texts', lambda *a: ['', references])
    assert not extract._prints_results(None, 0, 1)
    results = references + '\n' + ' '.join(f'mean = {i}.25' for i in range(25))
    monkeypatch.setattr(extract, 'page_texts', lambda *a: ['', results])
    assert extract._prints_results(None, 0, 1)


def test_successful_extraction_chunks_survive_another_chunk_failure(tmp_path, monkeypatch):
    from reproscope.stage0 import extract
    monkeypatch.setattr(extract, "CHUNK_PAGES", 8)
    paper = tmp_path / 'corpus/fixture'; paper.mkdir(parents=True)
    monkeypatch.setattr(paths, 'ROOT', tmp_path)
    (paper / 'paper.pdf').write_text('PDF')
    pages = []
    for i in range(9):
        p = paper / f'p{i+1:03d}.png'; p.write_bytes(b'image'); pages.append(p)
    monkeypatch.setattr(extract.artifacts, 'prompt_version', lambda _: 'fixed')
    monkeypatch.setattr(extract.config, 'tier', lambda _: SimpleNamespace(model_dump=lambda **kw: {'model': 'fixed'}))
    monkeypatch.setattr(extract, 'page_texts', lambda *a: [])
    calls = {0: 0, 8: 0}
    def chunk(manifest, tier, pages, start):
        calls[start] += 1
        if start == 8 and calls[start] == 1:
            raise RuntimeError('temporary failure')
        return start, extract.ClaimList(claims=[]), f'call-{start}'
    monkeypatch.setattr(extract, '_chunk_call', chunk)
    target = tmp_path / 'extract.json'
    manifest = paths.Manifest(paper_id='fixture')
    with pytest.raises(RuntimeError, match='temporary failure'):
        extract.extract_one(manifest, 'fixture', pages, target)
    extract.extract_one(manifest, 'fixture', pages, target)
    assert calls == {0: 1, 8: 2}


def test_empty_extraction_notes_are_metadata_not_a_reason_to_repeat_vision():
    from reproscope.stage0.extract import ClaimList
    assert ClaimList.model_validate({'claims': [], 'notes': []}).notes is None
    with pytest.raises(ValidationError):
        ClaimList.model_validate({'claims': [], 'notes': {'invalid': 'structure'}})


def test_nested_design_evidence_is_scrubbed_without_mutating_source_contract():
    from reproscope.stage0 import redact
    contract = artifacts.EstimandContract(analysis_id='a1', predictors=['Outcome-linked predictor'],
        design=AnalysisDesign(family='paired_t', contrast='cue vs no cue', independent_unit='participant',
                              evidence='Paired tests revealed an increase.'),
        identity={'study': 's1', 'outcome': 'speed'})
    items = {i['id']: i['text'] for i in redact.scrub_items([], [contract])}
    assert items['contract:a1:design:evidence'] == 'Paired tests revealed an increase.'
    assert items['contract:a1:predictors:0'] == 'Outcome-linked predictor'
    blind = redact.blind_contracts([contract], {
        'contract:a1:design:evidence': 'Paired tests compared cue conditions.',
        'contract:a1:predictors:0': 'Predictor'})[0]
    assert blind['design']['evidence'] == 'Paired tests compared cue conditions.'
    assert blind['predictors'] == ['Predictor'] and 'identity' not in blind
    assert contract.design.evidence == 'Paired tests revealed an increase.'


def test_packet_audit_requires_included_analyses_and_allows_known_abstentions():
    from reproscope.stage0.redact import audit_covers_packet
    packet = {'analyses': [{'analysis_id': 'a1'}, {'analysis_id': 'a2'}],
              'analyses_without_data': ['a3']}
    assert audit_covers_packet(packet, ['a1', 'a2'])
    assert audit_covers_packet(packet, ['a1', 'a2', 'a3'])
    for ids in (None, ['a1'], ['a1', 'a2', 'a4'], ['a1', 'a2', 'a2'], [1, 2]):
        assert not audit_covers_packet(packet, ids)


def test_shared_claim_rows_use_analysis_claim_identity():
    packet = {'analyses': [
        {'analysis_id': aid, 'quantities': [{'claim_id': 'n'}]} for aid in ('a1', 'a2')]}
    rows = [{'analysis_id': aid, 'claim_id': 'n', 'value': 28, 'n': 28} for aid in ('a1', 'a2')]
    assert len(execution.result_fields({'results': rows}, packet)) == 2
    with pytest.raises(ValueError, match='unique analysis/claim'):
        execution.result_fields({'results': [rows[0], rows[0]]}, packet)
    for row in [dict(rows[0], analysis_id='a3'), dict(rows[0], analysis_id=None),
                dict(rows[0], claim_id='unknown')]:
        with pytest.raises(ValueError, match='not requested'):
            execution.result_fields({'results': [row]}, packet)
    modified = copy.deepcopy(rows)
    modified[1]['n'] = 27
    assert not execution.equal(execution.result_fields({'results': rows}, packet),
                               execution.result_fields({'results': modified}, packet))


def test_linking_shared_claims_requires_agreement_and_preserves_available_uncertainty():
    from reproscope.stage1.match import direct_link
    rows = [{'analysis_id': 'a1', 'claim_id': 'c', 'value': '.5', 'se': None, 'n': '28'},
            {'analysis_id': 'a2', 'claim_id': 'c', 'value': .5, 'se': .1, 'n': 28}]
    linked = direct_link('c', json.dumps({'results': rows}))
    assert linked.found and linked.value == .5 and linked.se == .1 and linked.n == 28
    assert linked.source_analysis_ids == ['a1', 'a2']
    for field, value in [('value', .7), ('n', 29), ('value', 'nan')]:
        changed = copy.deepcopy(rows)
        changed[1][field] = value
        linked = direct_link('c', json.dumps({'results': changed}))
        assert linked.error and not linked.found
        assert linked.error_kind == ('invalid' if value == 'nan' else 'ambiguous')


def test_provider_cooldown_is_model_scoped_expires_and_ignores_schema_errors(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from reproscope import llm, ledger
    now = datetime.now(timezone.utc)
    def row(provider, seconds, **changes):
        return {'provider': provider, 'model': 'model', 'route': 'openrouter',
                'finish_reason': 'error', 'ts': (now - timedelta(seconds=seconds)).isoformat(), **changes}
    monkeypatch.setattr(ledger, 'rows', lambda pid: [row('bad', 30), row('expired', 901),
        row('other-model', 30, model='other'), row('validation-only', 30, finish_reason='stop')])
    assert llm.recent_failed_providers('paper', 'model', now=now) == ['bad']


def test_completed_failure_without_results_does_not_relaunch_on_resume(tmp_path, monkeypatch):
    rdir = tmp_path / 'r1'
    (rdir / 'work/out').mkdir(parents=True)
    trace = artifacts.ReplicaDecisionTrace(replica_id='r1', family='family', model='model',
        route='codex', ran=False, state='abstained', abstain_reason='agent timed out',
        output_fingerprint={}, meta=artifacts.ArtifactMeta(artifact='ReplicaDecisionTrace', inputs={'generation': 'fixed'}))
    artifacts.save(trace, rdir / 'trace.json')
    monkeypatch.setattr(replicas.blind, 'replica_dir', lambda *args: rdir)
    monkeypatch.setattr(replicas.blind, 'validate_packet_audit', lambda *args: None)
    monkeypatch.setattr(replicas, 'generation_inputs', lambda *args: {'generation': 'fixed'})
    monkeypatch.setattr(replicas.replica_env, 'ensure_base_env', lambda: pytest.fail('generation preparation must not run'))
    resumed = replicas.run_one('paper', 'family', 'r1', SimpleNamespace())
    assert not resumed.ran and resumed.abstain_reason == 'agent timed out'


def test_timeout_preserves_completed_opencode_usage_and_marks_incomplete(monkeypatch):
    import subprocess
    from reproscope import llm, ledger
    rows = []
    event = json.dumps({'type': 'step_finish', 'part': {'tokens': {
        'input': 10, 'output': 5, 'reasoning': 2, 'cache': {'read': 20}}, 'cost': .12}})
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(['opencode'], 1, output=event.encode())
    monkeypatch.setattr(llm, '_opencode', timeout)
    monkeypatch.setattr(ledger, 'record', lambda pid, row: rows.append(row) or 'call')
    result = llm.call('replica', 'task', paper_id='paper', stage='1', route='opencode', model='model', timeout_s=1)
    assert not result.ok and result.tokens_in == 30 and result.cost_usd == .12
    assert rows[0]['usage_incomplete'] is True


def test_vector_p_values_require_explicit_aggregation_and_complete_membership():
    from reproscope.stage1.match import direct_link
    ids = ["no_cue", "40db", "85db"]
    text = json.dumps({'results': [{'claim_id': 'c', 'analysis_id': 'a', 'value': [.01, .4, .2], 'member_ids': ids}]})
    lower = direct_link('c', text, quantity_kind='p_value', comparator='>=', aggregation='all', member_ids=ids)
    upper = direct_link('c', text, quantity_kind='p_value', comparator='<', aggregation='all', member_ids=ids)
    assert lower.value == .01 and upper.value == .4
    assert direct_link('c', text, quantity_kind='p_value').error_kind == 'ambiguous'
    assert direct_link('c', text, quantity_kind='p_value', comparator='>', aggregation='all', member_ids=['no_cue']).error_kind == 'invalid'
    bad = text.replace('0.4', '1.4')
    assert direct_link('c', bad, quantity_kind='p_value', comparator='>', aggregation='all', member_ids=ids).error_kind == 'invalid'


def test_reference_constraints_ignore_null_but_preserve_concrete_conflicts():
    from reproscope.stage3 import multiverse as mv
    grid = {'factors': [
        {'name': 'tail', 'levels': [{'value': 'two', 'reference_settings': {'alternative': 'two-sided', 'equal_var': False}}]},
        {'name': 'sample', 'levels': [{'value': 'all', 'reference_settings': {'alternative': None, 'equal_var': None}}]},
    ]}
    settings = mv.reference_specifications(grid)[0]['reference_settings']
    assert settings == {'alternative': 'two-sided', 'equal_var': False}
    grid['factors'][1]['levels'][0]['reference_settings']['alternative'] = 'greater'
    with pytest.raises(ValueError, match='conflicting screened reference settings'):
        mv.reference_specifications(grid)


def test_executor_generation_survives_verifier_exception(tmp_path, monkeypatch):
    from reproscope import stage3
    work = tmp_path / 'work'
    (work / 'out').mkdir(parents=True)
    (work / 'out/specs.csv').write_text('spec_id,estimate\nspec_001,1\n')
    generated = {'grid_sha': 'grid', '_inputs': {'data': 'original'}, '_ledger_id': 'completed-call'}
    def broken(*args):
        raise ValueError('checker defect')
    monkeypatch.setattr(stage3.mv, 'verify_execution', broken)
    with pytest.raises(ValueError, match='checker defect'):
        stage3._verify_generated_execution(tmp_path / 'execute.json', work, {}, 'paper', generated, {'code': 'new'})
    saved = json.loads((tmp_path / 'execute.json').read_text())
    assert saved['_ledger_id'] == 'completed-call'
    assert 'verification_inputs' not in saved
    assert not stage3.executor_stale(tmp_path, 'grid', force=False, dependencies={'data': 'original'}, check_outputs=False)


def test_open_source_identity_blocks_binding_without_blocking_method_choices():
    from reproscope import artifacts
    from reproscope.intake_validation import gate_source_identity
    contracts = [artifacts.EstimandContract(analysis_id=aid, ambiguities=[
        artifacts.ContractAmbiguity(field=field, kind=kind, options=['A','B'], note='source evidence')])
        for aid,field,kind in [('a1','figure_marker',None), ('a2','alternative',None),
                               ('a3','new_field',None), ('a4','new_method','method')]]
    r = artifacts.DataReadinessRecord(per_analysis_state={c.analysis_id:'complete' for c in contracts},
                                      per_analysis_outcome={c.analysis_id:'bound' for c in contracts})
    gate_source_identity(r, contracts)
    assert r.per_analysis_state == {'a1':'abstained','a2':'complete','a3':'abstained','a4':'complete'}
    assert r.per_analysis_outcome['a1'] == 'source_unresolved'
    assert r.source_identity_problems['a1'][0]['options'] == ['A','B']
    assert r.source_identity_problems['a3'][0]['classification'] == 'unclassified_field'


def test_pair_diagnostics_follow_declared_missing_parser(tmp_path):
    from types import SimpleNamespace
    from reproscope import data_checks
    path = tmp_path / 'd.csv'
    path.write_text('id,x,y\n1,1,2\n2, , \n3,4,5\n')
    manifest = SimpleNamespace(data_files=['d.csv'], path=lambda rel: tmp_path / rel)
    check = dict(analysis_id='a1',file='d.csv',kind='paired_complete',columns=['x','y'],assumption_evidence='paired design')
    assert data_checks.run(manifest,[check])[0]['status'] == 'unverified'
    binding = dict(analysis_id='a1',file='d.csv',input_columns=['x','y'],numeric_parsing='strict_float_blank_missing')
    result = data_checks.run(manifest,[check],bindings=[binding])[0]
    assert (result['status'],result['n_complete'],result['n_all_missing']) == ('passed',2,1)
    path.write_text('id,x,y\n1,1,2\n2, ,3\n3,4,5\n')
    assert data_checks.run(manifest,[check],bindings=[binding])[0]['affected_row_positions'] == [1]
    path.write_text('id,x,y\n1,1,2\n2,broken,3\n3,4,5\n')
    assert data_checks.run(manifest,[check],bindings=[binding])[0]['status'] == 'unverified'


def test_correlation_missingness_is_profiled_per_member_not_a_pairing_violation(tmp_path):
    from types import SimpleNamespace
    from reproscope import data_checks
    (tmp_path/'d.csv').write_text('x,y,z\n1,2,3\n4, ,5\n6,7, \n')
    manifest = SimpleNamespace(data_files=['d.csv'],path=lambda rel: tmp_path/rel)
    request = dict(analysis_id='a1',file='d.csv',kind='paired_complete',columns=['x','y','z'],assumption_evidence='correlations use complete cases')
    family = {'a1':{'members':[dict(member_id='m'+y,file='d.csv',x='x',y=y,numeric_parsing='strict_float_blank_missing',sample_rule='complete cases') for y in ['y','z']]}}
    result = data_checks.run(manifest,[request],families=family)[0]
    assert result['status'] == 'profiled'
    assert [m['n_complete'] for m in result['members']] == [2,2]
    assert [m['incomplete_row_positions'] for m in result['members']] == [[1],[2]]


def test_integrity_checks_use_analysis_sample_and_preserve_source_positions(tmp_path):
    from types import SimpleNamespace
    from reproscope import data_checks
    (tmp_path/'d.csv').write_text('id,x,y\n1,1,\n2,2,3\n3,4,\n4,5,6\n')
    manifest=SimpleNamespace(data_files=['d.csv'],path=lambda rel:tmp_path/rel)
    request=dict(analysis_id='a',file='d.csv',kind='paired_complete',columns=['x','y'],assumption_evidence='source requires complete pairs')
    selection={'a':dict(file='d.csv',id_column='id',included_ids=[2,4])}
    result=data_checks.run(manifest,[request],sample_selections=selection)[0]
    assert result['status']=='passed' and result['n_checked']==2
    assert result['sample_scope']['deposit_rows']==4
    selection['a']['included_ids']=[2,3,4]
    result=data_checks.run(manifest,[request],sample_selections=selection)[0]
    assert result['status']=='anomaly' and result['affected_row_positions']==[2]
    selection['a']['file']='other.csv'
    assert data_checks.run(manifest,[request],sample_selections=selection)[0]['status']=='unverified'


def test_release_gate_retains_source_identity_ambiguities(tmp_path):
    import json
    from reproscope.source_integrity import review_run
    (tmp_path/'stage0').mkdir()
    (tmp_path/'stage0/readiness.json').write_text(json.dumps({'source_identity_problems':{'a1':[{'field':'figure_marker'}]}}))
    result=review_run(tmp_path)
    assert not result['semantic_ready']
    assert 'analysis source identities unresolved: a1' in result['semantic_blockers']


def test_validation_recomputes_review_dependencies(tmp_path, monkeypatch):
    """A stale review marker cannot certify its own dependencies as current."""
    from types import SimpleNamespace
    from reproscope import validation, stage0, stage1, stage3, source_integrity
    from reproscope.stage2 import review
    from reproscope.stage1 import blind
    monkeypatch.setattr(validation.paths, "ROOT", tmp_path)
    monkeypatch.setattr(validation.paths, "manifest", lambda _: object())
    monkeypatch.setattr(validation.cohort, "validate_runs", lambda _: None)
    monkeypatch.setattr(stage0, "input_hashes", lambda _: {"version": "same"})
    monkeypatch.setattr(stage1, "inputs", lambda _: {"version": "same"})
    monkeypatch.setattr(stage3, "_stage_inputs", lambda _: {"version": "same"})
    monkeypatch.setattr(review, "gather", lambda _: SimpleNamespace(hashes={"version": "new"}))
    monkeypatch.setattr(blind, "validate_packet_audit", lambda _: None)
    monkeypatch.setattr(source_integrity, "review_run", lambda _: {"semantic_ready": True})
    root = tmp_path / "runs/p"
    for stage in range(4):
        folder = root / f"stage{stage}"
        folder.mkdir(parents=True)
        (folder / "done.json").write_text(json.dumps({"inputs": {"version": "same"}}))
    monkeypatch.setattr(validation.paths, "is_done", lambda folder, inputs:
                        json.loads((folder / "done.json").read_text())["inputs"] == inputs)
    result = validation.check({"fingerprint": "test", "papers": [{"run_id": "p", "split": "development", "replicas": []}]})
    assert "stage2: outputs or dependencies require regeneration/reverification" in result["runs"]["p"]["blockers"]
    assert not result["all_runs_current"]


def test_upstream_sample_note_does_not_block_an_explicit_deposit_selector():
    from reproscope.intake_validation import separate_sample_context
    note={'analysis_id':'a','contract_field':'sample_rule','file':'data/x.csv','table':None,'chosen':None,'input_columns':[],'note':'upstream exclusions cannot be repeated'}
    executable,context=separate_sample_context([note],{})
    assert executable==[note] and not context
    selector={'a':{'file':'data/x.csv','table':None,'id_column':'ID','included_ids':None,'evidence':'all deposited participants'}}
    executable,context=separate_sample_context([note],selector)
    assert not executable and context==[note]
    selector['a']['file']='data/other.csv'
    assert separate_sample_context([note],selector)[0]==[note]


def test_conditional_scope_rules_are_exhaustive_disjoint_and_do_not_inherit_interval_metrics():
    from reproscope.multiverse_contract import specification_scope
    rule=dict(when={'scale':['raw']},effect_metric='mean_difference',effect_group='raw',null_group='location_zero',role='comparable_effect',rationale='Raw location contrast across declared estimators.')
    grid={'factors':[{'name':'scale','levels':[{'value':'raw'},{'value':'log'}]},
                     {'name':'interval','levels':[{'value':'bootstrap','effect_metric':'r'}]}],
          'reporting_rules_required':True,'reporting_rules':[rule]}
    spec={'spec_id':'s','levels':{'scale':'raw','interval':'bootstrap'}}
    assert specification_scope(spec,grid)['effect_metric']=='mean_difference'
    import pytest
    with pytest.raises(ValueError,match='got 0'):
        specification_scope({**spec,'levels':{'scale':'log','interval':'bootstrap'}},grid)
    with pytest.raises(ValueError,match='got 2'):
        specification_scope(spec,{**grid,'reporting_rules':[rule,rule]})
    with pytest.raises(ValueError,match='unknown/empty'):
        specification_scope(spec,{**grid,'reporting_rules':[{**rule,'when':{'absent':['raw']}}]})


def test_monte_carlo_counts_survive_nullable_integer_csv_serialisation():
    from reproscope.statistical import integer_field
    assert monte_carlo_p('0.0','10000.0')==monte_carlo_p(0,10000)
    assert integer_field('1.0','p_index')==1
    for value in ['0.5','NaN','Infinity','',True]:
        with pytest.raises(ValueError):monte_carlo_p(value,10000)
    with pytest.raises(ValueError):monte_carlo_p(0,999.5)


def test_derived_output_ranges_never_validate_individual_input_items():
    ct = artifacts.EstimandContract(analysis_id='a', outcome='sum score')
    schema = {'files':[{'path':'data/d.csv','tables':[{'table':None,'rows':8,'columns':[
        {'name':c,'dtype':'int64','min':1,'max':5} for c in ['x','y']]}]}]}
    binding = {'analysis_id':'a','contract_field':'outcome','file':'data/d.csv','table':None,
        'chosen':None,'input_columns':['x','y'],'transformation':'sum x and y','expected_type':'numeric',
        'allowed_range':[], 'input_ranges':[{'column':c,'bounds':[1,5]} for c in ['x','y']], 'derived_range':[2,10]}
    assert validate_bindings([ct],[binding],schema)=={'a':[]}
    legacy = {**binding,'allowed_range':[2,10],'input_ranges':[],'derived_range':[]}
    errors = validate_bindings([ct],[legacy],schema)['a']
    assert any('Ambiguous derived range' in e for e in errors)
    assert not any('input range check failed' in e for e in errors)
    bad = {**binding,'input_ranges':[{'column':'x','bounds':[1,4]}]}
    assert any('declared=[1, 4], observed_min=1, observed_max=5' in e for e in validate_bindings([ct],[bad],schema)['a'])


def test_derived_inputs_cannot_hide_an_invalid_chosen_column():
    ct=artifacts.EstimandContract(analysis_id='a',outcome='score')
    schema={'files':[{'path':'data/d.csv','tables':[{'table':None,'columns':[
        {'name':'x','dtype':'int64','min':1,'max':5},{'name':'y','dtype':'int64','min':1,'max':5}]}]}]}
    b={'analysis_id':'a','contract_field':'outcome','file':'data/d.csv','chosen':'x+y',
       'input_columns':['x','y'],'transformation':'sum'}
    assert any('chosen must be one exact' in e for e in validate_bindings([ct],[b],schema)['a'])
    assert validate_bindings([ct],[{**b,'chosen':None}],schema)=={'a':[]}
