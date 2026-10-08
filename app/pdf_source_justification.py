"""Recover paragraph justification only from complete, actual PDF evidence."""
from __future__ import annotations

import math
from statistics import median

import fitz


def _vector(value, count):
    if len(value) != count or not all(math.isfinite(float(v)) for v in value):
        raise ValueError('invalid source justification coordinates')
    return tuple(float(v) for v in value)


def _box(value):
    result = fitz.Rect(_vector(value,4))
    if result.is_empty or result.is_infinite:
        raise ValueError('empty source justification bounds')
    return result


def _actual_rows(layout):
    """Return original rows only after every supplied raw span agrees exactly."""
    from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font
    from .pdf_wrapped_prose_frames import _source_proof

    proof = _source_proof(layout)
    if proof is None:
        return None
    geometry, frame, records, _, source_width = proof
    supplied_width = float(layout['source_page_width_pt'])
    if not math.isfinite(supplied_width) or supplied_width != source_width:
        return None
    with fitz.open(geometry['source_pdf_path']) as document:
        page = document[int(geometry['source_page_index'])]
        raw_rows = sorted((row for block in page.get_text('rawdict')['blocks']
            for row in block.get('lines',[]) if frame.contains(_box(row['bbox']))),
            key=lambda row:(row['bbox'][1],row['bbox'][0]))
        if len(records) != len(raw_rows):
            return None
        for raw, record in zip(raw_rows,records):
            if (_vector(record['bbox_pt'],4) != _vector(raw['bbox'],4)
                or len(record.get('spans') or []) != len(raw['spans'])):
                return None
            text = ''.join(char['c'] for span in raw['spans'] for char in span['chars'])
            if record['text'] != _pdf_output_text(text).strip():
                return None
            for actual, supplied in zip(raw['spans'],record['spans']):
                size, flags = float(supplied['size']), float(supplied['flags'])
                if (not math.isfinite(size+flags) or size <= 0 or flags != round(flags)
                    or size != actual['size'] or flags != actual['flags']
                    or supplied['font'] != actual['font'] or is_hancom_eq_font(actual['font'])
                    or _vector(supplied['bbox'],4) != _vector(actual['bbox'],4)
                    or _vector(supplied['origin'],2) != _vector(actual['origin'],2)
                    or len(supplied.get('chars') or []) != len(actual['chars'])
                    or supplied['text'] != ''.join(char['c'] for char in actual['chars'])):
                    return None
                for original, given in zip(actual['chars'],supplied['chars']):
                    if (given['c'] != original['c']
                        or _vector(given['origin'],2) != _vector(original['origin'],2)
                        or _vector(given['bbox'],4) != _vector(original['bbox'],4)):
                        return None
        return frame,records,raw_rows,source_width


def _spaces(row):
    atoms=[]
    for span in row['spans']:
        key=(span['font'],float(span['size']),int(span['flags']))
        atoms.extend((char,key) for char in span['chars'])
    ink=[i for i,(char,_) in enumerate(atoms) if not char['c'].isspace()]
    if not ink:
        return None
    for index in range(ink[0]+1,ink[-1]):
        char=atoms[index][0]['c']
        if char.isspace() and (char != ' ' or atoms[index-1][0]['c'].isspace()
                              or atoms[index+1][0]['c'].isspace()):
            return None
    result={}
    for index in range(1,len(atoms)-1):
        previous,pk=atoms[index-1];space,key=atoms[index];following,nk=atoms[index+1]
        if (space['c'] != ' ' or previous['c'].isspace() or following['c'].isspace()
            or pk != key or nk != key):
            continue
        advance=following['origin'][0]-space['origin'][0]
        width=space['bbox'][2]-space['bbox'][0]
        if min(advance,width) <= 0 or space['origin'][1] != following['origin'][1]:
            continue
        result.setdefault(key,[]).append((advance,width))
    return result


def source_justification(layout, rows, *, available_width_hwp, source_left_pt, page_width_hwp):
    """Return JUSTIFY/right margin for a proved semantic paragraph, else None.

    The caller already matches one complete native semantic paragraph to these
    consecutive source records. This function changes neither XML nor text.
    It reopens the PDF and uses actual raw glyphs, never supplied coordinates,
    to prove several consistently expanded interior spaces against the final
    row in the same face/size. Field names, colons and producer flags grant no
    exception. Width is the cell's usable interval before paragraph margins;
    source_left_pt is its original text rail.
    """
    try:
        if len(rows) < 2:
            return None
        width,left,page_width=map(float,(available_width_hwp,source_left_pt,page_width_hwp))
        if not all(math.isfinite(v) for v in (width,left,page_width)) or min(width,page_width) <= 0:
            return None
        evidence=_actual_rows(layout)
        if evidence is None:
            return None
        frame,records,actual,source_width=evidence
        starts=[i for i in range(len(records)-len(rows)+1) if rows == records[i:i+len(rows)]]
        if len(starts) != 1:
            return None
        selected=actual[starts[0]:starts[0]+len(rows)]
        scale=page_width/source_width
        rail=min(_box(record['bbox_pt']).x0 for record in records)
        if left != rail or not frame.x0 <= left < left+width/scale <= frame.x1+1/scale:
            return None
        if any(a['spans'][0]['origin'][1] >= b['spans'][0]['origin'][1]
               for a,b in zip(selected,selected[1:])):
            return None
        samples=[_spaces(row) for row in selected]
        if any(sample is None for sample in samples):
            return None
        common=set(samples[0]).intersection(*(set(sample) for sample in samples[1:]))
        common={key for key in common if all(len(sample[key]) >= 3 for sample in samples)}
        if len(common) != 1:
            return None
        key=common.pop()
        # MuPDF exposes float32 PDF coordinates. Bound comparison noise by
        # eight float32 units or one native output coordinate, whichever is
        # larger; actual final-row variation supplies the natural range.
        largest=max(abs(float(v)) for row in selected for span in row['spans']
                    for char in span['chars'] for v in (*char['origin'],*char['bbox']))
        uncertainty=max(1/scale,8*2.0**(math.frexp(max(largest,1.0))[1]-24))
        widths=[value[1] for sample in samples for value in sample[key]]
        if max(widths)-min(widths) > uncertainty:
            return None
        final=[value[0] for value in samples[-1][key]]
        spread=max(final)-min(final)
        for sample in samples[:-1]:
            advances=[value[0] for value in sample[key]]
            if (min(advances) <= max(final)+uncertainty
                or max(advances)-min(advances) > spread+2*uncertainty):
                return None
        ink=[max(char['bbox'][2] for span in row['spans'] for char in span['chars']
                 if not char['c'].isspace()) for row in selected]
        margins=[width-(right-left)*scale for right in ink[:-1]]
        if (min(margins) < 0 or max(margins) >= width
            or max(round(v) for v in margins)-min(round(v) for v in margins) > 1
            or ink[-1] > max(ink[:-1])+1/scale):
            return None
        return {'alignment':'JUSTIFY','right_hwp':round(median(margins))}
    except (ValueError,TypeError,AttributeError,KeyError,IndexError,OverflowError,OSError,
            fitz.FileNotFoundError,fitz.FileDataError,fitz.EmptyFileError):
        return None
