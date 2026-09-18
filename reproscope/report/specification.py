"""Aligned estimate/interval and analytical-choice panels, following specr's layout."""
from html import escape
import math
import textwrap


def reported_position(group, reference):
    """Compare only the explicitly matched effect group, at reported precision."""
    value=reference.get('value')
    if value is None or reference.get('metric')!=group['metric'] or reference.get('effect_group')!=group['name']:
        return {'available':False,'note':'No directly reported estimate is available on this effect scale and comparison.'}
    precision=reference.get('precision')
    at=(lambda v:round(v,precision)) if precision is not None else (lambda v:v)
    values=[r['estimate'] for r in group['rows']]
    below=sum(at(v)<at(value) for v in values);above=sum(at(v)>at(value) for v in values);ties=len(values)-below-above
    half=.5*10**(-precision) if precision is not None else None
    return {'available':True,'value':value,'claim_id':reference.get('claim_id'),'precision':precision,
        'n':len(values),'below':below,'above':above,'tied':ties,'rank_low':below+1,'rank_high':below+ties,
        'rounding_low':value-half if half is not None else None,'rounding_high':value+half if half is not None else None}


def inference_colour(row,null):
    p=row.get('p');alpha=row.get('p_threshold') or .05
    try:significant=p is not None and float(p)<float(alpha)
    except (ValueError,TypeError):significant=False
    return '#b52d47' if significant and row['estimate']<null else '#246ba0' if significant and row['estimate']>null else '#767676'


def specification_curve_svg(group):
    rows=sorted(enumerate(group['rows']),key=lambda ir:(ir[1]['estimate'],ir[0]))
    if not rows:return ''
    factors=group.get('chart_factors',[]);ref=group.get('reported_reference',{})
    w=max(940,330+len(rows)*10);ml=310;right=w-24;top=54;bottom=330
    levels=[];cursor=402
    for factor in factors:
        wrapped=textwrap.wrap(factor['label'],36) or ['Analytical choice']
        heading_y=cursor;cursor+=len(wrapped)*16+10
        entries=[]
        for level in factor['levels']:
            lines=textwrap.wrap(level['label'],37) or ['Unlabelled level'];height=max(25,len(lines)*16+8)
            entries.append({**level,'y':cursor+height/2,'lines':lines});cursor+=height
        levels.append((factor,heading_y,wrapped,entries));cursor+=14
    h=cursor+50 if factors else 420
    vals=[v for _,r in rows for v in (r['estimate'],r.get('ci_lower'),r.get('ci_upper')) if isinstance(v,(float,int)) and math.isfinite(v)]
    if ref.get('available'):vals += [ref['value']] + ([ref['rounding_low'],ref['rounding_high']] if ref.get('rounding_low') is not None else [])
    lo,hi=min(vals),max(vals);pad=(hi-lo or 1)*.12;lo-=pad;hi+=pad
    x=lambda j:ml+(j+.5)*(right-ml)/len(rows)
    y=lambda v:top+(hi-v)/(hi-lo)*(bottom-top)
    out=[f'<svg class="specification-figure" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" style="min-width:{w}px" role="img" aria-label="{escape(group["label"],quote=True)}: specification curve and aligned analytical choices">',f'<rect width="{w}" height="{h}" fill="white"/>']
    def text(xx,yy,value,**attrs):
        extra=' '.join(f'{k.rstrip("_").replace("_","-")}="{escape(str(v),quote=True)}"' for k,v in attrs.items())
        out.append(f'<text x="{xx:.2f}" y="{yy:.2f}" font-family="Arial,sans-serif" font-size="14" fill="#172e47" {extra}>{escape(str(value))}</text>')
    def line(x1,y1,x2,y2,colour='#e0e4e8',**attrs):
        extra=' '.join(f'{k.rstrip("_").replace("_","-")}="{v}"' for k,v in attrs.items());out.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{colour}" {extra}/>')
    text(12,27,'A  Estimates and confidence intervals',font_weight='bold')
    for j in range(5):
        v=lo+(hi-lo)*j/4;line(ml,y(v),right,y(v));text(ml-12,y(v)+5,f'{v:.3g}',text_anchor='end')
    if lo<=group['null_value']<=hi:line(ml,y(group['null_value']),right,y(group['null_value']),'#767676',stroke_dasharray='3 4')
    if ref.get('available'):
        if ref.get('rounding_low') is not None:
            out.append(f'<rect class="reported-rounding-band" x="{ml}" y="{y(ref["rounding_high"]):.2f}" width="{right-ml}" height="{y(ref["rounding_low"])-y(ref["rounding_high"]):.2f}" fill="#ad6500" opacity=".1"/>')
        line(ml,y(ref['value']),right,y(ref['value']),'#ad6500',stroke_width=2,stroke_dasharray='6 4',class_='reported-reference')
        text(right,43,f'Paper reports {ref["value"]:g} (dashed line)',text_anchor='end')
    tick_ranks=sorted({0,len(rows)-1,*[round((len(rows)-1)*i/4) for i in range(5)]})
    for j in tick_ranks:
        line(x(j),top,x(j),bottom,'#edf0f3');text(x(j),bottom+25,j+1,text_anchor='middle')
    text((ml+right)/2,bottom+49,'Specification rank (lowest to highest estimate)',text_anchor='middle')
    # One shared x coordinate for the estimate and every choice belonging to it.
    for j,(index,row) in enumerate(rows):
        xx=x(j);colour=inference_colour(row,group['null_value']);sid=escape(str(row.get('spec_id',index)),quote=True)
        out.append(f'<g class="spec-column" data-index="{index}" tabindex="0" role="button" aria-label="Inspect {sid}, rank {j+1}, estimate {row["estimate"]:.5g}"><title>{sid}: rank {j+1}, estimate {row["estimate"]:.5g}</title>')
        out.append(f'<rect class="selection-column" x="{xx-4:.2f}" y="{top}" width="8" height="{h-top-45}" fill="#172e47" opacity="0"/>')
        a,b=row.get('ci_lower'),row.get('ci_upper')
        if a is not None and b is not None:line(xx,y(a),xx,y(b),colour,opacity='.5',stroke_width='1.5')
        out.append(f'<circle class="estimate-point" cx="{xx:.2f}" cy="{y(row["estimate"]):.2f}" r="4" fill="{colour}"/>')
        for factor,_,_,entries in levels:
            for e in entries:
                if str(row.get('spec',{}).get(factor['name'],''))==e['value']:line(xx,e['y']-7,xx,e['y']+7,colour,stroke_width=2,**{'data-choice':escape(factor['name'],quote=True)})
        out.append('</g>')
    if factors:text(12,385,'B  Analytical choices',font_weight='bold')
    else:text(12,390,'No analytical choice varies within this effect group.')
    for factor,heading_y,heading,entries in levels:
        for i,t in enumerate(heading):text(12,heading_y+i*16,t,font_weight='bold')
        for e in entries:
            line(ml,e['y'],right,e['y'],'#edf0f3')
            for i,t in enumerate(e['lines']):text(ml-14,e['y']+5+(i-(len(e['lines'])-1)/2)*16,t,text_anchor='end')
    if factors:
        for j in tick_ranks:text(x(j),h-25,j+1,text_anchor='middle')
    out.append('</svg>')
    return ''.join(out)
