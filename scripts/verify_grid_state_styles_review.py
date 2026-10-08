"""Independent digest-valid grid state mutations with current style signatures.

An ordinary stale signature test does not exercise independent native style
validation. Every mutant here has all its cell style signatures refreshed
from the changed XML, followed by a new valid state checksum.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.hwpx_writer_v2 import HwpxDocument
from hwpx.tools import ruled_grid_flow as grid

HP,HH,HC = grid.HP,grid.HH,grid.HC


def text(node):
    return ''.join(t.text or '' for t in node.iter(HP+'t'))


def target(root):
    return next(t for t in root.iter(HP+'tbl') if t.get('name','').startswith(grid.PREFIX) and 'Winners' in text(t))


def signature(paragraph,para,char):
    # Deliberately avoid grid.metrics: that is the independent validator being
    # tested. Hashing changed XML must never bless unsupported style effects.
    return [grid.digest(grid.xml(para[paragraph.get('paraPrIDRef')])),
            [grid.digest(grid.xml(char[r.get('charPrIDRef')])) for r in paragraph.findall(HP+'run')]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hwpx',type=Path,default=ROOT/'tmp/september-exam-matrix/high3-grid-final2/native.hwpx')
    parser.add_argument('--report',type=Path,default=ROOT/'tmp/september-audit/grid-state-styles-independent/report.json')
    args = parser.parse_args()
    if not args.hwpx.is_file():
        print('SKIP: existing native fixture required');return 2
    code = ROOT/'app/_vendor/hwpx/tools/ruled_grid_flow.py'
    before_code = hashlib.sha256(code.read_bytes()).hexdigest()
    with ZipFile(args.hwpx) as package:
        header = etree.fromstring(package.read('Contents/header.xml'))
        roots = [etree.fromstring(package.read(n)) for n in package.namelist()
                 if n.startswith('Contents/section') and n.endswith('.xml')]
    root = next(r for r in roots if any('Winners' in text(t) for t in r.iter(HP+'tbl')))
    checks,failures = [],[]
    for name in ('positive_exact','strikeout','outline','shadow','emboss','engrave',
                 'italic','supscript','subscript','underline','latin_font','symbol_font',
                 'missing_font_ref_language','nonuniform_ratio','nonuniform_spacing',
                 'unicode_surrogate_pair','unicode_combining','tab','newline',
                 'native_equation','native_picture','native_nested_text','native_paragraph_control',
                 'duplicate_cache_container','generic_dirty'):
        r,h = deepcopy(root),deepcopy(header)
        table = target(r)
        p = next(p for p in table.iter(HP+'p') if text(p) == '1st prize')
        p.remove(p.find(HP+'linesegarray'))
        para = {s.get('id'):s for s in h.iter(HH+'paraPr')}
        char = {s.get('id'):s for s in h.iter(HH+'charPr')}
        style = char[p.find(HP+'run').get('charPrIDRef')]
        if name in ('strikeout','italic','supscript','subscript','emboss','engrave'):
            etree.SubElement(style,HH+name,**({'shape':'SOLID','color':'#000000'} if name == 'strikeout' else {}))
        elif name in ('outline','shadow'):style.find(HH+name).set('type','SOLID' if name == 'outline' else 'DISCRETE')
        elif name == 'underline':style.find(HH+'underline').set('type','BOTTOM')
        elif name in ('latin_font','symbol_font'):
            lang = 'latin' if name == 'latin_font' else 'symbol'
            ident = style.find(HH+'fontRef').get(lang)
            next(f for face in h.iter(HH+'fontface') if face.get('lang') == lang.upper() for f in face if f.get('id') == ident).set('face','Arial')
        elif name == 'missing_font_ref_language':del style.find(HH+'fontRef').attrib['symbol']
        elif name in ('nonuniform_ratio','nonuniform_spacing'):
            tag = name.removeprefix('nonuniform_');node = style.find(HH+tag);node.set('latin',str(int(node.get('latin'))+1))
        elif name in ('unicode_surrogate_pair','unicode_combining','tab','newline'):
            p.find(HP+'run/'+HP+'t').text += {'unicode_surrogate_pair':'\U0001f600','unicode_combining':'\u0301','tab':'\t','newline':'\n'}[name]
        elif name in ('native_equation','native_picture'):
            etree.SubElement(p.find(HP+'run'),HP+('equation' if name == 'native_equation' else 'pic'))
        elif name == 'native_nested_text':etree.SubElement(p.find(HP+'run/'+HP+'t'),HP+'lineBreak')
        elif name == 'native_paragraph_control':etree.SubElement(p,HP+'ctrl')
        elif name == 'duplicate_cache_container':
            other = next(q for q in table.iter(HP+'p') if q is not p and q.find(HP+'linesegarray') is not None)
            other.append(deepcopy(other.find(HP+'linesegarray')))
        elif name == 'generic_dirty':
            extra = etree.SubElement(r,HP+'p',id='independent-current-state-generic')
            etree.SubElement(etree.SubElement(extra,HP+'run'),HP+'t').text = 'ordinary editable text'
        state = grid.decode(table.get('name'))
        for record in state['cells']:
            q = next(q for q in table.iter(HP+'p') if q.get('id') == record[0])
            record[1] = signature(q,para,char)
        if name == 'generic_dirty':
            state['ids'] = [q.get('id') for q in r.findall(HP+'p')]
            state['base'] = state['last'] = grid.flags(r)
        table.set('name',grid.encode(state))
        before = etree.tostring(r),etree.tostring(h)
        context = grid.begin(r,para,char)
        accepted,atomic = context is not None,before == (etree.tostring(r),etree.tostring(h))
        passed = accepted == (name == 'positive_exact') and atomic
        checks.append({'name':name,'passed':passed,'accepted':accepted,'transactional':atomic,
                       'current_style_signatures_and_digest_valid':True})
        if not passed:failures.append(name)
        print(('PASS: ' if passed else 'FAIL: ')+name,flush=True)
    after_code = hashlib.sha256(code.read_bytes()).hexdigest()
    if before_code != after_code:failures.append('reviewed_code_snapshot_stable')
    report = {'ok':not failures,'input':str(args.hwpx),'input_sha256':hashlib.sha256(args.hwpx.read_bytes()).hexdigest(),
              'before_code':before_code,'after_code':after_code,'checks':checks,'failures':failures,
              'scope':'digest-valid current-native styles, complete ASCII/UTF-16 rejection, controls and generic intrusion; no full-page quality verdict',
              'known_nativecell3_ignored_style_properties':['relSz','offset','useFontSpace','useKerning','symMark'],
              'prior_strikeout_mutant_paint_changed':'tmp/september-audit/grid-flow-independent/strikeout-synced.hwpx'}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'ok':report['ok'],'checks':len(checks),'failures':failures,'report':str(args.report)},ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
