"""Independent-context source benchmark, kept outside production stage inputs.

Model-assisted evaluation is not human annotation or held-out validation. Inventory
is frozen before it is compared with extraction; findings never edit source gold.
"""
import argparse
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from pydantic import BaseModel, ConfigDict
from . import artifacts, paths, llm, response_cache
from .stage0.extract import page_paths, page_texts

class Item(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_id:str
    evidence:str
    value:float
    comparator:Literal['=','<','>','<=','>=']
    quantity_kind:str
    precision:int
    study:str
    outcome:str
    contrast:str
    clean:bool
    reason:str

class Inventory(BaseModel):
    model_config=ConfigDict(extra='forbid')
    items:list[Item]
    coverage_notes:str
    excluded_categories:list[str]

class Match(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_id:str
    claim_id:str|None
    verdict:Literal['correct','incorrect','missing','uncertain']
    reason:str
    field:Literal['value','degrees_of_freedom[0]','degrees_of_freedom[1]']="value"

class Matches(BaseModel):
    model_config=ConfigDict(extra='forbid')
    items:list[Match]

INVENTORY_PROMPT='''Read the supplied page IMAGE and contextual paper text to create a source-only numerical inventory. You have no pipeline extraction or reproduction outputs. Inventory every explicitly reported empirical numerical quantity for this paper's studies, including sample counts (also spelled out), exclusions, demographics, test statistics, p bounds, effect sizes, descriptives and fit quantities. One record per physical occurrence; separate repeated reports and distinct annotated brackets. Exclude page/reference/study numbers, design constants, axis ticks, unlabelled bar heights, equation constants and other papers' results. Each item needs a unique source_id beginning with the given page ID, exact source evidence, literal number/operator/decimals, kind and semantic study/outcome/contrast. Do not infer unprinted numbers. Set clean=false only for actually ambiguous/unreadable numbers or associations and explain why, never to avoid difficult tables. Describe covered regions and excluded categories. Context from other pages identifies meaning, but only inventory the supplied image. This is a model-assisted benchmark requiring independent human validation, not ground truth by assertion.'''


def root(paper_id):return paths.ROOT/'validation_benchmarks'/paper_id/'source_first'


def semantic_candidate(claim):
    """Only transcription and meaning enter the judge, never pipeline decisions/logs."""
    fields = ('claim_id', 'study_id', 'claim_type', 'quantity_kind', 'value', 'comparator',
              'precision', 'source_quote', 'source_region', 'figure_panel', 'figure_endpoints',
              'legend_quote', 'quantity_role', 'aggregation', 'member_ids', 'target_outcome',
              'target_contrast', 'target_model', 'uncertainty', 'location', 'description',
              'analysis_label')
    return {key: claim[key] for key in fields if key in claim}


def inventory(paper_id):
    man=paths.manifest(paper_id);pages=page_paths(man);folder=root(paper_id);folder.mkdir(parents=True,exist_ok=True)
    context=(man.dir/'paper.txt').read_text()
    def one(entry):
        i,image=entry;out=folder/f'page_{i:03d}.json'
        ins={'pdf':artifacts.sha256_file(man.path(man.pdf)),'image':artifacts.sha256_file(image),'prompt':paths.hash_text(INVENTORY_PROMPT)}
        if out.exists() and json.loads(out.read_text()).get('inputs')==ins:return json.loads(out.read_text())
        result=llm.call('source_first_inventory',INVENTORY_PROMPT+f'\nPage ID p{i:03d}.\nContext:\n'+context,
            paper_id=paper_id,stage='benchmark',tier='strong',images=[image],schema=Inventory,
            timeout_s=1200,log_path=folder/f'page_{i:03d}.log')
        if not result.ok or not result.parsed:raise RuntimeError(str(result.error))
        got={'page':i,'inputs':ins,'call_id':result.ledger_id,**result.parsed.model_dump()}
        for j,item in enumerate(got['items']):item['source_id']=f'p{i:03d}_q{j+1:03d}'
        out.write_text(json.dumps(got,indent=2)+'\n');print('benchmark page',i,len(got['items']),flush=True)
        return got
    with ThreadPoolExecutor(max_workers=3) as pool:records=list(pool.map(one,enumerate(pages,1)))
    if len(records)!=len(pages):raise ValueError('inventory does not cover every page')
    result={'scope':'Source-first model inventory, frozen before output comparison; no independent human or held-out validation.',
        'pdf_sha256':artifacts.sha256_file(man.path(man.pdf)),'pages':records}
    dest=folder/'frozen_inventory.json'
    if dest.exists() and json.loads(dest.read_text())!=result:raise ValueError('frozen benchmark changed; create a separately reviewed version')
    dest.write_text(json.dumps(result,indent=2)+'\n')
    return dest


def review_inventory(paper_id):
    """Independent source-only second reading; preserve both frozen versions."""
    folder=root(paper_id);original=folder/'frozen_inventory.json'
    gold=json.loads(original.read_text());man=paths.manifest(paper_id);pages=page_paths(man)
    context=(man.dir/'paper.txt').read_text()
    def one(page):
        if not page['items']:return page
        prompt=INVENTORY_PROMPT+'\nIndependently validate this proposed inventory against the page image and paper context. Correct every wrong literal/operator/precision or study/outcome/contrast. Add missed empirical occurrences, retain metadata such as printed degrees of freedom as quantity_kind="df", and mark design constants (e.g. a target power of 80%) clean=false with a reason. Range endpoints have literal comparator "=" and an endpoint description, not invented >=/<= claims. Do not remove difficult or ambiguous items: retain them with clean=false and a specific source reason. No extraction outputs or evaluation verdicts are supplied.\nProposed inventory:\n'+json.dumps(page['items'])+'\nPaper context:\n'+context
        cache=folder/f'review_{page["page"]:03d}.response.json';images=[pages[page['page']-1]]
        key=response_cache.key(prompt,Inventory,images,'strong');saved=response_cache.read(cache,key,Inventory)
        if saved:parsed,cid=saved
        else:
            r=llm.call('source_inventory_review',prompt,paper_id=paper_id,stage='benchmark',tier='strong',images=images,schema=Inventory,timeout_s=1200,log_path=folder/f'review_{page["page"]:03d}.log')
            if not r.ok or not r.parsed:raise RuntimeError(str(r.error))
            parsed,cid=r.parsed,r.ledger_id;response_cache.write(cache,key,parsed,cid)
        output={**page,**parsed.model_dump(),'review_call_id':cid}
        for j,item in enumerate(output['items']):item['source_id']=f'p{page["page"]:03d}_q{j+1:03d}'
        return output
    with ThreadPoolExecutor(max_workers=3) as pool:reviewed=list(pool.map(one,gold['pages']))
    output={**gold,'pages':reviewed,'original_inventory_sha256':artifacts.sha256_file(original),
        'scope':'Two source-only model readings; original inventory retained. Review model saw no pipeline output or grades. Development benchmark, not human or held-out validation.'}
    dest=folder/'reviewed_inventory.json'
    if dest.exists() and json.loads(dest.read_text())!=output:raise ValueError('reviewed benchmark changed')
    dest.write_text(json.dumps(output,indent=2)+'\n')
    return dest


def score(paper_id):
    folder=root(paper_id);frozen=folder/'reviewed_inventory.json'
    if not frozen.exists():frozen=folder/'frozen_inventory.json'
    if not frozen.exists():raise ValueError('freeze source-first inventory before scoring')
    gold=json.loads(frozen.read_text());stage=paths.run_dir(paper_id,0);claim_path=stage/'claims.json'
    import hashlib
    raw_claims=claim_path.read_bytes();claims=json.loads(raw_claims);all_matches=[]
    claims_hash=hashlib.sha256(raw_claims).hexdigest()
    from .reported_metadata import fields
    metadata=fields(claims)
    texts=page_texts(paths.manifest(paper_id),len(gold['pages']))
    def match_page(page):
        expected=[i for i in page['items'] if i['clean']]
        if not expected:return []
        candidates=[semantic_candidate(c) for c in claims if (c.get('location') or {}).get('page')==page['page']]
        prompt='''Match this frozen source inventory to candidate extraction records on the same physical page. Check every expected source occurrence. Return one item per source_id. Mark correct only when number/operator/precision, statistic, study/sample, outcome, contrast, and aggregation all match the source meaning; synonyms are allowed. Repeated occurrences must map to distinct claim/field pairs. Report field="value" for primary values. Degrees of freedom are already extracted as metadata of their test: map them to a supplied metadata field, such as degrees_of_freedom[0], on the corresponding test claim. A candidate can cover its test value and its df through different fields. Judge transcription/meaning independently of the candidate acceptance state; state is checked separately by the controller. Do not assume either inventory or candidates are correct. Use uncertain if the inventory conflicts with the supplied page text, incorrect for wrong candidate meaning/literal value, missing if not extracted. A raw signed t can differ in convention only when the source supports the actual direction; do not invent orientation. No reproduction results or prior verdicts are supplied.\n'''+json.dumps({'expected':expected,'candidates':candidates,'metadata':[m for m in metadata if m['page']==page['page']],'page_text':texts[page['page']]})
        key=response_cache.key(prompt,Matches,[],'strong');cache=folder/f'match_{page["page"]:03d}.response.json'
        saved=response_cache.read(cache,key,Matches)
        if saved:parsed,_=saved
        else:
            result=llm.call('source_benchmark_match',prompt,paper_id=paper_id,stage='benchmark',tier='strong',schema=Matches,timeout_s=1200,log_path=folder/f'match_{page["page"]:03d}.log')
            if not result.ok or not result.parsed:raise RuntimeError(str(result.error))
            parsed=result.parsed;response_cache.write(cache,key,parsed,result.ledger_id)
        if len(parsed.items)!=len(expected) or {m.source_id for m in parsed.items}!={i['source_id'] for i in expected}:raise ValueError('benchmark match omitted or added source IDs')
        by_id={c['claim_id']:c for c in candidates};truth={i['source_id']:i for i in expected}
        matches=[]
        for m in parsed.items:
            row=m.model_dump();c=by_id.get(m.claim_id,{});q=truth[m.source_id]
            if m.field=='value':literal=bool(c) and all(c.get(k)==q[k] for k in ('value','comparator','precision'))
            else:literal=any(f['claim_id']==m.claim_id and f['field']==m.field and f['value']==q['value'] for f in metadata) and q['comparator']=='=' and q['precision']==0
            if m.verdict=='correct' and not literal:row.update(verdict='incorrect',reason='deterministic literal check failed')
            matches.append(row)
        return matches
    with ThreadPoolExecutor(max_workers=3) as pool:
        for batch in pool.map(match_page,gold['pages']):all_matches.extend(batch)
    from collections import Counter
    duplicates={key for key,n in Counter((m['claim_id'],m['field']) for m in all_matches if m['verdict']=='correct').items() if n>1}
    accepted={c['claim_id'] for c in claims if c.get('state')=='complete' and c.get('source_validation') in {'text_anchored','visual_adjudicated'}}
    correct=[m for m in all_matches if m['verdict']=='correct' and (m['claim_id'],m['field']) not in duplicates and m['claim_id'] in accepted]
    n=sum(i['clean'] for p in gold['pages'] for i in p['items'])
    if artifacts.sha256_file(claim_path)!=claims_hash:
        raise RuntimeError('Extraction changed during benchmark scoring; rerun against the current claims.')
    result={'scope':gold['scope'],'gold_sha256':artifacts.sha256_file(frozen),'claims_sha256':claims_hash,
        'clean_source_occurrences':n,'accepted_count':len(accepted),'accepted_correct':len(correct),
        'accepted_recall':len(correct)/n if n else None,'accepted_precision':len({m['claim_id'] for m in correct if m['field']=='value'})/len(accepted) if accepted else None,
        'correct_metadata_fields':sum(m['field']!='value' for m in correct),
        'precision_denominator':'accepted primary result records; recall includes separately inventoried df metadata',
        'matches':all_matches,'duplicate_matches':sorted(duplicates),'ambiguous_inventory_items':[i for p in gold['pages'] for i in p['items'] if not i['clean']]}
    result['passed']=bool(n and accepted and result['accepted_recall']>.95 and result['accepted_precision']>.95 and not duplicates)
    (stage/'extraction_benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
    print({k:v for k,v in result.items() if k not in {'matches','ambiguous_inventory_items'}},flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['inventory','review','score']);parser.add_argument('paper_id');args=parser.parse_args()
    {'inventory':inventory,'review':review_inventory,'score':score}[args.mode](args.paper_id)
