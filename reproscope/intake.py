"""Create a fresh run corpus with reproducible tabular format conversion.

Original deposits are retained byte-for-byte. Conversion changes container format,
not analytical values, coding, exclusions, or derived variables.
"""
import json
import shutil
from pathlib import Path
import pandas as pd
from . import paths, artifacts


def prepare(source_id: str, run_id: str) -> Path:
    source = paths.manifest(source_id)
    target = paths.corpus_dir(run_id)
    if target.exists() or (paths.ROOT / 'runs' / run_id).exists():
        raise ValueError('fresh intake requires a new corpus and run ID')
    target.mkdir(parents=True)
    (target / 'data').mkdir()
    (target / 'originals').mkdir()
    manifest = source.model_dump(exclude_none=True)
    manifest.update(paper_id=run_id, data_files=[], source_paper_id=source_id)
    manifest.pop('multiverse_policy', None)
    shutil.copy2(source.path(source.pdf), target / 'paper.pdf')
    manifest['pdf'] = 'paper.pdf'
    receipts = []
    labels = {}
    for index, rel in enumerate(source.data_files):
        original = source.path(rel)
        saved = target / 'originals' / f'{index:02d}_{original.name}'
        shutil.copy2(original, saved)
        ext = original.suffix.lower()
        frames = []
        if ext in {'.xls', '.xlsx', '.xlsm'}:
            from .stage0.readiness import _unnamed_fraction, _group_labels
            with pd.ExcelFile(original) as book:
                for sheet in book.sheet_names:
                    frame = book.parse(sheet, header=0)
                    header = 0
                    groups = None
                    if _unnamed_fraction(frame.columns) > .3:
                        groups = _group_labels(frame.columns)
                        frame = book.parse(sheet, header=1)
                        header = 1
                    frames.append((sheet, frame, {'header': header, 'group_labels': groups}))
        elif ext == '.sav':
            import pyreadstat
            frame, meta = pyreadstat.read_sav(str(original))
            frames.append((None, frame, {'column_labels': meta.column_names_to_labels,
                                         'value_labels': meta.variable_value_labels}))
        elif ext == '.dta':
            frames.append((None, pd.read_stata(original, convert_categoricals=False), {}))
        else:
            dest = target / 'data' / original.name
            if dest.exists():raise ValueError('duplicate deposit basename')
            shutil.copy2(original, dest)
            manifest['data_files'].append(str(dest.relative_to(target)))
            receipts.append({'original':rel, 'sha256':artifacts.sha256_file(original),
                             'output':str(dest.relative_to(target)), 'operation':'byte_copy'})
        for sheet_index, (sheet, frame, metadata) in enumerate(frames):
            dest = target / 'data' / f'{original.stem}__{sheet_index}.csv'
            if dest.exists():raise ValueError('duplicate converted basename')
            frame.to_csv(dest, index=False)
            # Verify the entire serialised table, allowing representational numeric roundoff only.
            back = pd.read_csv(dest)
            verify_roundtrip(frame.reset_index(drop=True), back)
            manifest['data_files'].append(str(dest.relative_to(target)))
            labels[dest.name] = metadata
            receipts.append({'original':rel, 'sha256':artifacts.sha256_file(original),
                'sheet':sheet, 'output':str(dest.relative_to(target)), 'metadata':metadata,
                'rows':len(frame), 'columns':list(frame.columns),
                'output_sha256':artifacts.sha256_file(dest), 'roundtrip':'verified',
                'operation':'tabular_container_conversion'})
    if source.codebook:
        shutil.copy2(source.path(source.codebook), target / Path(source.codebook).name)
        manifest['codebook'] = Path(source.codebook).name
    manifest['data_labels'] = labels
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    (target / 'intake_conversion.json').write_text(json.dumps(receipts, indent=2)+'\n')
    return target


def verify_roundtrip(original, converted):
    import math
    if list(original.columns)!=list(converted.columns) or original.shape!=converted.shape:
        raise ValueError('tabular conversion changed shape or columns')
    for a,b in zip(original.to_numpy().flat,converted.to_numpy().flat):
        if pd.isna(a) and pd.isna(b):continue
        if pd.isna(a) or pd.isna(b):raise ValueError('tabular conversion changed missingness')
        if str(a)==str(b):continue
        try:
            if math.isclose(float(a),float(b),rel_tol=1e-12,abs_tol=1e-12):continue
        except (ValueError,TypeError):pass
        raise ValueError('tabular conversion changed a cell')
