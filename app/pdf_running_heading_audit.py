"""Independently check source running fields against native controls and paint."""
import re
import zipfile
from lxml import etree
import fitz

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'


def inspect_running_header_fields(source, output, page_limit=None):
    from .pdf_layout_writer import _page_body_top
    from .pdf_running_furniture import measure_running_furniture
    from .pdf_question_rendering import _visible_svg_text, _multiply, _transform, IDENTITY, SVG

    records = []
    with fitz.open(source) as pdf:
        count = min(len(pdf), page_limit) if page_limit is not None else len(pdf)
        for index in range(1, count):
            page = pdf[index]
            top = _page_body_top(page)
            subjects = {s['text'].strip() for b in page.get_text('dict')['blocks'] for l in b.get('lines', [])
                        if l['bbox'][3] < top for s in l['spans']
                        if re.fullmatch(r'.{1,16}영역(?:\s*\([^\n]+\))?', s['text'].strip())}
            if len(subjects) != 1:
                continue
            measured = measure_running_furniture(page, top, next(iter(subjects)))
            if measured:
                records.append((index, measured))
    result = {'ok': True, 'source_pages_checked': len(records), 'native_page_fields_checked': 0,
              'painted_header_fields_checked': 0, 'issues': []}
    if not records:
        return result
    with zipfile.ZipFile(output) as package:
        roots = [etree.fromstring(package.read(name)) for name in sorted(package.namelist())
                 if re.fullmatch(r'Contents/section\d+\.xml', name)]
    headers = [h for root in roots[1:] for h in root.findall(HP+'p/'+HP+'run/'+HP+'ctrl/'+HP+'header')]
    for parity in {('EVEN' if (index+1)%2 == 0 else 'ODD') for index, _ in records}:
        matching = [h for h in headers if h.get('applyPageType') == parity]
        fields = [n for h in matching for n in h.iter(HP+'autoNum') if n.get('numType') == 'PAGE']
        if len(matching) != 1 or len(fields) != 1:
            result['issues'].append({'kind': 'missing_or_duplicate_native_page_field', 'parity': parity})
        else:
            result['native_page_fields_checked'] += 1
    try:
        import rhwp
        native = rhwp.parse(str(output))
        for index, record in records:
            if index >= native.page_count:
                result['issues'].append({'kind': 'missing_rendered_page', 'page': index+1})
                continue
            root = etree.fromstring(native.render_svg(index).encode())
            scale = float(root.get('width')) / record['page_width_pt']
            for node in list(root.iter(SVG+'text')):
                matrix = IDENTITY
                for ancestor in [*reversed(list(node.iterancestors())), node]:
                    matrix = _multiply(matrix, _transform(ancestor.get('transform', '')))
                x, y = float(node.get('x', 0)), float(node.get('y', 0))
                baseline = matrix[1]*x+matrix[3]*y+matrix[5]
                if baseline >= record['body_top_pt']*scale:
                    node.getparent().remove(node)
            visible, invisible, unknown = _visible_svg_text(etree.tostring(root, encoding='unicode'))
            expected = ''.join(f['text'] for f in sorted(record['fields'].values(), key=lambda f: f['bbox_pt'][0]))
            if re.sub(r'\s+', '', visible) != re.sub(r'\s+', '', expected) or invisible or unknown:
                result['issues'].append({'kind': 'missing_or_unpainted_header_field', 'page': index+1,
                                         'expected': expected, 'painted': visible,
                                         'invisible': invisible, 'unassessed': unknown})
            else:
                result['painted_header_fields_checked'] += 3
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        result['issues'].append({'kind': 'header_render_unavailable', 'error': str(error)})
    result['ok'] = not result['issues']
    return result
