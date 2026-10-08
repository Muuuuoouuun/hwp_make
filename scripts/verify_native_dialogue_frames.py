"""Actual-source conversation ownership, independent proof and public edits."""
from collections import Counter
from copy import deepcopy
import hashlib
import base64
import io
import json
import os
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
FOLDER = Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'tmp/native-dialogue-frames'
FOLDER.mkdir(parents=True,exist_ok=True)
os.environ['HWP_MAKE_DATA_DIR'] = str((FOLDER/'data').resolve())

import fitz
import numpy as np
from PIL import Image
from lxml import etree
import rhwp
from app.hwpx_writer_v2 import HwpxDocument
from app import pdf_dialogue_frames as dialogue
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_source_image_validation import render_source_crop,compare_source_crop,inspect_source_images
from app.pdf_source_backgrounds import native_background_assets
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.package_validator import validate_package

HP,HH,HC = dialogue.HP,dialogue.HH,dialogue.HC
SVG = '{http://www.w3.org/2000/svg}'
SOURCE = ROOT/'data/external_exam_qa/2026_september_high2/통합사회.pdf'
CAPTURE = {}


def compact(value):return re.sub(r'\s+','',value)


def path_to(node):
    result=[]
    while node.getparent() is not None:
        result.append(node.getparent().index(node));node=node.getparent()
    return list(reversed(result))


def follow(root,path):
    for index in path:root=root[index]
    return root


def packages(path):
    with zipfile.ZipFile(path) as archive:
        header=etree.fromstring(archive.read('Contents/header.xml'))
        roots=[etree.fromstring(archive.read(n)) for n in archive.namelist() if re.fullmatch(r'Contents/section\d+\.xml',n)]
        manifest=etree.fromstring(archive.read('Contents/content.hpf'))
        refs={n.get('id'):n.get('href') for n in manifest.iter('{http://www.idpf.org/2007/opf/}item')}
        media=Counter(hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist() if n.startswith('BinData/'))
    candidates=[(r,t) for r in roots for t in r.iter(HP+'tbl') if '인공 지능의 답변' in ''.join(t.itertext())]
    assert len(candidates)==1
    return header,roots,refs,media,*candidates[0]


def source_fixture():
    frozen=json.loads((ROOT/'tmp/september-exam-matrix/stable-all-51-20261007-final/source_inventory.json').read_text(encoding='utf8'))
    expected=next(r for r in frozen['cases'] if r['id']=='2026_september_high2__s_soc')
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==expected['sha256']
    assert expected['physical_pages']==6 and expected['question_runs']==[list(range(1,26))]
    raw=fitz.open(SOURCE)
    return raw,expected


def capture_write():
    original_coalesce,original_restore=dialogue.coalesce_dialogue_frames,dialogue.restore_dialogue_frame
    def coalesce(blocks,page,lines):
        result=original_coalesce(blocks,page,lines)
        if any(b.get('source_dialogue_frame') for b in result):
            assert 'blocks' not in CAPTURE
            CAPTURE.update(blocks=deepcopy(blocks),source_lines=deepcopy(lines),source_page=page.number,
                           merged=deepcopy(next(b for b in result if b.get('source_dialogue_frame'))))
        return result
    def restore(root,layout,header,width,column_width,para_style,char_style=None):
        if layout.get('source_dialogue_frame'):
            CAPTURE.update(document=deepcopy(root.getroottree().getroot()),root_path=path_to(root),
                header=deepcopy(header),layout=deepcopy(layout),page_width=width,column_width=column_width)
        count=original_restore(root,layout,header,width,column_width,para_style,char_style)
        if layout.get('source_dialogue_frame'):assert count==9,count
        return count
    dialogue.coalesce_dialogue_frames,dialogue.restore_dialogue_frame=coalesce,restore
    try:stats=write_pdf_structured_hwpx(SOURCE,FOLDER/'native.hwpx',native_math=True)
    finally:dialogue.coalesce_dialogue_frames,dialogue.restore_dialogue_frame=original_coalesce,original_restore
    (FOLDER/'write.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf8')
    assert stats['source_problem_count']==stats['output_problem_count']==25
    assert stats['source_pages']==6 and stats['output_source_page_numbers']==list(range(1,7))
    assert stats['source_text_preservation_ratio']==1 and stats['question_grouping']['inventory_matches']
    assert stats['full_page_images']==stats['text_visual_overlays']==stats['math_visual_overlays']==0
    return stats


