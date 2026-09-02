"""Prompt filling that tolerates braces in the substituted material.

`artifacts.load_prompt` rejects any `{{key}}` left after substitution, which is the
right check for a prompt template but fires on an R script or a JSON blob that
happens to contain `{{...}}`. Substituting a sentinel first keeps the check on the
template and lets the payload carry whatever it carries.
"""

from __future__ import annotations

from .. import artifacts


def fill(name: str, **kwargs: object) -> str:
    sentinels = {k: f"\x00SLOT{i}\x00" for i, k in enumerate(kwargs)}
    text = artifacts.load_prompt(name, **sentinels)
    for key, sentinel in sentinels.items():
        text = text.replace(sentinel, str(kwargs[key]))
    return text
