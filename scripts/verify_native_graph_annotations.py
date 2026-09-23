"""Real graph ownership, visible labels, paragraph edits and corruption checks."""
from copy import deepcopy
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix='native_graph_runtime_')
if __name__ == '__main__':
    os.environ['HWP_MAKE_DATA_DIR'] = runtime.name
import fitz
from lxml import etree as E
from PIL import Image
from app.pdf_layout_writer import write_pdf_structured_hwpx, _iter_text_lines, _line_text, _pdf_output_text
from app.pdf_editability import inspect_pdf_editability
from app.pdf_native_text import body_text
from app.pdf_question_rendering import inspect_question_rendering, _multiply, _transform, _bounds, IDENTITY
from app.pdf_layout_fidelity import rhwp
from app.hwpx_writer_v2 import HwpxDocument
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.package_validator import validate_package

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HC = '{http://www.hancom.co.kr/hwpml/2011/core}'
SVG = '{http://www.w3.org/2000/svg}'


def state(path):
    with zipfile.ZipFile(path) as archive:
        roots = {n:E.fromstring(archive.read(n)) for n in archive.namelist() if re.fullmatch(r'Contents/section\d+\.xml',n)}
        media = {n:hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist() if n.startswith('BinData/')}
    return roots,media


def paint(path,page_index):
    doc = rhwp.parse(str(path))
    svg = doc.render_svg(page_index)
    root = E.fromstring(svg.encode())
    values = []
    for node in root.iter():
        if node.tag not in (SVG+'image',SVG+'text'):
            continue
        if any(E.QName(a).localname in ('defs','pattern','clipPath') for a in node.iterancestors()):
            continue
        matrix = IDENTITY
        for ancestor in [*reversed(list(node.iterancestors())),node]:
            matrix = _multiply(matrix,_transform(ancestor.get('transform','')))
        bounds = _bounds(matrix,float(node.get('x',0)),float(node.get('y',0)),
                         float(node.get('width',0)),float(node.get('height',0)))
        values.append({'kind':E.QName(node).localname,'text':''.join(node.itertext()),'bounds':bounds})
    return doc.page_count,values,svg