def producer_negatives():
    cases=('flag_only','missing_pixel_proof','span_nan','record_nan','origin_nan','span_font_nan',
           'missing_raw','equation_font','source_text','source_frame','source_page_nan',
           'answer_blank','equation','nested_table','extra_control','missing_picture','width_nan','height_inf','negative_margin')
    def forbidden(*a,**k):raise AssertionError('invalid source allocated styles')
    for case in cases:
        document,header,layout=deepcopy(CAPTURE['document']),deepcopy(CAPTURE['header']),deepcopy(CAPTURE['layout'])
        root=follow(document,CAPTURE['root_path']);table=root.find(HP+'run/'+HP+'tbl')
        record=layout['source_typography']['lines'][0];span=record['spans'][0]
        if case=='flag_only':layout['source_dialogue_frame']=True
        elif case=='missing_pixel_proof':layout['source_dialogue_frame']['images'][0].pop('pixel_sha256')
        elif case=='span_nan':span['bbox']=[float('nan'),*span['bbox'][1:]]
        elif case=='record_nan':record['bbox_pt'][0]=float('nan')
        elif case=='origin_nan':span['chars'][0]['origin']=[float('nan'),1]
        elif case=='span_font_nan':span['size']=float('nan')
        elif case=='missing_raw':span.pop('chars')
        elif case=='equation_font':span['font']='HancomEQN'
        elif case=='source_text':record['text']+=' missing'
        elif case=='source_frame':layout['native_tables'][0]['bbox_pt'][0]-=5
        elif case=='source_page_nan':layout['source_page_width_pt']=float('nan')
        elif case=='answer_blank':layout['source_answer_blanks']=[{'bbox_pt':[1,2,3,4]}]
        elif case in ('equation','extra_control'):
            etree.SubElement(table.find('.//'+HP+'p/'+HP+'run'),HP+('equation' if case=='equation' else 'ctrl'))
        elif case=='nested_table':etree.SubElement(table.find('.//'+HP+'p/'+HP+'run'),HP+'tbl')
        elif case=='missing_picture':
            pic=table.find('.//'+HP+'pic');pic.getparent().remove(pic)
        elif case=='width_nan':table.find(HP+'sz').set('width','nan')
        elif case=='height_inf':table.find(HP+'sz').set('height','inf')
        elif case=='negative_margin':table.find(HP+'tr/'+HP+'tc/'+HP+'cellMargin').set('left','-1')
        before=etree.tostring(document),etree.tostring(header)
        assert dialogue.restore_dialogue_frame(root,layout,header,CAPTURE['page_width'],CAPTURE['column_width'],forbidden,forbidden)==0,case
        assert before==(etree.tostring(document),etree.tostring(header)),case
    return len(cases)


def coalescer_negatives(pdf):
    page=pdf[CAPTURE['source_page']]
    originals=CAPTURE['blocks'];lines=CAPTURE['source_lines']
    frame=fitz.Rect(CAPTURE['merged']['rect'])
    cases=('missing_line','wrong_line','missing_avatar','extra_avatar','missing_raw','equation_font','partial_rule')
    for case in cases:
        blocks,source_lines=deepcopy(originals),deepcopy(lines)
        piece=next(b for b in blocks if b.get('type')=='box' and dialogue._same(b['rect'],frame))
        if case=='missing_line':piece['lines'].pop()
        elif case=='wrong_line':piece['lines'][0]['spans'][0]['text']+=' wrong'
        elif case=='missing_avatar':blocks.remove(next(b for b in blocks if b.get('type')=='image' and frame.contains(fitz.Rect(b['image']['bbox']))))
        elif case=='extra_avatar':blocks.append(deepcopy(next(b for b in blocks if b.get('type')=='image' and frame.contains(fitz.Rect(b['image']['bbox'])))))
        elif case in ('missing_raw','equation_font'):
            span=piece['lines'][0]['spans'][0]
            if case=='missing_raw':span.pop('chars')
            else:span['font']='HancomEQN'
        active=page
        if case=='partial_rule':
            class Page:
                def __getattr__(self,key):return getattr(page,key)
                def get_drawings(self):return []
            active=Page()
        before=repr(blocks)
        result=dialogue.coalesce_dialogue_frames(blocks,active,source_lines)
        assert not any(b.get('source_dialogue_frame') for b in result),case
        assert repr(blocks)==before,case
    return len(cases)


