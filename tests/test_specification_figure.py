import xml.etree.ElementTree as ET
from reproscope.report.specification import reported_position,specification_curve_svg,inference_colour


def test_rounding_position_and_scale_identity():
    g={'name':'pearson','metric':'r','rows':[{'estimate':v} for v in [-.516,-.514,-.513,-.48]]}
    ref={'value':-.51,'precision':2,'metric':'r','effect_group':'pearson','claim_id':'c1'}
    got=reported_position(g,ref)
    assert (got['below'],got['tied'],got['above'])==(1,2,1)
    assert (got['rank_low'],got['rank_high'])==(2,3)
    assert not reported_position({**g,'name':'rank'},ref)['available']
    assert not reported_position({**g,'metric':'d'},ref)['available']
    assert reported_position({**g,'rows':[{'estimate':0}]},{**ref,'value':0})['available']


def test_choice_columns_align_with_sorted_estimates_and_reference_survives():
    rows=[{'spec_id':'s2','estimate':2.,'ci_lower':1.,'ci_upper':3.,'p':.1,'spec':{'method':'B'}},
          {'spec_id':'s1','estimate':1.,'ci_lower':.5,'ci_upper':2.,'p':.01,'spec':{'method':'A'}}]
    g={'name':'raw','metric':'mean_difference','label':'Outcome <contrast>','null_value':0,'rows':rows,
       'chart_factors':[{'name':'method','label':'Method','levels':[{'value':'A','label':'A'},{'value':'B','label':'B'}]}]}
    g['reported_reference']=reported_position(g,{'value':1.5,'metric':g['metric'],'effect_group':'raw','precision':1})
    root=ET.fromstring(specification_curve_svg(g));ns={'s':'http://www.w3.org/2000/svg'}
    columns=root.findall("s:g[@class='spec-column']",ns)
    assert [c.attrib['data-index'] for c in columns]==['1','0']
    for c in columns:
        dot=c.find('s:circle',ns);marks=c.findall("s:line[@data-choice='method']",ns)
        assert len(marks)==1 and marks[0].attrib['x1']==dot.attrib['cx']
    assert root.find("s:line[@class='reported-reference']",ns) is not None
    assert inference_colour(rows[0],0)=='#767676'  # CI excludes zero, declared p does not meet criterion.
