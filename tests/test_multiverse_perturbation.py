import json
import pandas as pd
from reproscope.multiverse_perturbation import resample_records


def test_record_perturbation_preserves_identifiers_and_derived_totals(tmp_path):
    (tmp_path/'out').mkdir();(tmp_path/'data').mkdir()
    frame=pd.DataFrame({'id':range(20),'item_a':range(20),'item_b':[x*x for x in range(20)]})
    frame['total']=frame.item_a+frame.item_b
    frame.to_csv(tmp_path/'data/input.csv',index=False)
    plan={'specs':[{'file':'data/input.csv','id_column':'id','x':'total'}]}
    (tmp_path/'out/analysis_plan.json').write_text(json.dumps(plan))
    assert resample_records(tmp_path)
    changed=pd.read_csv(tmp_path/'data/input.csv')
    assert changed.id.tolist()==frame.id.tolist()
    assert (changed.total==changed.item_a+changed.item_b).all()
    assert changed.total.mean()!=frame.total.mean()
    assert set(changed.item_a).issubset(set(frame.item_a))


def test_exact_signed_rank_perturbation_preserves_untied_domain(tmp_path):
    (tmp_path/'data').mkdir()
    frame=pd.DataFrame({'id':range(20),'a':range(1,21),'b':[0]*20})
    frame.to_csv(tmp_path/'data/input.csv',index=False)
    recipes=[{'file':'data/input.csv','id_column':'id','test':'wilcoxon','wilcoxon_policy':'exact_no_ties'}]
    assert resample_records(tmp_path,recipes=recipes)
    changed=pd.read_csv(tmp_path/'data/input.csv')
    assert len(changed)==16 and changed.id.is_unique
    assert (changed.a-changed.b).abs().is_unique
    assert changed.a.tolist()==frame.set_index('id').loc[changed.id,'a'].tolist()