def native_proof(path):
    header,roots,refs,media,root,table=packages(path)
    layout=CAPTURE['layout'];geometry=layout['native_tables'][0]
    with zipfile.ZipFile(path) as archive:
        assert dialogue.source_flow_dialogue_frame_table(table,root,header,refs,archive,SOURCE)
        pictures=table.findall('.//'+HP+'pic')
        for picture,image in zip(pictures,geometry['images']):
            # Table traversal is visual order: left bot, right user, left bot.
            ref=picture.find(HC+'img');payload=archive.read(refs[ref.get('binaryItemIDRef')])
            assert compare_source_crop(render_source_crop(SOURCE,5,fitz.Rect(image['bbox_pt'])),payload)['ok']
        assets=native_background_assets(table,header,refs,archive)
        assert len(assets)==1 and assets[0][0]==layout['source_dialogue_frame']['background']['sha256']
        with fitz.open(SOURCE) as pdf:
            page=pdf[CAPTURE['source_page']]
            frame=fitz.Rect(layout['source_dialogue_frame']['bbox_pt'])
            background=layout['source_dialogue_frame']['background']
            numbers=background['source_image_numbers']
            before=pdf.tobytes(no_new_id=True)
            assert dialogue.compose_proved_dialogue_background(page,frame,numbers)==assets[0][1]
            for invalid in (numbers[:-1],numbers+[numbers[-1]],numbers+[999],[],
                            [float(n) for n in numbers]):
                assert dialogue.compose_proved_dialogue_background(page,frame,invalid) is None
            assert dialogue.compose_proved_dialogue_background(page,frame+fitz.Rect(1,0,0,0),numbers) is None
            assert before==pdf.tobytes(no_new_id=True)
            record={**background,'role':'source_background_frame',
                    'bbox_px':[frame.x0,frame.y0,frame.width,frame.height]}
            texts={assets[0][0]:''.join(t.text or '' for t in table.iter(HP+'t'))}
            checked=inspect_source_images(pdf,{assets[0][0]:assets[0][1]},[record],background_texts=texts)
            pixel=checked['source_crop_checks'][0]
            assert pixel['ok'] and pixel['exact_bytes'] and pixel['native_background_proof']['ok'],pixel
        cases=('fractional_row','fractional_column','fractional_colspan','fractional_rowspan','leading_empty_image_p',
               'shifted_picture_cache','shifted_picture','wrong_avatar','missing_avatar','wrong_text','extra_paragraph',
               'missing_background','absolute_anchor','nonfinite_cell','oversized_cache')
        for case in cases:
            changed=deepcopy(root);target=follow(changed,path_to(table));cells=target.findall(HP+'tr/'+HP+'tc')
            avatar=next(c for c in cells if c.find('.//'+HP+'pic') is not None)
            picture=avatar.find('.//'+HP+'pic')
            if case.startswith('fractional_'):
                node,key={'fractional_row':(cells[0].find(HP+'cellAddr'),'rowAddr'),
                    'fractional_column':(cells[0].find(HP+'cellAddr'),'colAddr'),
                    'fractional_colspan':(cells[0].find(HP+'cellSpan'),'colSpan'),
                    'fractional_rowspan':(cells[0].find(HP+'cellSpan'),'rowSpan')}[case]
                node.set(key,str(float(node.get(key))+.5))
            elif case=='leading_empty_image_p':
                p=deepcopy(avatar.find(HP+'subList/'+HP+'p'));p.find(HP+'run').remove(p.find(HP+'run/'+HP+'pic'))
                etree.SubElement(p.find(HP+'run'),HP+'t').text='';avatar.find(HP+'subList').insert(0,p)
            elif case=='shifted_picture_cache':avatar.find(HP+'subList/'+HP+'p/'+HP+'linesegarray/'+HP+'lineseg').set('vertpos','300')
            elif case=='shifted_picture':picture.find(HP+'pos').set('vertOffset','300')
            elif case=='wrong_avatar':picture.find(HC+'img').set('binaryItemIDRef',target.findall('.//'+HP+'pic')[1].find(HC+'img').get('binaryItemIDRef'))
            elif case=='missing_avatar':picture.getparent().remove(picture)
            elif case=='wrong_text':next(t for t in target.iter(HP+'t') if t.text).text+=' wrong'
            elif case=='extra_paragraph':cells[0].find(HP+'subList').append(deepcopy(cells[0].find(HP+'subList/'+HP+'p')))
            elif case=='missing_background':target.set('borderFillIDRef',cells[0].get('borderFillIDRef'))
            elif case=='absolute_anchor':target.find(HP+'pos').set('vertRelTo','PAGE')
            elif case=='nonfinite_cell':cells[0].find(HP+'cellSz').set('width','nan')
            elif case=='oversized_cache':cells[0].find(HP+'subList/'+HP+'p/'+HP+'linesegarray/'+HP+'lineseg').set('horzsize','999999')
            before=etree.tostring(changed),etree.tostring(header)
            assert not dialogue.source_flow_dialogue_frame_table(target,changed,header,refs,archive,SOURCE),case
            assert before==(etree.tostring(changed),etree.tostring(header)),case
    paragraphs=[p for p in table.iter(HP+'p') if any((t.text or '').strip() for t in p.iter(HP+'t'))]
    assert len(paragraphs)==9
    assert [len(p.findall(HP+'linesegarray/'+HP+'lineseg')) for p in paragraphs]==[2,1,1,2,2,1,1,2,1]
    assert not table.findall('.//'+HP+'lineBreak') and not table.findall('.//'+HP+'equation')
    frame=fitz.Rect(geometry['bbox_pt']);scale=CAPTURE['page_width']/layout['source_page_width_pt']
    assert abs(float(table.find(HP+'sz').get('height'))-frame.height*scale)<=1
    # An already reconstructed semantic grid is an exact no-op.
    doc_copy,head_copy=deepcopy(root),deepcopy(header)
    tcopy=follow(doc_copy,path_to(table));host=tcopy.getparent().getparent()
    before=etree.tostring(doc_copy),etree.tostring(head_copy)
    assert dialogue.restore_dialogue_frame(host,layout,head_copy,CAPTURE['page_width'],CAPTURE['column_width'],lambda *_:None,lambda *_:None)==0
    assert before==(etree.tostring(doc_copy),etree.tostring(head_copy))
    return len(cases),media


