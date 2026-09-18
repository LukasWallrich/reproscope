"""Independent, source-only translation into a closed numerical verification recipe.

The translator receives screened methods, the blind contract and column names.
It cannot see any executor source, result, plan, or participant record. Recipes
are cached against their exact inputs and reviewed by a separate subscription model.
"""
from pathlib import Path
from typing import Literal, Any
import json
from pydantic import BaseModel, ConfigDict, Field, model_validator
from . import artifacts, config, llm, provenance

VERSION='closed-multiverse-2'

class Recipe(BaseModel):
    model_config=ConfigDict(extra='forbid')
    file:str
    x:str
    y:str
    id_column:str | None=None
    design:Literal['paired','association']
    estimator:Literal['mean','yuen','trimmed_difference','rank_biserial','partial','semipartial']
    transform:Literal['identity','log']='identity'
    rank:bool=False
    covariates:list[str]=[]
    polynomial_column:str | None=None
    polynomial_degree:Literal[1,2]=1
    spline_probabilities:list[float]=[]
    spline_knot_scope:Literal['retained','complete_cases']='retained'
    x_items:list[str]=[]
    y_items:list[str]=[]
    scoring:Literal['deposited','prorate','exclude_flagged']='deposited'
    integer_tolerance:float=1e-8
    min_item_fraction:float=.8
    outliers:Literal['none','iqr_difference','mahalanobis','studentized_residual_trim']='none'
    outlier_fraction:float=Field(default=.05,gt=0,lt=.5)
    rank_covariates:bool=False
    approximate_rank_fisher:bool=False
    outlier_columns:list[str]=[]
    outlier_threshold:float=1.5
    mahalanobis_probability:float=.999
    trim_fraction:float=.2
    test:Literal['t','yuen','wilcoxon','sign_flip','freedman_lane','residual_permutation']
    wilcoxon_policy:Literal['auto','exact_no_ties']='auto'
    permutation_target:Literal['outcome','predictor']='outcome'
    permutation_statistic:Literal['effect','t']='effect'
    alternative:Literal['two-sided','greater','less']='two-sided'
    test_draws:int=Field(default=20000,ge=1000,le=200000)
    test_seed:int=20260915
    ci:Literal['student_t','yuen','fisher_z','bca','percentile']
    ci_level:float=.95
    ci_draws:int=Field(default=10000,ge=1000,le=200000)
    ci_seed:int=20260915
    adjustment:Literal['none','holm','fixed_threshold']='none'
    per_test_alpha:float | None=None
    family:list[dict[str,Any]]=[]
    note:str=''

    @model_validator(mode='after')
    def coherent(self):
        if self.design=='paired':
            if self.estimator not in {'mean','yuen','trimmed_difference','rank_biserial'} or self.rank or self.covariates or self.polynomial_column or self.spline_probabilities:
                raise ValueError('unsupported paired estimator or nuisance transformation')
            tests={'mean':{'t','sign_flip'},'yuen':{'yuen'},'trimmed_difference':{'yuen'},'rank_biserial':{'wilcoxon'}}
            intervals={'mean':{'student_t','bca','percentile'},'yuen':{'yuen','student_t','percentile'},'trimmed_difference':{'yuen','student_t','percentile'},'rank_biserial':{'percentile'}}
            if self.test not in tests[self.estimator] or self.ci not in intervals[self.estimator]:raise ValueError('paired estimator/test/interval mismatch')
        else:
            if self.transform!='identity':raise ValueError('association transform requires a separate documented protocol')
            if self.estimator not in {'partial','semipartial'} or self.test not in {'t','freedman_lane','residual_permutation'} or self.ci not in {'fisher_z','percentile'}:
                raise ValueError('unsupported association estimator/test/interval combination')
            if self.ci=='fisher_z' and ((self.rank and not self.approximate_rank_fisher) or self.estimator!='partial'):raise ValueError('Fisher interval requires estimator=partial; rank=true additionally requires approximate_rank_fisher=true')
            if self.test in {'freedman_lane','residual_permutation'} and self.alternative!='two-sided':raise ValueError('Freedman-Lane adapter currently requires two-sided test')
        if not 0<self.ci_level<1 or not 0<=self.trim_fraction<.5 or self.outlier_threshold<=0 or not 0<self.mahalanobis_probability<1:
            raise ValueError('invalid method probability or trimming/outlier control')
        if self.scoring!='deposited' and (not self.x_items or not self.y_items):raise ValueError('scoring requires explicit items for each scale')
        if self.spline_probabilities and (not self.polynomial_column or self.polynomial_degree!=1 or len(self.spline_probabilities)!=3 or sorted(set(self.spline_probabilities))!=self.spline_probabilities or not all(0<p<1 for p in self.spline_probabilities)):
            raise ValueError('natural spline requires one named raw nuisance column and three ordered interior probabilities')
        if self.outliers=='iqr_difference' and self.design!='paired':raise ValueError('difference-IQR requires paired design')
        if self.permutation_statistic=='t' and self.test!='freedman_lane':raise ValueError('coefficient t permutation statistic requires Freedman-Lane refitting')
        if self.test=='residual_permutation' and self.estimator=='semipartial' and self.permutation_target!='predictor':raise ValueError('direct semipartial residual permutation must move predictor')
        if self.outliers=='studentized_residual_trim' and self.design!='association':raise ValueError('studentized residual trimming requires association')
        if self.outliers=='mahalanobis' and not self.outlier_columns:raise ValueError('Mahalanobis requires explicit columns')
        if self.adjustment=='holm' and not self.family:raise ValueError('Holm requires nonfocal members')
        if self.adjustment=='fixed_threshold' and (self.per_test_alpha is None or not 0<self.per_test_alpha<=.05 or self.family):raise ValueError('fixed threshold requires source alpha and no family')
        if self.adjustment=='none' and self.family:raise ValueError('unadjusted result cannot silently carry a correction family')
        return self

class ConditionalPatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    when:dict[str,list[str]]
    patch:dict[str,Any]

class RecipeBook(BaseModel):
    model_config=ConfigDict(extra='forbid')
    base:Recipe
    factors:dict[str,dict[str,dict[str,Any]]]
    conditions:list[ConditionalPatch]=[]
    evidence:list[str]
    limitations:list[str]

class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    accepted:bool
    problems:list[str]
    evidence:list[str]

INSTRUCTIONS='''Permutation statistic: permutation_statistic=t uses the full-model OLS coefficient t statistic for both the observed and every permuted sample, with df=n-q-2; this can accompany a semi-partial point estimate. permutation_statistic=effect uses the selected full/semi-partial correlation itself. Preserve the screened choice explicitly. Recipe extensions: conditions contains explicit factor-level selectors and shallow overrides applied AFTER factor patches, for screened interactions (e.g. CI by estimator); overlapping conditional patches must agree. studentized_residual_trim fits both RAW outcome and predictor to the selected raw nuisance design with intercept before ranking. Use maximum absolute internally studentized residual across the two fits, exclude ceil(outlier_fraction*n) largest scores once; round scores to 12 decimal places before sorting to make numerical ties reproducible, then break ties by original deposited row order. Refit/rank only after selection. rank_covariates=true ranks every additional covariate when rank=true; polynomial_column already ranks by default. approximate_rank_fisher=true permits a SCREENED approximate Fisher interval for FULL rank partial correlation, never semipartial. residual_permutation directly permutes the named residual vector against the other fixed vector, without adding fitted values or projecting again; this differs from freedman_lane. It requires an explicit selected target and screened null; do not substitute one for the other. t is the supported analytical partial/semipartial coefficient test. Fixed implementation defaults where not otherwise specified: test_draws=20000, ci_draws=10000, both seeds=20260915, PCG64, linear quantiles. No invented hypothesis test or interval: unresolved scientific choices must return to screening.
Translate the supplied screened multiverse into a closed RecipeBook. No computation and no tools. The base defines common settings; factors maps EVERY executed factor and EVERY level to a shallow dictionary of Recipe field overrides (empty where no change). Combinations merge base and patches; conflicting nonidentical patches are rejected. Follow the screened how text and blind contract, including conditional estimator, test, interval, sample and nuisance interactions. No paper values, estimated sample IDs or computed outputs.
Recipe semantics: paired x-y preserves orientation. transform=log verifies positive paired values then logs both condition columns BEFORE the outlier rule, estimation and resampling. Its location output is log_ratio, never an exponentiated ratio. mean is arithmetic mean difference; yuen is difference of separately trimmed marginal means with paired winsorised covariance; trimmed_difference is the symmetrically trimmed mean of within-pair differences, with one-sample winsorised-difference variance and effective df h-1, and test=yuen. These two trimming methods are distinct; follow the actual screened method. Both support matched analytic or participant-percentile intervals; rank_biserial uses nonzero signed midranks. For a signed-rank level requiring exact inference and explicitly refusing ties/zeros, set wilcoxon_policy=exact_no_ties; otherwise the documented auto policy applies. The private check preserves an exact-no-ties domain by subsampling whole records without replacement rather than manufacturing duplicates. association x is outcome Y, y is predictor X; partial residualises both; semipartial residualises X only. rank=true midranks x/y and polynomial_column before building nuisance; other covariates are unchanged (binary). covariates are additional nuisance columns, polynomial_column is handled separately (centred linear and squared when degree=2). A three-knot restricted/natural cubic spline is specified with spline_probabilities=[lower,interior,upper] and polynomial_column naming its RAW nuisance variable, polynomial_degree=1. It uses two nuisance columns, including the linear term; never rank the spline input even when rank=true. spline_knot_scope=retained takes quantiles after selection; complete_cases takes quantiles before scoring/outlier exclusions. Choose the screened scope explicitly, then freeze those knots throughout participant bootstrap draws. Always intercept. OLS coefficient test uses full-model residual df even for semipartial. Scoring noninteger flags are a reconstruction assumption, not established missing-value indicators. x_items/y_items explicit full columns; prorate asserts sum equals deposited total, replaces flagged cells by person's unflagged mean if >=min_item_fraction; exclude_flagged removes any flagged row. Outliers apply after scoring, once before rank/resampling. mahalanobis uses specified raw columns and sample covariance; iqr_difference filters x-y at quartiles +/- threshold*IQR. Bootstrap resamples retained whole records and refits/reranks/rebuilds nuisance, never repeats fixed outlier screen. CI two-sided at ci_level regardless test tail. test_draws/ci_draws and seeds are fixed controls.
For Holm family, family lists only NONFOCAL direct paired-test recipe dictionaries (file,x,y,alternative,design=paired,estimator=mean,test=t,ci=student_t, other fields as needed); they must correspond to the screened family and explicitly described sample policy. The focal p is added automatically. For paper fixed per-comparison criterion use adjustment=fixed_threshold, per_test_alpha=declared criterion, family=[]; it is compared as min(1,p_raw*.05/per_test_alpha) against .05, without inventing nonfocal p-values or claiming a recovered family size. For Freedman-Lane, permutation_target names the variable whose reduced-model residuals the screened algorithm permutes: outcome means x, predictor means y. Preserve this choice explicitly even though the point partial correlation is symmetric. All non-null tests must have a defensible method. Ignore old assertions of adapter limitations; our closed interpreter now supports these methods. If an essential choice is unspecified or unsupported, document in limitations and do not silently invent it. Evidence must identify the factor/level or contract clause for bindings and adjustments. Do not use paper-specific dispatch, hardcoded results or dataset-name logic. Return the schema.'''


