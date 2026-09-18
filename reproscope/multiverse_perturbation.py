"""Change empirical distributions while preserving within-record constraints."""
import json
from pathlib import Path
import numpy as np
import pandas as pd


def resample_records(work, *, recipes=None):
    work=Path(work)
    plans=recipes if recipes is not None else json.loads((work/'out/analysis_plan.json').read_text())['specs']
    files={};subsample=set()
    for plan in plans:
        if plan.get('status')=='unsupported':continue
        path=(work/plan['file']).resolve()
        if not path.is_relative_to((work/'data').resolve()) or path.suffix.lower()!='.csv':continue
        identifiers=files.setdefault(path,set())
        if plan.get('id_column'):identifiers.add(plan['id_column'])
        if plan.get('test')=='wilcoxon' and plan.get('wilcoxon_policy')=='exact_no_ties':subsample.add(path)
    changed=False
    for index,(path,identifiers) in enumerate(sorted(files.items())):
        frame=pd.read_csv(path)
        if len(frame)<3 or not identifiers.issubset(frame.columns):continue
        # Draw complete observation records, retaining the destination identifiers.
        # Items, derived totals, category labels and missingness travel together.
        rng=np.random.default_rng(741+index)
        # Do not manufacture ties outside a screened exact-test domain. A private
        # subset changes the empirical distribution and n without duplicating pairs.
        draw=np.sort(rng.choice(len(frame),max(3,int(.8*len(frame))),replace=False)) if path in subsample else rng.integers(0,len(frame),len(frame))
        sampled=frame.iloc[draw].reset_index(drop=True)
        if path not in subsample:
            for name in identifiers:sampled[name]=frame[name].to_numpy()
        sampled.to_csv(path,index=False)
        changed=changed or not sampled.equals(frame)
    return changed