def painted_bounds(svg,wanted):
    glyphs=[]
    for node in svg.iter(SVG+'text'):
        for char in ''.join(node.itertext()):
            if not char.isspace():glyphs.append((char,node))
    value=''.join(char for char,_ in glyphs)
    wanted=compact(wanted);start=value.index(wanted)
    glyphs=glyphs[start:start+len(wanted)]
    backgrounds=[node for node in svg.iter(SVG+'image') if
        hashlib.sha256(base64.b64decode(node.get('href').split(',',1)[1])).hexdigest()
        ==CAPTURE['layout']['source_dialogue_frame']['background']['sha256']]
    assert len(backgrounds)==1
    image=backgrounds[0];x,y,w,h=[float(image.get(key)) for key in ('x','y','width','height')]
    for char,node in glyphs:
        size=float(node.get('font-size'))
        transform=node.get('transform','')
        if transform:
            match=re.fullmatch(r'translate\(([-\d.eE]+),\s*([-\d.eE]+)\) scale\(([-\d.eE]+),\s*([-\d.eE]+)\)',transform)
            assert match,transform
            xx,yy,sx,sy=map(float,match.groups());size*=max(sx,sy)
        else:xx,yy=float(node.get('x')),float(node.get('y'))
        assert all(np.isfinite(v) for v in (xx,yy,size))
        assert x-2<=xx and xx+size<=x+w+2 and y-2<=yy-size and yy+size*.25<=y+h+2,(char,xx,yy)
    return len(glyphs)


