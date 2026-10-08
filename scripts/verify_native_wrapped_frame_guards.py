"""Actual-source and fail-closed checks for one-cell wrapped prose frames."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import zipfile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app.hwpx_writer_v2  # expose the bundled editable-document tools
from app.pdf_wrapped_prose_frames import HP, HH, HC, WRAPPED_CELL, source_flow_wrapped_prose_frame_table
from hwpx.tools.paragraph_floats import wrapped_cell_layout
from hwpx.tools.question_reflow import flow_height
from hwpx.tools.wrapped_flow_state import begin, finish, decode, PREFIX


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT/'data/external_exam_qa/2026_september_high2/english.pdf')
    parser.add_argument('--hwpx', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if not args.source.is_file() or not args.hwpx.is_file():
        print('SKIP: actual source or HWPX fixture missing')
        return 2
    checks = []
    with zipfile.ZipFile(args.hwpx) as package:
        header = etree.fromstring(package.read('Contents/header.xml'))
        manifest = etree.fromstring(package.read('Contents/content.hpf'))
        hrefs = {n.get('id'): n.get('href') for n in manifest.iter() if n.get('href')}
        roots = [etree.fromstring(package.read(n)) for n in package.namelist()
                 if n.startswith('Contents/section') and n.endswith('.xml')]
        wrapped=lambda c: c.get('name','')==WRAPPED_CELL or c.get('name','').startswith(PREFIX)
        root = next(s for s in roots if any(wrapped(c) for c in s.iter(HP+'tc')))
        table = next(c.getparent().getparent() for c in root.iter(HP+'tc') if wrapped(c))
        def prove(t, r, h, source=args.source):
            return source_flow_wrapped_prose_frame_table(t, r, h, hrefs, package, source)
        assert prove(table,root,header), 'actual source rules/text/image/masks must independently match'
        checks.append('actual_source_complete_frame')
        for case in ('missing_text','wrong_picture','missing_border','width','question_width',
                     'page_anchor','overlap','second_picture','picture_inline','wrong_owner',
                     'oversized_cache','descender','mask_overlap','nan_width','nan_spacing',
                     'nan_textpos','noninteger_textpos','nan_margin','missing_source',
                     'wrong_cell_address','fractional_cell_address','wrong_cell_span','negative_exclusion'):
            changed = deepcopy(root); h = deepcopy(header)
            t = next(c.getparent().getparent() for c in changed.iter(HP+'tc') if wrapped(c))
            cell = t.find(HP+'tr/'+HP+'tc'); pic = t.find('.//'+HP+'pic')
            lines = t.findall('.//'+HP+'lineseg')
            if case == 'missing_text':
                next(t.iter(HP+'t')).text = 'omitted source text'
            elif case == 'wrong_picture':
                image = pic.find(HC+'img')
                image.set('binaryItemIDRef', next(k for k,v in hrefs.items() if k != image.get('binaryItemIDRef') and v.startswith('BinData/')))
            elif case == 'missing_border':
                fill = next(f for f in h.iter(HH+'borderFill') if f.get('id') == cell.get('borderFillIDRef'))
                fill.find(HH+'rightBorder').set('type','NONE')
            elif case == 'width': t.find(HP+'sz').set('width',str(float(t.find(HP+'sz').get('width'))+100))
            elif case == 'question_width': next(a for a in t.iterancestors() if a.tag == HP+'drawText').set('lastWidth','1000')
            elif case == 'page_anchor': pic.find(HP+'pos').set('vertRelTo','PAGE')
            elif case == 'overlap': pic.find(HP+'pos').set('allowOverlap','1')
            elif case == 'second_picture': pic.getparent().append(deepcopy(pic))
            elif case == 'picture_inline': pic.find(HP+'pos').set('treatAsChar','1')
            elif case == 'wrong_owner':
                pic.getparent().remove(pic)
                cell.findall(HP+'subList/'+HP+'p')[-1].find(HP+'run').insert(0,pic)
            elif case == 'oversized_cache':
                lines[0].set('vertsize','200000'); lines[0].set('textheight','200000')
            elif case == 'descender': lines[0].set('baseline',lines[0].get('textheight'))
            elif case == 'mask_overlap':
                owner = pic.getparent().getparent()
                owner.findall(HP+'linesegarray/'+HP+'lineseg')[-1].set('horzsize','22430')
            elif case == 'nan_width': cell.find(HP+'cellSz').set('width','nan')
            elif case == 'nan_spacing': lines[0].set('spacing','nan')
            elif case == 'nan_textpos': lines[0].set('textpos','nan')
            elif case == 'noninteger_textpos': lines[0].set('textpos','.5')
            elif case == 'nan_margin':
                paragraph = cell.find(HP+'subList/'+HP+'p')
                style = next(p for p in h.iter(HH+'paraPr') if p.get('id') == paragraph.get('paraPrIDRef'))
                style.find('.//'+HH+'margin/'+HC+'prev').set('value','nan')
            elif case == 'wrong_cell_address': cell.find(HP+'cellAddr').set('rowAddr','1')
            elif case == 'fractional_cell_address': cell.find(HP+'cellAddr').set('colAddr','.5')
            elif case == 'wrong_cell_span': cell.find(HP+'cellSpan').set('rowSpan','2')
            elif case == 'negative_exclusion': pic.find(HP+'outMargin').set('left','20000')
            before=(etree.tostring(changed),etree.tostring(h))
            source=args.source if case != 'missing_source' else args.source.with_name('absent-source-fixture.pdf')
            assert not prove(t,changed,h,source), f'fail-closed source/native guard: {case}'
            assert before == (etree.tostring(changed),etree.tostring(h)), f'guard must not mutate: {case}'
            checks.append(case)
        styles={p.get('id'):p for p in header.iter(HH+'paraPr')}
        generic=deepcopy(table.find(HP+'tr/'+HP+'tc')); generic.set('name','')
        assert wrapped_cell_layout(generic,styles) is None, 'generic tables cannot opt in by topology alone'
        picture=table.find('.//'+HP+'pic'); ordinary=etree.Element(HP+'p'); run=etree.SubElement(ordinary,HP+'run')
        run.append(deepcopy(picture)); run[0].find(HP+'pos').set('treatAsChar','1')
        assert flow_height(ordinary) == float(picture.find(HP+'sz').get('height'))+400
        checks.extend(('generic_table_unchanged','ordinary_picture_reserve_400'))
        # Native break history distinguishes our generated pagination from a
        # later explicit user edit. Metadata cannot bypass cell eligibility.
        changed=deepcopy(root)
        cells=list(changed.iter(HP+'tc'))
        cell=next(c for c in cells if wrapped(c))
        intro=cell.findall(HP+'subList/'+HP+'p')[1]
        cache=intro.find(HP+'linesegarray');intro.remove(cache)
        context=begin(changed,styles,{c.get('id'):c for c in header.iter(HH+'charPr')})
        assert context is not None
        baseline=context['slots'].copy()
        intro.append(cache)
        following=next(p for p in changed.findall(HP+'p') if any(d.get('name')=='question:v1:q28' for d in p.iter(HP+'drawText')))
        following.set('pageBreak','1');following.set('columnBreak','0')
        finish(changed,context,styles,{c.get('id'):c for c in header.iter(HH+'charPr')})
        assert cell.get('name','').startswith(PREFIX)
        decode(cell.get('name'))
        intro.remove(cache)
        after=begin(changed,styles,{c.get('id'):c for c in header.iter(HH+'charPr')})
        assert after is not None and after['slots'][following]==baseline[following]
        checks.append('generated_break_uses_original_baseline')
        following.set('pageBreak','0');following.set('columnBreak','1')
        manual=begin(changed,styles,{c.get('id'):c for c in header.iter(HH+'charPr')})
        assert manual is not None and manual['state']['base'][changed.findall(HP+'p').index(following)]==['0','1']
        checks.append('explicit_manual_break_change_preserved')
        following.set('columnBreak','0')
        manual=begin(changed,styles,{c.get('id'):c for c in header.iter(HH+'charPr')})
        assert manual is not None and manual['state']['base'][changed.findall(HP+'p').index(following)]==['0','0']
        checks.append('explicit_manual_break_removal_preserved')
        for case in ('malformed_state','forged_state','changed_order','duplicate_id','missing_id','generic_dirty'):
            r=deepcopy(changed)
            c=next(c for c in r.iter(HP+'tc') if c.get('name','').startswith(PREFIX))
            if case=='malformed_state': c.set('name',PREFIX+'invalid')
            elif case=='forged_state': c.set('name',c.get('name')[:-5]+'AAAAA')
            elif case=='changed_order': r.insert(1,r.findall(HP+'p')[-1])
            elif case=='duplicate_id': r.findall(HP+'p')[1].set('id',r.findall(HP+'p')[0].get('id'))
            elif case=='missing_id': r.findall(HP+'p')[0].attrib.pop('id')
            elif case=='generic_dirty':
                target=next(p for p in r.findall(HP+'p') if p.find(HP+'linesegarray') is not None)
                target.remove(target.find(HP+'linesegarray'))
            before=etree.tostring(r)
            assert begin(r,styles,{c.get('id'):c for c in header.iter(HH+'charPr')}) is None,case
            assert etree.tostring(r)==before
            checks.append(case)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps({'ok':True,'source':str(args.source),'hwpx':str(args.hwpx),
                                      'checks':checks,'count':len(checks)},indent=2),encoding='utf8')
    print('WRAPPED_FRAME_GUARDS_OK',len(checks))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
