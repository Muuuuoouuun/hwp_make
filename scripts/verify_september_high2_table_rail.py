"""Prove September high2 Q10's actual ruled rows and choice ownership."""
from copy import deepcopy
from pathlib import Path
import argparse
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
from verify_pdf_open_edge_grid import package, check, negative_geometry
import fitz
from app.pdf_source_grid_geometry import source_grid_cell_bounds
from app.pdf_layout_writer import _iter_text_lines
from app.pdf_source_semantics import source_grid_cells, inspect_source_question_semantics, HP
import rhwp


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=ROOT/'data/external_exam_qa/2026_september_high2/english.pdf')
    parser.add_argument('--hwpx',type=Path)
    args=parser.parse_args()
    if not args.source.is_file() or args.hwpx is None or not args.hwpx.is_file():
        print('SKIP: actual high2 source and --hwpx are both required')
        return 2
    with fitz.open(args.source) as document:
        page=document[0]
        grid=next(t for t in page.find_tables().tables if t.row_count==6 and t.col_count==5)
        original=[[c for c in row.cells] for row in grid.rows]
        check(original[1][0] is None and original[2][4] is None,
              'actual detector loses the first two open outer rows')
        horizontals=[]
        for drawing in page.get_drawings():
            for part in drawing['items']:
                if (part[0]=='l' and abs(part[1].y-part[2].y)<.01
                    and min(part[1].x,part[2].x)<453 and max(part[1].x,part[2].x)>750
                    and 666<part[1].y<780):horizontals.append(part[1].y)
        rules=sorted(set(round(y,3) for y in horizontals))
        check(len(rules)==7,'all seven original complete horizontal separators are independently present')
        fixed=source_grid_cell_bounds(page,grid)
        check(all(c is not None for row in fixed for c in row),'complete source rule chain proves every open outer slot')
        check(abs(original[1][1][3]-rules[2])>.7 and abs(fixed[1][0][3]-rules[2])<.001,
              'source rule measurement corrects the false detector row joint')
        matrices=source_grid_cells(page,_iter_text_lines(page))
        expected=next(t['cells'] for t in matrices if len(t['cells'])==6)
        check([row[0] for row in expected]==['','①','②','③','④','⑤'],
              'all five original circled labels belong to their matching source rows')
        check([row[1] for row in expected[1:]]==list('ABCDE'),
              'source A/B/C/D/E glyphs remain in their actual model cells')
        negative_geometry(page,grid)
        # A forged wider source cell must not use the otherwise complete rules.
        from types import SimpleNamespace
        fake=deepcopy(original);fake[1][2]=(*fake[1][2][:2],fake[1][2][2]+500,fake[1][2][3])
        altered=SimpleNamespace(rows=[SimpleNamespace(cells=row) for row in fake],col_count=5)
        check(source_grid_cell_bounds(page,altered)[1][0] is None,
              'forged detected cell geometry cannot use the rule-chain proof')
    draw,header=package(args.hwpx,'question:v1:q10')
    with fitz.open(args.source) as document:
        page=document[0];grids=source_grid_cells(page,_iter_text_lines(page))
        check(inspect_source_question_semantics([],draw,fitz.Rect(page.rect),grids,header=header)['ok'],
              'actual native Q10 retains every independent source row and column')
        for label in ('missing','swapped'):
            altered=deepcopy(draw)
            cells=[cell for cell in altered.iter(HP+'tc')
                   if cell.find(HP+'cellAddr').get('colAddr')=='5'
                   and cell.find(HP+'cellAddr').get('rowAddr') in ('1','2')]
            a,b=[next(cell.iter(HP+'t')) for cell in cells]
            if label=='missing':a.text=''
            else:a.text,b.text=b.text,a.text
            check(not inspect_source_question_semantics([],altered,fitz.Rect(page.rect),grids,header=header)['ok'],
                  f'{label} actual White/Black source values are rejected')
    check(not any((t.text or '').strip() in '①②③④⑤' for p in draw.findall(HP+'subList/'+HP+'p')
                  if p.find(HP+'run/'+HP+'tbl') is None for t in p.iter(HP+'t')),
          'table choice labels are not duplicated as five following prose rows')
    check(rhwp.parse(str(args.hwpx)).page_count==8,'complete actual high2 conversion retains all eight source pages')
    print('SEPTEMBER_HIGH2_TABLE_RAIL_OK')
    return 0


if __name__=='__main__':raise SystemExit(main())
