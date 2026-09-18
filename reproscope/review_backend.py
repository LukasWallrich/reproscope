"""Explicit alternate subscription backend for unblinded review calls only."""
import os
from . import config,llm,provenance


def fingerprint():
    selected=os.environ.get('REPROSCOPE_REVIEW_BACKEND','default')
    if selected not in {'default','strong_alt'}:
        raise ValueError('review backend must be default or strong_alt')
    return provenance.digest({'selection':selected,'alternate':config.tier('strong_alt').model_dump() if selected=='strong_alt' else None})


def call(*args,**kwargs):
    fingerprint()
    if os.environ.get('REPROSCOPE_REVIEW_BACKEND')=='strong_alt':
        stage=kwargs.get('stage')
        stage1_review=stage=='1' and args and args[0] in {'hardcoding_audit','targeted_hardcoding_audit','fix_severity','diagnose'}
        if (stage not in {'2','3'} and not stage1_review) or kwargs.get('agentic') or kwargs.get('images'):
            raise ValueError('alternate review backend is restricted to unblinded non-agentic review')
        spec=config.tier('strong_alt')
        requested=kwargs.pop('tier',None)
        kwargs.update(route=spec.route,model=spec.model,
            extra={**(kwargs.get('extra') or {}),'review_backend':'strong_alt','requested_tier':requested})
    return llm.call(*args,**kwargs)
