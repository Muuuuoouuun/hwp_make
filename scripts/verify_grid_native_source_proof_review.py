"""Independent source-consumer native glyph-style proof on a real plain grid.

The source PDF, decoration image, source provenance, all text and the source
glyph baseline stay unchanged in the height mutant. Reconstructing expected
native cells from their current styles cannot prove source font size.
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
from app.pdf_source_grid_layout import source_flow_grid_frame_table,HP,HH,HC
from hwpx.tools import ruled_grid_flow as flow


def text(node):
    return ''.join(t.text or '' for t in node.iter(HP+'t'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hwpx',type=Path,default=ROOT/'tmp/september-exam-matrix/high3-grid-final3/native.hwpx')
    parser.add_argument('--source',type=Path,default=ROOT/'data/external_exam_qa/2027_kice_september_high3/english.pdf')
    parser.add_argument('--stats',type=Path)
    parser.add_argument('--report',type=Path,default=ROOT/'tmp/september-audit/grid-native-source-independent/report.json')
    args = parser.parse_args()
    stats_path = args.stats or args.hwpx.parent/'write.json'
    if not all(p.is_file() for p in (args.hwpx,args.source,stats_path)):
        print('SKIP: existing native, source and writer stats required');return 2
    files = [ROOT/'app/pdf_source_grid_layout.py',ROOT/'app/_vendor/hwpx/tools/ruled_grid_flow.py']
    hashes = lambda:{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    before_code = hashes()
    with ZipFile(args.hwpx) as package:
        parts = {n:package.read(n) for n in package.namelist()}
    header = etree.fromstring(parts['Contents/header.xml'])
    roots = [etree.fromstring(v) for n,v in parts.items() if n.startswith('Contents/section') and n.endswith('.xml')]
    manifest = etree.fromstring(parts['Contents/content.hpf'])
    hrefs = {n.get('id'):n.get('href') for n in manifest.iter('{http://www.idpf.org/2007/opf/}item')}
    provenance = json.loads(stats_path.read_text(encoding='utf8'))['image_provenance']
    tables = [(r,t) for r in roots for t in r.iter(HP+'tbl') if t.get('name','').startswith(flow.PREFIX)]
    checks,failures = [],[]
    def record(name,passed,**evidence):
        checks.append({'name':name,'passed':bool(passed),**evidence})
        if not passed:failures.append(name)
        print(('PASS: ' if passed else 'FAIL: ')+name,flush=True)
    for index,(r,t) in enumerate(tables):
        before = etree.tostring(r),etree.tostring(header)
        accepted = source_flow_grid_frame_table(t,r,header,hrefs,parts,args.source,provenance)
        record(f'actual_source_grid_{index+1}',accepted and before == (etree.tostring(r),etree.tostring(header)))
    root,table = next((r,t) for r,t in tables if 'Winners' in text(t))
    for name in ('native_height_compensated_source_baseline','native_bold','native_narrow_ratio','native_tracking'):
        r,h = deepcopy(root),deepcopy(header)
        t = next(t for t in r.iter(HP+'tbl') if t.get('name','').startswith(flow.PREFIX) and 'Winners' in text(t))
        cell = next(c for c in t.findall(HP+'tr/'+HP+'tc') if text(c) == '1st prize')
        p = cell.find(HP+'subList/'+HP+'p')
        style = next(c for c in h.iter(HH+'charPr') if c.get('id') == p.find(HP+'run').get('charPrIDRef'))
        clone = deepcopy(style)
        clone.set('id',str(max(int(c.get('id')) for c in h.iter(HH+'charPr'))+1))
        chars = h.find('.//'+HH+'charProperties');chars.append(clone);chars.set('itemCnt',str(len(chars)))
        for run in p.findall(HP+'run'):run.set('charPrIDRef',clone.get('id'))
        evidence = {'old_native_height':int(style.get('height')),'text_unchanged':text(p) == '1st prize'}
        if name == 'native_height_compensated_source_baseline':
            clone.set('height','600')
            line = p.find(HP+'linesegarray/'+HP+'lineseg')
            old_baseline = int(line.get('baseline'))
            line.set('vertsize','600');line.set('textheight','600');line.set('baseline','510')
            margin = cell.find(HP+'cellMargin')
            old_top = int(margin.get('top'));margin.set('top',str(old_top+old_baseline-510))
            evidence.update(new_native_height=600,source_baseline_unchanged=old_top+old_baseline == int(margin.get('top'))+510)
        elif name == 'native_bold':etree.SubElement(clone,HH+'bold')
        else:
            tag,value = ('ratio','90') if name == 'native_narrow_ratio' else ('spacing','-10')
            for lang in clone.find(HH+tag).attrib:clone.find(HH+tag).set(lang,value)
        # The proof must stand without the mutable cache state. Supply a
        # digest-valid snapshot matching changed native style/cache/geometry.
        state = flow.decode(t.get('name'))
        ps = {s.get('id'):s for s in h.iter(HH+'paraPr')};cs = {s.get('id'):s for s in h.iter(HH+'charPr')}
        state['geometry'] = flow.geometry(t,h)[0]
        for entry in state['cells']:
            q = next(q for q in t.iter(HP+'p') if q.get('id') == entry[0])
            entry[1] = flow.metrics(q,ps,cs)[1]
            if q is p:
                entry[2] = flow.lines(q)
                entry[3] = int(cell.find(HP+'cellSz').get('height'))-int(cell.find(HP+'cellMargin').get('top'))-entry[2][-1][2]
        t.set('name',flow.encode(state))
        before = etree.tostring(r),etree.tostring(h)
        accepted = source_flow_grid_frame_table(t,r,h,hrefs,parts,args.source,provenance)
        atomic = before == (etree.tostring(r),etree.tostring(h))
        record(name,not accepted and atomic,accepted=accepted,transactional=atomic,**evidence)
    after_code = hashes()
    record('reviewed_code_snapshot_stable',before_code == after_code)
    report = {'ok':not failures,'input':str(args.hwpx),'source':str(args.source),'checks':checks,'failures':failures,
              'before_code':before_code,'after_code':after_code,
              'scope':'source consumer actual glyph size/style proof against digest-valid changed current native styles; no full-page quality claim'}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'ok':report['ok'],'checks':len(checks),'failures':failures,'report':str(args.report)},ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
