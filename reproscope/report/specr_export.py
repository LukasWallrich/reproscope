"""Optional standard R/specr export of the report's verified aggregate results."""
import base64,json,subprocess
from pathlib import Path
from .. import provenance
from .specification import inference_colour


def export(group,folder):
    rows=[]
    for r in group['rows']:
        choices={f['name']:next(l['label'] for l in f['levels'] if l['value']==str(r['spec'][f['name']])) for f in group['chart_factors']}
        rows.append({**{k:r.get(k) for k in ('estimate','ci_lower','ci_upper')},'choices':choices,'colour':inference_colour(r,group['null_value'])})
    payload={'rows':rows,'factors':group['chart_factors'],'reference':group['reported_reference'],'unit':group['metric'],'null':group['null_value']}
    script=Path(__file__).with_name('specr.R');sha=provenance.digest({'payload':payload,'script':script.read_text()})
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);source=folder/(sha+'.json');image=folder/(sha+'.svg')
    source.write_text(json.dumps(payload,indent=2)+'\n')
    if not image.exists():
        p=subprocess.run(['Rscript',str(script),str(source),str(image)],capture_output=True,text=True,timeout=180)
        if p.returncode:raise RuntimeError('specr figure export failed: '+p.stderr[-1500:])
    return 'data:image/svg+xml;base64,'+base64.b64encode(image.read_bytes()).decode()