def verify(folder,source=None,native=None,provenance=None,check_api=False):
    folder.mkdir(parents=True,exist_ok=True)
    source = source or ROOT/'data/external_exam_qa/2026_june_high1/math.pdf'
    if not source.is_file():
        print('SKIP: local real math PDF unavailable')
        return False
    if native is None:
        native = folder/'math.hwpx'
        stats = write_pdf_structured_hwpx(source,native,native_math=True)
        provenance = stats['image_provenance']
        (folder/'stats.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf8')
    audit = inspect_pdf_editability(source,native,provenance,require_question_boxes=True)
    assert audit['ok'],audit['issues']
    graph_audit = audit['question_units']['graph_annotations']
    assert graph_audit['annotation_count'] == 10 and len(graph_audit['graphs']) == 1,graph_audit
    assert validate_package(native).ok
    roots,assets = state(native)
    root = next(r for r in roots.values() if r.find('.//'+HP+'container') is not None)
    group = root.find('.//'+HP+'container')
    assert len(group.findall(HP+'rect')) == 10
    assert len(group.findall('.//'+HP+'equation')) == 3
    count = sum(len(list(r.iter(HP+'p'))) for r in roots.values())
    pages,paints,svg = paint(native,10)
    image = next(p['bounds'] for p in paints if p['kind']=='image')
    record = next(p for p in provenance if p.get('source_kind') == 'bitmap_objects')
    with fitz.open(source) as original:
        page = original[10]
        scale = float(root.find('.//'+HP+'pagePr').get('width'))/page.rect.width/75
        sx,sy,w,h = record['bbox_px']
        expected = (sx*scale,sy*scale,(sx+w)*scale,(sy+h)*scale)
        source_lines = sorted((line for line in _iter_text_lines(page)
                         if fitz.Rect(sx,sy,sx+w,sy+h).intersects(fitz.Rect(line['bbox']))),
                         key=lambda line:(line['bbox'][1],line['bbox'][0]))
        source_labels = [_pdf_output_text(_line_text(line)).replace('$','') for line in source_lines]
    error = max(abs(a-b) for a,b in zip(image,expected))
    assert error < .1,(image,expected,error)
    # Count only actual text paints beside/inside this graph, excluding stem.
    graph_text = ''.join(p['text'] for p in paints if p['kind']=='text'
                         and image[0]-2 <= p['bounds'][0] <= image[2]+2
                         and image[1]-2 <= p['bounds'][1] <= image[3]+2)
    assert re.sub(r'\s','',graph_text) == re.sub(r'\s','',''.join(source_labels)),(source_labels,graph_text)
    assert inspect_question_rendering(native,rhwp)['ok']
    (folder/'page11.svg').write_text(svg,encoding='utf8')
    (folder/'page11.png').write_bytes(rhwp.parse(str(native)).render_png(10))

    doc = HwpxDocument.open(native)
    section = next(s for s in doc.sections if s.element.find('.//'+HP+'container') is not None)
    graph = section.element.find('.//'+HP+'container')
    label = next(p for p in graph.iter(HP+'p') if body_text(p)=='A')
    HwpxOxmlParagraph(label,section).text = 'R'
    equation = next(e for e in graph.iter(HP+'equation') if e.findtext(HP+'script')=='y=f(x)')
    equation.find(HP+'script').text = 'y=h(x)'
    section.mark_dirty()
    edited = folder/'edited_labels.hwpx'
    doc.save_to_path(edited)
    new_roots,new_assets = state(edited)
    new_group = next(r.find('.//'+HP+'container') for r in new_roots.values() if r.find('.//'+HP+'container') is not None)
    assert 'R' in [body_text(p) for p in new_group.iter(HP+'p')]
    assert 'y=h(x)' in [e.findtext(HP+'script') for e in new_group.iter(HP+'equation')]
    assert new_assets == assets
    assert sum(len(list(r.iter(HP+'p'))) for r in new_roots.values()) == count
    assert inspect_question_rendering(edited,rhwp)['ok']
    edited_pages,edited_paints,_ = paint(edited,10)
    assert edited_pages == pages == 12
    edited_image = next(p['bounds'] for p in edited_paints if p['kind']=='image')
    assert max(abs(a-b) for a,b in zip(edited_image,image)) < .1
    assert any(p['text']=='R' for p in edited_paints)
    edited_graph_text = [p['text'] for p in edited_paints if p['kind']=='text'
                         and image[0]-2 <= p['bounds'][0] <= image[2]+2
                         and image[1]-2 <= p['bounds'][1] <= image[3]+2]
    assert 'A' not in edited_graph_text,edited_graph_text
    assert 'h' in edited_graph_text,edited_graph_text
    resaved = folder/'resaved_labels.hwpx'
    HwpxDocument.open(edited).save_to_path(resaved)
    assert paint(edited,10) == paint(resaved,10)

    # Edit the whole prose paragraph before the graph while retaining equations.
    doc = HwpxDocument.open(native)
    section = next(s for s in doc.sections if s.element.find('.//'+HP+'container') is not None)
    graph = section.element.find('.//'+HP+'container')
    question = next(a for a in graph.iterancestors() if a.tag==HP+'drawText')
    stem = question.find(HP+'subList/'+HP+'p')
    addition = ' Additional evidence remains in this same editable paragraph.'*4
    HwpxOxmlParagraph(stem,section).add_run(addition,char_pr_id_ref=stem.find(HP+'run').get('charPrIDRef'))
    expanded = folder/'expanded_paragraph.hwpx'
    doc.save_to_path(expanded)
    expanded_pages,expanded_paints,_ = paint(expanded,10)
    expanded_image = next(p['bounds'] for p in expanded_paints if p['kind']=='image')
    assert expanded_image[1] > image[1]+10 and abs(expanded_image[0]-image[0]) < .1
    assert expanded_pages==12 and inspect_question_rendering(expanded,rhwp)['ok']
    assert state(expanded)[1] == assets
    assert sum(len(list(r.iter(HP+'p'))) for r in state(expanded)[0].values()) == count

    corruptions = {}
    def corrupt(name,mutate):
        changed = deepcopy(root)
        g = changed.find('.//'+HP+'container')
        mutate(g)
        destination = folder/(name+'.hwpx')
        with zipfile.ZipFile(native) as before,zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as after:
            for entry in before.infolist():
                after.writestr(entry,E.tostring(changed,xml_declaration=True,encoding='UTF-8')
                               if entry.filename == next(n for n,r in roots.items() if r is root) else before.read(entry.filename))
        outcome = inspect_pdf_editability(source,destination,provenance,require_question_boxes=True)
        assert not outcome['ok'],name
        corruptions[name] = outcome['issues']
    corrupt('missing_label',lambda g:g.remove(g.find(HP+'rect')))
    corrupt('duplicate_label',lambda g:g.append(deepcopy(g.find(HP+'rect'))))
    corrupt('wrong_text',lambda g:setattr(g.find('.//'+HP+'t'),'text','Z'))
    corrupt('shifted_label',lambda g:g.find(HP+'rect/'+HP+'renderingInfo/'+HC+'transMatrix').set('e3','0'))
    corrupt('locked_label',lambda g:g.find(HP+'rect').set('lock','1'))
    corrupt('collapsed_label',lambda g:g.find(HP+'rect/'+HP+'drawText/'+HP+'subList').set('textHeight','0'))
    corrupt('scaled_group',lambda g:g.find(HP+'renderingInfo/'+HC+'scaMatrix').set('e1','2'))
    corrupt('duplicate_outside',lambda g:g.getparent().getparent().getparent().append(deepcopy(g.find(HP+'rect/'+HP+'drawText/'+HP+'subList/'+HP+'p'))))
    pixel_results = {}
    for alter in (False,True):
        name = 'one_changed_bitmap_pixel' if alter else 'reencoded_identical_pixels'
        changed_provenance = deepcopy(provenance)
        changed_record = next(p for p in changed_provenance if p.get('source_kind')=='bitmap_objects')
        destination = folder/(name+'.hwpx')
        with zipfile.ZipFile(native) as before,zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as after:
            for entry in before.infolist():
                payload = before.read(entry.filename)
                if entry.filename.startswith('BinData/') and hashlib.sha256(payload).hexdigest()==changed_record['sha256']:
                    with Image.open(io.BytesIO(payload)) as encoded_image:
                        pixels=encoded_image.convert('RGB')
                    if alter:
                        pixels.putpixel((4,4),(0,0,0))
                    buffer=io.BytesIO();pixels.save(buffer,format='PNG',optimize=True)
                    payload=buffer.getvalue()
                    changed_record['sha256']=hashlib.sha256(payload).hexdigest()
                after.writestr(entry,payload)
        outcome=inspect_pdf_editability(source,destination,changed_provenance,require_question_boxes=True)
        assert outcome['ok'] is (not alter),outcome['issues']
        if alter:
            assert 'source_picture_pixels_mismatch' in outcome['issues']
            corruptions[name]=outcome['issues']
        pixel_results[name]={'ok':outcome['ok'],'issues':outcome['issues']}
    for path in (edited,resaved,expanded):
        assert validate_package(path).ok,path
    report = {'ok':True,'graph_annotations':graph_audit,'graph_position_maximum_error_px':error,
              'annotation_edits':['A -> R','y=f(x) -> y=h(x)'],'resave_stable':True,
              'paragraph_added_characters':len(addition),'graph_shift_after_edit_px':expanded_image[1]-image[1],
              'paragraph_count_unchanged':True,'bitmaps_unchanged':True,'pages':pages,'rejected_corruptions':corruptions}
    report['exact_bitmap_pixel_checks']=pixel_results
    if check_api:
        from fastapi.testclient import TestClient
        from app import main
        if native is not None:
            stats_path = folder/'stats.json'
            stats = json.loads(stats_path.read_text(encoding='utf8'))
        payload = {'filename':source.name,'data_base64':base64.b64encode(source.read_bytes()).decode(),
                   'native_math':True,'math_ai_recognition':False}
        api_results = []
        with TestClient(main.app) as client:
            for name in ('missing_label','shifted_label'):
                def faulty_writer(_source, output, **kwargs):
                    Path(output).write_bytes((folder/(name+'.hwpx')).read_bytes())
                    return {**stats,'editable_text_coverage_ratio':1,'source_text_preservation_ratio':1}
                with patch.object(main.pdf_layout_writer,'write_pdf_structured_hwpx',faulty_writer):
                    for mode in ('structured','coordinate'):
                        response = client.post('/api/pdf-layout-export',json={**payload,'layout_mode':mode})
                        result = response.json()
                        assert response.status_code == 422,result
                        assert 'graph_annotations' in result['detail']['editability']['question_units']
                        assert 'export' not in result
                        api_results.append({'mutation':name,'mode':mode,'status':response.status_code})
        assert not list((Path(runtime.name)/'exports').rglob('*.hwpx'))
        report['api_rejections_despite_perfect_stats'] = api_results
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('NATIVE_GRAPH_ANNOTATIONS_OK: '+json.dumps(report,ensure_ascii=False))
    return True


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    if args.output_dir:
        ok=verify(args.output_dir,check_api=True)
    else:
        with tempfile.TemporaryDirectory(prefix='native_graph_') as folder:
            ok=verify(Path(folder),check_api=True)
    if not ok:
        sys.exit(2)
