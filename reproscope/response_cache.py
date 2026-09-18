"""Immutable structured-response receipts, separate from local validation.

A cache hit preserves the original ledger identity and never creates a model-call
receipt. Prompt, schema, images and model configuration must all match exactly.
"""
from pathlib import Path
import json
from . import config, provenance, llm


def key(prompt, schema, images, tier, options=None):
    spec=config.tier(tier)
    protocol=llm.ROUTE_PROTOCOL_VERSIONS.get(spec.route)
    return provenance.digest({**({'options': options} if options else {}), **({'route_protocol':protocol} if protocol else {}), 'prompt':prompt, 'schema':schema.model_json_schema(),
                              'images':provenance.files({str(p):p for p in images}),
                              'model':config.tier(tier).model_dump()})


def read(path: Path, fingerprint: str, schema):
    if not path.exists():
        return None
    try:
        record=json.loads(path.read_text())
        if record.get('fingerprint') != fingerprint or not record.get('ledger_id'):
            return None
        if provenance.digest(record['response']) != record.get('response_hash'):
            return None
        return schema.model_validate(record['response']), record['ledger_id']
    except (ValueError, KeyError, TypeError):
        return None


def write(path: Path, fingerprint: str, response, ledger_id: str):
    if not ledger_id:
        return
    payload=response.model_dump()
    record={'fingerprint':fingerprint,'response':payload,'response_hash':provenance.digest(payload),'ledger_id':ledger_id}
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(record,indent=2)+'\n')
    temporary.replace(path)
