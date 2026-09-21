"""Refresh native tab caches from shaped glyph advances, retaining tab stops.

PDF glyph metrics and the installed HWP font shaper can differ. Copying only
the PDF's blank gap accumulates that difference across a choice row. A small
in-memory HWPX probe measures the actual runs, including native equations;
only the cached tab gaps change. The paragraph and native tab stops survive.
"""
from copy import deepcopy
import io
import re
import zipfile

from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
SVG = "{http://www.w3.org/2000/svg}"
MARKERS = '①②③④⑤'


def refresh_choice_tab_widths(path):
    from .hwpx_writer_v2 import HwpxDocument  # registers the bundled hwpx package
    from hwpx.tools.paragraph_spacing import paragraph_tab_stops, paragraph_indentation
    from .pdf_question_rendering import _transform, _multiply, IDENTITY
    import rhwp

    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        payloads = {info.filename: archive.read(info.filename) for info in infos}
    header = etree.fromstring(payloads['Contents/header.xml'])
    styles = {p.get('id'): p for p in header.iter(HH+'paraPr')}
    roots, candidates = {}, []
    for filename, payload in payloads.items():
        if not re.fullmatch(r'Contents/section\d+\.xml', filename):
            continue
        root = etree.fromstring(payload)
        roots[filename] = root
        for paragraph in root.iter(HP+'p'):
            tabs = paragraph.findall(HP+'run/'+HP+'tab')
            cache = paragraph.find(HP+'linesegarray')
            stops = paragraph_tab_stops(paragraph, styles)
            children = [c for r in paragraph.findall(HP+'run') for c in r]
            text = ''.join(t.text or '' for t in paragraph.findall(HP+'run/'+HP+'t'))
            labels = re.findall('[①-⑤]', text)
            if (not tabs or len(tabs) != len(stops) or len(labels) != len(tabs)+1
                or not 2 <= len(labels) <= 5 or ''.join(labels) not in MARKERS
                or not text.lstrip().startswith(labels[0]) or cache is None or len(cache) != 1
                or any(c.tag not in {HP+'t', HP+'tab', HP+'equation'}
                       or (c.tag == HP+'t' and len(c)) for c in children)):
                continue
            left, _, indent = paragraph_indentation(paragraph, styles)
            if indent:
                continue
            candidates.append((filename, paragraph, tabs, [left, *stops], labels))
    evidence = {'measured_rows': 0, 'updated_rows': 0, 'unmeasured_rows': 0}
    if not candidates:
        return evidence
    # Use the document's real fonts/styles, but give each measured paragraph
    # a page of its own. Header/footer/question geometry cannot contaminate
    # measurements or require matching identical choice text in the body.
    first = next(iter(roots.values()))
    probe = etree.Element(first.tag, nsmap=first.nsmap)
    secpr = deepcopy(first.find('.//'+HP+'secPr'))
    for child in list(secpr):
        if etree.QName(child).localname in {'header', 'footer', 'headerApply', 'footerApply', 'masterPage'}:
            secpr.remove(child)
    page = secpr.find(HP+'pagePr')
    margin = page.find(HP+'margin')
    for key in ('top', 'bottom', 'left', 'right'):
        margin.set(key, '1000')
    margin.set('header', '0'); margin.set('footer', '0'); margin.set('gutter', '0')
    for index, (_, original, _, _, _) in enumerate(candidates):
        paragraph = deepcopy(original)
        paragraph.set('pageBreak', '1' if index else '0')
        paragraph.set('columnBreak', '0')
        cache = paragraph.find(HP+'linesegarray')[0]
        cache.set('vertpos', '0')
        if not index:
            run = paragraph.find(HP+'run')
            run.insert(0, secpr)
            ctrl = etree.Element(HP+'ctrl')
            etree.SubElement(ctrl, HP+'colPr', id='0', type='NEWSPAPER', layout='LEFT',
                             colCount='1', sameSz='1', sameGap='0')
            run.insert(1, ctrl)
        probe.append(paragraph)
    probe_payloads = dict(payloads)
    probe_header = deepcopy(header)
    probe_header.set('secCnt', '1')
    probe_payloads['Contents/header.xml'] = etree.tostring(probe_header)
    probe_payloads['Contents/section0.xml'] = etree.tostring(probe)
    manifest = etree.fromstring(payloads['Contents/content.hpf'])
    opf = '{' + etree.QName(manifest).namespace + '}'
    removed = set()
    for item in list(manifest.find(opf+'manifest')):
        if re.fullmatch(r'(?:Contents/)?section[1-9]\d*\.xml', item.get('href', '')):
            removed.add(item.get('id'))
            item.getparent().remove(item)
    for item in list(manifest.find(opf+'spine')):
        if item.get('idref') in removed:
            item.getparent().remove(item)
    probe_payloads['Contents/content.hpf'] = etree.tostring(manifest)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for filename, payload in probe_payloads.items():
            if filename in roots and filename != 'Contents/section0.xml':
                continue
            archive.writestr(filename, payload)
    document = rhwp.Document.from_bytes(buffer.getvalue())
    if document.page_count != len(candidates):
        evidence['unmeasured_rows'] = len(candidates)
        return evidence
    changed = set()
    for index, (filename, paragraph, tabs, stops, labels) in enumerate(candidates):
        svg = etree.fromstring(document.render_svg(index).encode())
        markers = []
        for node in svg.iter(SVG+'text'):
            text = ''.join(node.itertext())
            if text not in MARKERS or not text:
                continue
            matrix = IDENTITY
            for ancestor in [*reversed(list(node.iterancestors())), node]:
                matrix = _multiply(matrix, _transform(ancestor.get('transform', '')))
            x, y = float(node.get('x', 0)), float(node.get('y', 0))
            markers.append((text, matrix[0]*x+matrix[2]*y+matrix[4], matrix[1]*x+matrix[3]*y+matrix[5]))
        if ([m[0] for m in markers] != labels
            or max(m[2] for m in markers)-min(m[2] for m in markers) > .1):
            evidence['unmeasured_rows'] += 1
            continue
        widths = [round(int(tab.get('width', '0'))+(stops[i+1]-stops[i])
                        -(markers[i+1][1]-markers[i][1])*75) for i, tab in enumerate(tabs)]
        if any(width < 0 or width > 65535 for width in widths):
            evidence['unmeasured_rows'] += 1
            continue
        evidence['measured_rows'] += 1
        if any(int(tab.get('width', '0')) != width for tab, width in zip(tabs, widths)):
            for tab, width in zip(tabs, widths):
                tab.set('width', str(width))
            changed.add(filename)
            evidence['updated_rows'] += 1
    if changed:
        for filename in changed:
            payloads[filename] = etree.tostring(roots[filename], encoding='utf-8', xml_declaration=True, standalone=True)
        with zipfile.ZipFile(path, 'w') as archive:
            for info in infos:
                archive.writestr(info, payloads[info.filename])
    return evidence