def compile_book(book, grid, *, source_roles=None):
    from .stage3.multiverse import enumerate_specs
    book=RecipeBook.model_validate(book).model_dump()
    specs=enumerate_specs(grid)
    expected={f['name']:{l['value'] for l in f['levels']} for f in grid['factors']}
    if set(book['factors'])!=set(expected):raise ValueError('recipe factor coverage differs from screened grid')
    for name,levels in expected.items():
        if set(book['factors'][name])!=levels:raise ValueError('recipe level coverage differs: '+name)
    result={};errors={}
    for s in specs:
        r=dict(book['base']);assigned={}
        for factor,value in s['levels'].items():
            patch=book['factors'][factor][value]
            for k,v in patch.items():
                if k in assigned and assigned[k]!=v:raise ValueError('conflicting recipe patches: '+k)
                assigned[k]=v
            r.update(patch)
        conditional={}
        for condition in book['conditions']:
            if any(f not in expected or not set(levels)<=expected[f] for f,levels in condition['when'].items()):raise ValueError('unknown conditional recipe selector')
            if all(s['levels'].get(f) in levels for f,levels in condition['when'].items()):
                for k,v in condition['patch'].items():
                    if k in conditional and conditional[k]!=v:raise ValueError('conflicting conditional recipe patches: '+k)
                    conditional[k]=v
        r.update(conditional)
        if source_roles and r.get('design')=='association' and (r.get('x'),r.get('y'))!=source_roles:
            why=f'association x must be the bound outcome {source_roles[0]}, y the bound predictor {source_roles[1]}; swapping them changes semi-partial estimates and directed permutation procedures'
            errors.setdefault(why,[]).append(s['spec_id'])
        try:result[s['spec_id']]=Recipe.model_validate(r).model_dump()
        except ValueError as exc:
            why='; '.join(e['msg'] for e in exc.errors()) if hasattr(exc,'errors') else str(exc)
            errors.setdefault(why,[]).append(s['spec_id']+' '+json.dumps(s['levels']))
    if errors:raise ValueError('\n'.join(why+' Affected: '+', '.join(ids[:3])+(' (and others)' if len(ids)>3 else '') for why,ids in errors.items()))
    return result



