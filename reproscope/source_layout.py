"""Physical PDF word locations and numeric candidates, without result interpretation.

The text layer supplies coordinates and literal tokens, not ground truth for
damaged glyphs or image-only quantities. Readers can identify missing candidates.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

VERSION = "physical-source-3"
NUMBER_WORDS = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split(), range(21)))
NUMBER_TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(),range(20,100,10)))

def number_word(literal):
    word=literal.casefold().strip(',.;:')
    if word in NUMBER_WORDS:return NUMBER_WORDS[word]
    parts=re.split('[-–]',word)
    if len(parts)==2 and parts[0] in NUMBER_TENS and parts[1] in NUMBER_WORDS and 0<NUMBER_WORDS[parts[1]]<10:return NUMBER_TENS[parts[0]]+NUMBER_WORDS[parts[1]]
    return NUMBER_TENS.get(word)

NUMBER = re.compile(r"(?<![\w.])[-−+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?(?![\w.]\d)")


def parse_bbox(xml: str, pdf_sha256: str) -> dict:
    # XML 1.0 cannot represent these damaged text-layer glyphs. Keep their
    # positions as replacement characters; never reinterpret them as symbols.
    controls = sorted({f"U+{ord(c):04X}" for c in xml if ord(c) < 32 and c not in "\t\n\r"})
    xml = "".join(c if ord(c) >= 32 or c in "\t\n\r" else "\ufffd" for c in xml)
    root = ET.fromstring(xml)
    pages = []
    for page_no, page in enumerate(root.findall(".//{*}page"), 1):
        width, height = float(page.attrib["width"]), float(page.attrib["height"])
        words, candidates, markers = [], [], []
        previous_context=''
        for line_no, line in enumerate(page.findall(".//{*}line"), 1):
            elements = line.findall("{*}word")
            context = " ".join("".join(w.itertext()) for w in elements)
            for word_index, word in enumerate(elements):
                literal = "".join(word.itertext())
                bbox = [float(word.attrib[k]) for k in ("xMin", "yMin", "xMax", "yMax")]
                identity = {"pdf": pdf_sha256, "page": page_no, "bbox": bbox}
                import json
                word_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
                record = {"word_id": word_id, "text": literal, "bbox": bbox,
                          "line": line_no, "context": context}
                words.append(record)
                preceding = " ".join("".join(w.itertext()) for w in elements[:word_index])
                if re.fullmatch(r"\*{1,4}|†{1,2}|‡", literal):
                    markers.append({"source_token_id": f"p{page_no:03d}:{word_id}:marker",
                                    "word_id": word_id, "literal": literal, "bbox": bbox, "context": context})
                if number_word(literal) is not None:
                    candidates.append({"source_token_id": f"p{page_no:03d}:{word_id}:word",
                        "word_id": word_id, "literal": literal, "word_text": literal,
                        "bbox": bbox, "context": context, "prefix": preceding + " ",
                        "value": number_word(literal), "precision": 0,
                        "number_word": True})
                for part, match in enumerate(NUMBER.finditer(literal)):
                    candidates.append({"source_token_id": f"p{page_no:03d}:{word_id}:{part}",
                        "word_id": word_id, "literal": match.group(), "word_text": literal,
                        "bbox": bbox, "context": context,
                        "prefix": previous_context + " " + preceding + " " + literal[:match.start()],
                        "value": float(match.group().replace("−", "-")),
                        "precision": len(match.group().partition(".")[2].split("e")[0].split("E")[0])})
            previous_context=context
        pages.append({"page": page_no, "width": width, "height": height,
                      "words": words, "numeric_candidates": candidates, "marker_candidates": markers})
    return {"version": VERSION, "pdf_sha256": pdf_sha256, "pages": pages,
            "damaged_control_glyphs": controls,
            "scope": "physical native-text locations; numeric candidates include design, axes, citations and equations; not an inventory of statistical results"}


def build(pdf: Path) -> dict:
    pdf = Path(pdf)
    result = subprocess.run(["pdftotext", "-bbox-layout", str(pdf), "-"],
                            capture_output=True, text=True, check=True, timeout=60)
    return parse_bbox(result.stdout, hashlib.sha256(pdf.read_bytes()).hexdigest())


def prompt_page(page: dict) -> str:
    """Candidate identifiers supplement the image; readers still inspect all regions."""
    return "\n".join(f'{c["source_token_id"]} | {c.get("word_text", c["literal"])} | '
                     f'box={c["bbox"]} | {c["context"]}'
                     for c in page["numeric_candidates"] + page.get("marker_candidates", []))


def index(layout: dict) -> dict:
    return {c["source_token_id"]: {**c, "page": p["page"],
            "kind": "marker" if c["source_token_id"].endswith(":marker") else "number"}
            for p in layout["pages"] for c in p["numeric_candidates"] + p.get("marker_candidates", [])}
