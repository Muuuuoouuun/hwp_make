"""Keep original decorative caps fixed while native body paragraphs grow.

Only complete, source-verified single-cell frames with a vertically constant
middle band qualify. Three ordinary table rows hold the original bitmap
pieces; no PDF text is painted into them or moved to individual line boxes.
"""
from copy import deepcopy
import hashlib
import io
import re
import zipfile

import fitz
from lxml import etree
import numpy as np
from PIL import Image

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
HC = '{http://www.hancom.co.kr/hwpml/2011/core}'


def constant_middle_band(payload):
    """Use only an actual run of equal bitmap rows, never guessed text bounds."""
    with Image.open(io.BytesIO(payload)) as image:
        pixels = np.asarray(image.convert('RGB'))
    middle = len(pixels) // 2
    start, end = middle, middle + 1
    while start and np.array_equal(pixels[start - 1], pixels[middle]):
        start -= 1
    while end < len(pixels) and np.array_equal(pixels[end], pixels[middle]):
        end += 1
    if not 0 < start < end < len(pixels) or end - start < len(pixels) * .6:
        return None
    return start, end, len(pixels)


def split_background_frame_rows(source, output, provenance):
    """Return updated source records after creating native fixed cap rows."""
    from .hwpx_writer_v2 import HwpxDocument
    from .pdf_background_geometry import source_flow_background_table
    from .pdf_source_backgrounds import native_background_assets, compose_source_background

    # Plan against the actual saved output and PDF before modifying the file.
    plans = []
    with zipfile.ZipFile(output) as package, fitz.open(source) as pdf:
        header = etree.fromstring(package.read('Contents/header.xml'))
        manifest = etree.fromstring(package.read('Contents/content.hpf'))
        hrefs = {n.get('id'): n.get('href') for n in manifest.iter('{http://www.idpf.org/2007/opf/}item')}
        for part in package.namelist():
            if not re.fullmatch(r'Contents/section\d+\.xml', part):
                continue
            root = etree.fromstring(package.read(part))
            for table in root.iter(HP + 'tbl'):
                cells = table.findall(HP + 'tr/' + HP + 'tc')
                if len(cells) != 1 or not source_flow_background_table(
                    table, root, header, hrefs, package, source, provenance
                ):
                    continue
                assets = native_background_assets(etree.Element(table.tag, attrib=dict(table.attrib)), header, hrefs, package)
                if len(assets) != 1 or (band := constant_middle_band(assets[0][1])) is None:
                    continue
                records = [p for p in provenance if p.get('sha256') == assets[0][0] and p.get('role') == 'source_background_frame']
                if len(records) != 1:
                    continue
                record = records[0]
                height = int(table.find(HP + 'sz').get('height'))
                start, end, pixels = band
                boundaries = [0, round(start * height / pixels), round(end * height / pixels), height]
                caps = boundaries[1], height - boundaries[2]
                margins = cells[0].find(HP + 'cellMargin')
                paragraphs = cells[0].findall(HP + 'subList/' + HP + 'p')
                if not paragraphs or any(p.find(HP + 'linesegarray') is None for p in paragraphs):
                    continue
                last_lines = paragraphs[-1].findall(HP + 'linesegarray/' + HP + 'lineseg')
                if not last_lines:
                    continue
                trim = max(0, caps[1] - int(margins.get('bottom', '0')))
                if (min(caps) < 300 or caps[0] > int(margins.get('top', '0'))
                    or trim > int(last_lines[-1].get('spacing', '0'))):
                    continue
                page = pdf[int(record['page']) - 1]
                x, y, width, span = map(float, record['bbox_px'])
                region_bounds = [y, y + span * start / pixels, y + span * end / pixels, y + span]
                pieces = []
                blocks = page.get_text('dict').get('blocks', [])
                for index, (a, b) in enumerate(zip(region_bounds, region_bounds[1:])):
                    region = fitz.Rect(x, a, x + width, b)
                    numbers = [block['number'] for block in blocks if block.get('type') == 1
                               and block['number'] in record['source_image_numbers']
                               and not (fitz.Rect(block['bbox']) & region).is_empty]
                    data = compose_source_background(page, region, numbers)
                    pieces.append((data, {**record, 'sha256': hashlib.sha256(data).hexdigest(),
                                          'bbox_px': [x, a, width, b - a], 'source_image_numbers': numbers}))
                plans.append((part, table.get('id'), record, boundaries, trim, pieces))
    if not plans:
        return provenance, {'applied': 0}

    doc = HwpxDocument.open(output)
    header = doc.headers[0].element
    fills = header.find('.//' + HH + 'borderFills')
    paras = header.find('.//' + HH + 'paraProperties')
    chars = header.find('.//' + HH + 'charProperties')
    # Empty cap cells carry decoration, not hidden text. Give their required
    # empty paragraph a small ordinary style that fits the measured cap.
    para_id = str(max(int(p.get('id')) for p in paras) + 1)
    char_id = str(max(int(p.get('id')) for p in chars) + 1)
    style = deepcopy(paras[0]); style.set('id', para_id)
    for node in style.iter():
        if etree.QName(node).localname in ('prev', 'next', 'left', 'right', 'intent'):
            node.set('value', '0')
        if etree.QName(node).localname == 'lineSpacing':
            node.set('type', 'FIXED'); node.set('value', '100')
    char = deepcopy(chars[0]); char.set('id', char_id); char.set('height', '100')
    paras.append(style); paras.set('itemCnt', str(len(paras)))
    chars.append(char); chars.set('itemCnt', str(len(chars)))
    used_ids = {node.get('id') for section in doc.sections for node in section.element.iter()}
    next_id = 1
    updated = list(provenance)
    for part, table_id, record, boundaries, trim, pieces in plans:
        section = doc.sections[int(re.search(r'(\d+)\.xml$', part).group(1))]
        table = next(t for t in section.element.iter(HP + 'tbl') if t.get('id') == table_id)
        row = table.find(HP + 'tr'); original = deepcopy(row.find(HP + 'tc'))
        fill = next(f for f in fills if f.get('id') == table.get('borderFillIDRef'))
        table.set('borderFillIDRef', original.get('borderFillIDRef'))
        table.set('rowCnt', '3'); table.remove(row)
        for index, (data, _) in enumerate(pieces):
            cap_fill = deepcopy(fill)
            fill_id = str(max(int(f.get('id')) for f in fills) + 1)
            cap_fill.set('id', fill_id)
            cap_fill.find('.//' + HC + 'img').set('binaryItemIDRef', doc.add_image(data, 'png'))
            fills.append(cap_fill)
            cell = deepcopy(original); cell.set('borderFillIDRef', fill_id)
            cell.find(HP + 'cellAddr').set('rowAddr', str(index))
            cell.find(HP + 'cellSz').set('height', str(boundaries[index + 1] - boundaries[index]))
            margin = cell.find(HP + 'cellMargin'); sub = cell.find(HP + 'subList')
            if index == 1:
                margin.set('top', str(int(margin.get('top')) - boundaries[1]))
                margin.set('bottom', str(max(0, int(margin.get('bottom')) - (boundaries[3] - boundaries[2]))))
                # This is trailing space after the final line, not a baseline
                # or line-height change. Edited text recomputes ordinary flow.
                if trim:
                    line = sub.findall(HP + 'p')[-1].findall(HP + 'linesegarray/' + HP + 'lineseg')[-1]
                    line.set('spacing', str(int(line.get('spacing')) - trim))
            else:
                for side in ('left', 'right', 'top', 'bottom'):
                    margin.set(side, '0')
                for node in list(sub): sub.remove(node)
                while str(next_id) in used_ids: next_id += 1
                used_ids.add(str(next_id))
                p = etree.SubElement(sub, HP + 'p', id=str(next_id), paraPrIDRef=para_id,
                                     styleIDRef='0', pageBreak='0', columnBreak='0', merged='0')
                etree.SubElement(etree.SubElement(p, HP + 'run', charPrIDRef=char_id), HP + 't')
                cache = etree.SubElement(p, HP + 'linesegarray')
                etree.SubElement(cache, HP + 'lineseg', textpos='0', vertpos='0', vertsize='100',
                                 textheight='100', baseline='85', spacing='0', horzpos='0',
                                 horzsize=cell.find(HP + 'cellSz').get('width'), flags='393216')
            etree.SubElement(table, HP + 'tr').append(cell)
        section.mark_dirty()
        section._preserve_question_layout_caches = True
        position = updated.index(record)
        updated[position:position + 1] = [p for _, p in pieces]
    fills.set('itemCnt', str(len(fills)))
    doc.headers[0].mark_dirty()
    doc.save(output)
    return updated, {'applied': len(plans), 'native_rows_per_frame': 3}