def source_bindings(paper_id,contract):
    from . import paths
    source=paths.run_dir(paper_id,0)/'readiness.json'
    if not source.exists():return []
    aid=(contract.get('contract') or contract).get('analysis_id')
    return [{k:b.get(k) for k in ('contract_field','chosen','file','input_columns','transformation')}
        for b in json.loads(source.read_text()).get('variable_bindings',[]) if b.get('analysis_id')==aid]


def source_identifiers(work):
    """Locate source-labelled identifiers, validating uniqueness without exposing rows."""
    import re
    import pandas as pd
    labels=set();work=Path(work)
    for path in (work/'data').glob('*.txt'):
        try:doc=json.loads(path.read_text())
        except (ValueError,OSError):continue
        if not isinstance(doc,dict):continue
        for sheet in doc.get('sheets',[]):
            for row in sheet.get('rows',[]):
                if len(row)>=2 and isinstance(row[0],str) and isinstance(row[1],str) and re.search(r'\b(?:ID|identifier)\b',row[1],re.I):labels.add(row[0])
    result={}
    for path in (work/'data').glob('*.csv'):
        columns=set(pd.read_csv(path,nrows=0).columns);candidates=labels&columns
        if candidates:
            frame=pd.read_csv(path,usecols=sorted(candidates))
            valid=[c for c in sorted(candidates) if frame[c].notna().all() and frame[c].is_unique]
            if valid:result[str(path.relative_to(work))]=valid
    return result


def validate_source_bindings(book,grid,bindings,identifiers=None):
    """Fix asymmetric variable roles to the controller's approved source bindings."""
    by_field={b['contract_field']:b for b in bindings if b.get('chosen') and not b.get('transformation')}
    outcome=by_field.get('outcome');predictors=[v for k,v in by_field.items() if k.startswith('predictors[')]
    # A genuinely varied outcome or predictor needs its own per-level binding review.
    changing=any(f.get('field') in {'outcome','predictor','predictors'} for f in grid.get('factors',[]))
    roles=(outcome['chosen'],predictors[0]['chosen']) if outcome and len(predictors)==1 and not changing else None
    compiled=compile_book(book,grid,source_roles=roles)
    for sid,r in compiled.items():
        choices=(identifiers or {}).get(r['file'],[])
        if choices and r['id_column'] not in choices:raise ValueError(f'{sid}: source codebook identifies unique participant identifiers {choices}; id_column must name one so retained identities and private resamples can be checked')
    return compiled