def public_edits(native,media):
    original=rhwp.parse(str(native))
    pages=[]
    source_text=''.join(r['text'] for r in CAPTURE['layout']['source_typography']['lines'])
    for i in range(original.page_count):
        svg=etree.fromstring(original.render_svg(i).encode())
        value=''.join(svg.itertext())
        if compact(source_text) in compact(value):pages.append(i)
    assert len(pages)==1,'all conversation glyphs must paint on exactly one page'
    index=pages[0]
    svg=etree.fromstring(original.render_svg(index).encode())
    painted_count=painted_bounds(svg,source_text)
    (FOLDER/'native-dialogue.png').write_bytes(bytes(original.render_png(index)))
    with fitz.open(SOURCE) as pdf:
        pdf[5].get_pixmap(matrix=fitz.Matrix(1,1)).save(FOLDER/'source-page6.png')
    document=HwpxDocument.open(native)
    changed=False
    for section in document.sections:
        for draw in section.element.iter(HP+'drawText'):
            if draw.get('name')!='question:v1:q23':continue
            for p in draw.iter(HP+'p'):
                public=HwpxOxmlParagraph(p,section)
                if public.text.startswith('안녕하세요.'):
                    public.text=public.text.replace('안녕하세요.','안녕하세요!');changed=True;break
    assert changed
    small=FOLDER/'small-edited.hwpx';document.save_to_path(small)
    assert validate_package(small).ok and packages(small)[3]==media
    small_doc=rhwp.parse(str(small));assert small_doc.page_count==original.page_count
    pixels0=np.asarray(Image.open(io.BytesIO(bytes(original.render_png(index)))).convert('RGB'))
    pixels1=np.asarray(Image.open(io.BytesIO(bytes(small_doc.render_png(index)))).convert('RGB'))
    changed_pixels=int(np.count_nonzero(np.any(pixels0!=pixels1,axis=-1)))
    assert 0<changed_pixels<500,changed_pixels
    reopened=FOLDER/'small-reopened.hwpx';HwpxDocument.open(small).save_to_path(reopened)
    assert etree.tostring(packages(small)[5])==etree.tostring(packages(reopened)[5])
    # Grow the last semantic answer, never introduce a cell per printed row.
    document=HwpxDocument.open(native);target=None
    for section in document.sections:
        for draw in section.element.iter(HP+'drawText'):
            if draw.get('name')!='question:v1:q23':continue
            target=next(p for p in draw.iter(HP+'p') if ''.join(p.itertext()).startswith('(마)'))
            before=HwpxOxmlParagraph(target,section).text
            addition=' 편집 조건을 확인합니다.'*8+' DIALOGUE_EDIT_END'
            HwpxOxmlParagraph(target,section).text=before+addition
    assert target is not None
    growth=FOLDER/'large-edited.hwpx';document.save_to_path(growth)
    assert validate_package(growth).ok
    table=packages(native)[5];grown=packages(growth)[5]
    assert grown.get('rowCnt')=='5' and grown.get('colCnt')=='3'
    assert float(grown.find(HP+'sz').get('height'))>float(table.find(HP+'sz').get('height'))
    assert packages(growth)[3]==media
    rendered=rhwp.parse(str(growth));svgs=[etree.fromstring(rendered.render_svg(i).encode()) for i in range(rendered.page_count)]
    all_text=''.join(''.join(s.itertext()) for s in svgs)
    assert 'DIALOGUE_EDIT_END' in compact(all_text)
    painted_growth=painted_bounds(next(s for s in svgs if compact(source_text+addition) in compact(''.join(s.itertext()))),source_text+addition)
    reopened=FOLDER/'large-reopened.hwpx';HwpxDocument.open(growth).save_to_path(reopened)
    assert etree.tostring(packages(growth)[5])==etree.tostring(packages(reopened)[5])
    return {'native_pages':original.page_count,'dialogue_native_page':index+1,'small_edit_changed_pixels':changed_pixels,
            'painted_dialogue_glyphs_within_frame':painted_count,'large_edit_painted_glyphs_within_frame':painted_growth,
            'large_edit_grows':True,'small_large_reopen_stable':True,'media_unchanged':True}


def main():
    from scripts.verify_september_exam_matrix import code_fingerprint
    code_before=code_fingerprint()['sha256']
    with source_fixture()[0] as pdf:
        stats=capture_write()
        negatives=producer_negatives()+coalescer_negatives(pdf)
    consumer,media=native_proof(FOLDER/'native.hwpx')
    edits=public_edits(FOLDER/'native.hwpx',media)
    code_after=code_fingerprint()['sha256']
    assert code_before==code_after,'product code changed during the actual-source regression'
    result={'ok':True,'code_before':code_before,'code_after':code_after,
        'source_pages':6,'source_questions':25,'source_text_lines':13,
        'semantic_paragraphs':9,'native_grid':[5,3],'avatars':3,'source_decoration_strips':13,
        'native_frame_height':18483,'producer_negatives':negatives,'consumer_negatives':consumer,
        'source_text_preservation':stats['source_text_preservation_ratio'],'quality_pass_claimed':False,**edits}
    (FOLDER/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print('NATIVE_DIALOGUE_FRAMES_OK '+json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
