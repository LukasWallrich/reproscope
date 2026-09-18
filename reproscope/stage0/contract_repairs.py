"""Bounded patches for invalid contracts; unchanged methods are not regenerated."""
from pydantic import BaseModel, ConfigDict
from ..source_mapping import TermMapping, UnassignedClaim, mapping_key
from .contracts import SlimContract, ContractsAndMethods


class TermKey(BaseModel):
    model_config=ConfigDict(extra='forbid')
    field: str
    study_id: str
    source_text: str
    claim_ids: list[str] = []


class ContractRepair(BaseModel):
    model_config=ConfigDict(extra='forbid')
    contracts: list[SlimContract]=[]
    remove_contract_ids: list[str]=[]
    term_map: list[TermMapping]=[]
    remove_term_map: list[TermKey]=[]
    unassigned: list[UnassignedClaim]=[]
    remove_unassigned_ids: list[str]=[]
    redacted_methods: str | None=None


def _apply(current, replacements, removals, key):
    original={key(item):item for item in current}
    if len(original)!=len(current):
        raise ValueError('Cannot patch a collection with duplicate identities')
    keys=[key(item) for item in replacements]
    if len(keys)!=len(set(keys)) or len(removals)!=len(set(removals)) or set(keys)&set(removals):
        raise ValueError('Duplicate or contradictory repair operations')
    unknown=set(removals)-set(original)
    if unknown:raise ValueError(f'Repair removes unknown identities: {unknown}')
    for item in removals:original.pop(item)
    for item in replacements:original[key(item)]=item
    return list(original.values())


def apply(current: ContractsAndMethods, patch: ContractRepair):
    revised = ContractsAndMethods(
        contracts=_apply(current.contracts,patch.contracts,patch.remove_contract_ids,lambda c:c.analysis_id),
        term_map=_apply(current.term_map,patch.term_map,[mapping_key(k) for k in patch.remove_term_map],mapping_key),
        unassigned=_apply(current.unassigned,patch.unassigned,patch.remove_unassigned_ids,lambda c:c.claim_id),
        redacted_methods=current.redacted_methods if patch.redacted_methods is None else patch.redacted_methods,
    )
    before = {cid for contract in current.contracts for cid in contract.claim_ids}
    after = ({cid for contract in revised.contracts for cid in contract.claim_ids}
             | {item.claim_id for item in revised.unassigned})
    if lost := before - after:
        raise ValueError('Repair drops source assignments without replacement or disposition: ' + ', '.join(sorted(lost)))
    return revised