def prepare(work, grid, paper_id):
    import pandas as pd
    work=Path(work);folder=work.parent/'independent_recipe';folder.mkdir(exist_ok=True)
    from .stage3.multiverse import executor_grid
    payload={'grid':executor_grid(grid),'contract':json.loads((work/'CONTRACT.json').read_text()),
        'columns':{str(p.relative_to(work)):list(pd.read_csv(p,nrows=0).columns) for p in sorted((work/'data').glob('*.csv'))}}
    payload['source_bindings']=source_bindings(paper_id,payload['contract'])
    payload['codebook']={p.name:p.read_text() for p in sorted((work/'data').glob('*')) if p.suffix.lower() in {'.txt','.md'}}
    key=provenance.digest({'version':VERSION,'inputs':payload,'instructions':INSTRUCTIONS,'schema':RecipeBook.model_json_schema()})
    identifiers=source_identifiers(work)
    cached=folder/(key+'.json')
    record=None
    if cached.exists():
        record=json.loads(cached.read_text())
        if record.get('accepted'):
            try:validate_source_bindings(record['book'],grid,payload['source_bindings'],identifiers)
            except ValueError as exc:
                record={**record,'accepted':False,'review':{'accepted':False,'problems':[str(exc)],'evidence':[]}}
            else:return record
    import os
    adjudication_model=os.getenv('REPROSCOPE_RECIPE_ADJUDICATION_MODEL')
    if record and not record['accepted'] and adjudication_model and not any(h.get('kind')=='adjudication' for h in record.get('history',[])):
        controller=[]
        try:validate_source_bindings(record['book'],grid,payload['source_bindings'],identifiers)
        except ValueError as exc:controller=[str(exc)]
        response=llm.call('independent_method_recipe_adjudication',INSTRUCTIONS+'\nIndependently adjudicate the rejected source-only translation. Separate substantive source mismatches from reviewer misunderstandings of fixed Recipe semantics or paragraph scope. The fixed interpreter conventions (including 12-decimal trim-score rounding) need no separate field or note. Check every source interaction, especially full versus semi-partial CI scopes and permutation statistics. Do not invent missing scientific choices. Controller binding/identifier errors are mandatory and cannot be waived. Return accepted only for a faithful complete recipe.\nInputs:'+json.dumps(payload)+'\nSource identifier candidates:'+json.dumps(identifiers)+'\nRecipe:'+json.dumps(record['book'])+'\nReviewer objections:'+json.dumps(record['review'])+'\nController errors:'+json.dumps(controller),
            paper_id=paper_id,stage='3',route='claude_p',model=adjudication_model,agentic=False,schema=Review,log_path=folder/f'{key}-adjudication.log',timeout_s=900,large_context=True)
        if not response.ok or response.parsed is None:raise RuntimeError('Source recipe adjudication failed')
        verdict=response.parsed.model_dump()
        if controller:verdict={**verdict,'accepted':False,'problems':list(dict.fromkeys(verdict['problems']+controller))}
        record['history'].append({'call':response.ledger_id,'kind':'adjudication','model':adjudication_model,'prior_review':record['review'],'decision':verdict})
        record.update(review=verdict,accepted=verdict['accepted'])
        cached.write_text(json.dumps(record,indent=2)+'\n')
        if record['accepted']:return record
    spec=config.tier('strong');other=config.tier('mid')
    history=record.get('history',[]) if record else [];feedback=''
    start=1+sum(h.get('kind')=='translation' for h in history)
    if record:feedback='Correct review findings while preserving all other settings: '+json.dumps(record['review']['problems'])+'\nPrevious candidate:\n'+json.dumps(record['book'])
    if record is None:
        failed=[]
        for path in folder.glob(key+'-*.candidate.json'):
            number=int(path.name.removeprefix(key+'-').removesuffix('.candidate.json'))
            failed.append((number,json.loads(path.read_text())))
        failed.sort()
        if failed and [n for n,_ in failed]==list(range(1,failed[-1][0]+1)):
            history=[{'call':r['call'],'kind':'translation'} for _,r in failed]
            start=failed[-1][0]+1;previous=failed[-1][1]['book']
            try:validate_source_bindings(previous,grid,payload['source_bindings'],identifiers)
            except ValueError as exc:problem=str(exc)
            else:problem='Recheck previously failed translation against the current source contract.'
            feedback='Fix only invalid schema/coverage, preserving supported settings: '+problem+'\nPrevious candidate:\n'+json.dumps(previous)
    limit=7 if any(h.get('kind')=='adjudication' for h in history) else 5
    for attempt in range(start,limit+1):
        import os
        chosen=config.tier(os.environ['REPROSCOPE_METHOD_REPAIR_TIER']) if attempt>=3 and os.environ.get('REPROSCOPE_METHOD_REPAIR_TIER') else spec
        answer=llm.call('independent_method_recipe',INSTRUCTIONS+'\n'+json.dumps(payload)+'\n'+feedback,
            paper_id=paper_id,stage='3',route=chosen.route,model=chosen.model,agentic=False,schema=RecipeBook,
            log_path=folder/f'{key}-{attempt}.log',timeout_s=900,large_context=True)
        history.append({'call':answer.ledger_id,'kind':'translation'})
        if not answer.ok or answer.parsed is None:raise RuntimeError('Independent recipe translation failed: '+str(answer.error))
        book=answer.parsed.model_dump()
        try:validate_source_bindings(book,grid,payload['source_bindings'],identifiers)
        except ValueError as exc:
            (folder/f'{key}-{attempt}.candidate.json').write_text(json.dumps({'book':book,'call':answer.ledger_id,'compile_error':str(exc)},indent=2)+'\n')
            feedback='Fix only the invalid schema/coverage while preserving supported settings: '+str(exc)+'\nPrevious candidate:\n'+json.dumps(book)
            continue
        # Reviewer sees only source inputs and recipe, never executor artifacts.
        review=llm.call('independent_method_recipe_review',INSTRUCTIONS+'\nReview the candidate recipe for faithful source bindings and every interaction. Return accepted=false for substantive mismatches. Do not require a recovered family size for a fixed published threshold. No tools; all evidence is in this prompt.\nInputs:'+json.dumps(payload)+'\nRecipe:'+json.dumps(book)+'\nPrior source adjudication (retain its valid scope interpretations while checking this revision independently):'+json.dumps([h.get('decision') for h in history if h.get('kind')=='adjudication']),
            paper_id=paper_id,stage='3',route=other.route,model=other.model,agentic=False,schema=Review,
            cwd=folder,log_path=folder/f'{key}-{attempt}-review.log',timeout_s=900,large_context=True)
        history.append({'call':review.ledger_id,'kind':'review'})
        if not review.ok or review.parsed is None:raise RuntimeError('Independent recipe review failed: '+str(review.error))
        verdict=review.parsed.model_dump()
        adjudication_model=os.getenv('REPROSCOPE_RECIPE_ADJUDICATION_MODEL')
        if not verdict['accepted'] and adjudication_model and sum(h.get('kind')=='review' for h in history)>=2 and not any(h.get('kind')=='adjudication' for h in history):
            adjudication=llm.call('independent_method_recipe_adjudication',INSTRUCTIONS+'\nAdjudicate these source-translation objections independently. The fixed Recipe semantics are part of the interpreter: do not require a field or note restating fixed conventions (including residual-score rounding). Check the actual algorithm and all conditional scopes, outcome/predictor roles, identification and inference. Accept only a faithful complete translation. No results, executor code or participant rows are supplied.\nInputs:'+json.dumps(payload)+'\nRecipe:'+json.dumps(book)+'\nReview objections:'+json.dumps(verdict),
                paper_id=paper_id,stage='3',route='claude_p',model=adjudication_model,agentic=False,schema=Review,
                log_path=folder/f'{key}-{attempt}-adjudication.log',timeout_s=900,large_context=True)
            history.append({'call':adjudication.ledger_id,'kind':'adjudication','model':adjudication_model,'prior_review':verdict})
            if adjudication.ok and adjudication.parsed is not None:verdict=adjudication.parsed.model_dump()
        record={'version':VERSION,'input_sha256':key,'book':book,'review':verdict,'accepted':verdict['accepted'],
            'history':history,'input_scope':'screened blind methods, contract, approved variable bindings, source codebook and column names; no executor artifacts or participant records'}
        cached.write_text(json.dumps(record,indent=2)+'\n')
        if verdict['accepted']:return record
        feedback='Correct review findings while preserving all other settings: '+json.dumps(verdict['problems'])+'\nPrevious candidate:\n'+json.dumps(book)
    raise RuntimeError('Independent method recipe could not pass source review')
