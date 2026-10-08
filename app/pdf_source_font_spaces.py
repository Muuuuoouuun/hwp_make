"""Prove actual embedded PDF font space advances for a short terminal row."""
from __future__ import annotations

import hashlib
import math
import re
import struct

def integer(value,maximum=65535):
    if isinstance(value,bool) or not isinstance(value,int) or not 0 <= value <= maximum:
        raise ValueError('invalid bounded integer')
    return value

def ttf_space_width(data,gid):
    """Read only bounded SFNT head/maxp/hhea/hmtx data; no Unicode guess."""
    if not isinstance(data,bytes) or not 12 <= len(data) <= 16*1024*1024 or data[:4] not in (b'\x00\x01\x00\x00',b'true'):
        raise ValueError('unsupported or oversized TrueType program')
    count=struct.unpack_from('>H',data,4)[0]
    if not 1 <= count <= 128 or 12+16*count > len(data):
        raise ValueError('invalid SFNT directory')
    tables={}
    for index in range(count):
        tag,checksum,offset,length=struct.unpack_from('>4sIII',data,12+16*index)
        if tag in tables or offset%4 or offset < 12+16*count or offset+length > len(data):
            raise ValueError('invalid SFNT table bounds')
        tables[tag]=(offset,length)
    for tag,size in ((b'head',54),(b'maxp',6),(b'hhea',36),(b'hmtx',4)):
        if tag not in tables or tables[tag][1] < size:
            raise ValueError('missing or short font metrics')
    head,maxp,hhea,hmtx=(tables[tag][0] for tag in (b'head',b'maxp',b'hhea',b'hmtx'))
    if struct.unpack_from('>I',data,head+12)[0] != 0x5F0F3CF5:
        raise ValueError('invalid head magic')
    units=struct.unpack_from('>H',data,head+18)[0]
    glyphs=struct.unpack_from('>H',data,maxp+4)[0]
    metrics=struct.unpack_from('>H',data,hhea+34)[0]
    if not 16 <= units <= 16384 or not 1 <= metrics <= glyphs or not 0 <= integer(gid) < glyphs:
        raise ValueError('invalid glyph or metric count')
    if 4*metrics+2*(glyphs-metrics) > tables[b'hmtx'][1]:
        raise ValueError('truncated horizontal metrics')
    offset=hmtx+4*min(gid,metrics-1)
    advance=struct.unpack_from('>H',data,offset)[0]
    if advance <= 0 or abs(advance/units-.25) > 1e-9:
        raise ValueError('actual glyph program is not quarter em')
    return {'units_per_em':units,'advance_width':advance,'gid':gid,'glyph_count':glyphs,
            'metric_count':metrics,'head_units_offset':head+18,'hmtx_advance_offset':offset,
            'program_bytes':len(data),'program_sha256':hashlib.sha256(data).hexdigest()}

def xref(document,owner,key):
    kind,value=document.xref_get_key(owner,key)
    match=re.fullmatch(r'([1-9]\d*) 0 R',value or '')
    if kind != 'xref' or not match or int(match[1]) >= document.xref_length():
        raise ValueError('missing actual PDF reference')
    return int(match[1])

def cmap_space_cid(data):
    """Conservative bounded ToUnicode bfchar/bfrange reader (16-bit CIDs)."""
    if not isinstance(data,bytes) or not 1 <= len(data) <= 131072:
        raise ValueError('missing or oversized actual CMap')
    value=re.sub(r'%[^\r\n]*','',data.decode('ascii'))
    if '/CMapType 2' not in value or len(re.findall(r'begincodespacerange',value)) != 1:
        raise ValueError('unsupported actual ToUnicode map')
    mapping={}
    def add(cid,unicode):
        integer(cid)
        if cid in mapping or not 0 <= unicode <= 0x10ffff or 0xd800 <= unicode <= 0xdfff or len(mapping) >= 4096:
            raise ValueError('ambiguous or oversized actual CMap')
        mapping[cid]=unicode
    for count,body in re.findall(r'(\d+)\s+beginbfchar(.*?)endbfchar',value,re.S):
        pairs=re.findall(r'<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4,8})>',body)
        if len(pairs) != int(count):raise ValueError('unsupported bfchar')
        for cid,unicode in pairs:add(int(cid,16),int(unicode,16))
    for count,body in re.findall(r'(\d+)\s+beginbfrange(.*?)endbfrange',value,re.S):
        triples=re.findall(r'<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4,8})>',body)
        if len(triples) != int(count):raise ValueError('unsupported bfrange')
        for start,end,unicode in triples:
            start,end,unicode=int(start,16),int(end,16),int(unicode,16)
            if not start <= end or end-start > 4096:raise ValueError('oversized range')
            for offset,cid in enumerate(range(start,end+1)):add(cid,unicode+offset)
    matches=[cid for cid,unicode in mapping.items() if unicode == 32]
    if len(matches) != 1:raise ValueError('U+0020 does not have one actual CID')
    return matches[0]

def pdf_cid_width(value,cid):
    """Read a bounded PDF CID W array; require an explicit unique width."""
    if len(value) > 131072:raise ValueError('oversized actual widths')
    tokens=re.findall(r'\[|\]|[-+]?\d+(?:\.\d+)?',value)
    if not tokens or tokens[0] != '[' or tokens[-1] != ']':raise ValueError('unsupported widths')
    widths={};index=1
    def add(code,width):
        integer(code)
        if code in widths or len(widths) >= 4096 or not math.isfinite(width) or not 0 < width <= 2000:
            raise ValueError('invalid or ambiguous actual width')
        widths[code]=width
    while index < len(tokens)-1:
        start=int(tokens[index]);index+=1
        if tokens[index] == '[':
            index+=1;code=start
            while tokens[index] != ']':add(code,float(tokens[index]));code+=1;index+=1
            index+=1
        else:
            end=int(tokens[index]);width=float(tokens[index+1]);index+=2
            if not start <= end or end-start > 4096:raise ValueError('invalid width range')
            for code in range(start,end+1):add(code,width)
    if index != len(tokens)-1 or cid not in widths or abs(widths[cid]/1000-.25) > 1e-9:
        raise ValueError('actual PDF space width is not explicit quarter em')
    return widths[cid]

def face(value):
    return re.sub(r'^[A-Z]{6}\+','',value)


def source_terminal_space_positions(document, page, rows, source_lines):
    """Return only actual terminal ASCII-space cursors after complete proof.

    The caller first proves every supplied body/raw glyph, regular Times
    style, quarter-em bbox, and actual terminal origin advance. This gate
    additionally binds U+0020 to one actual source resource/CID/GID and the
    embedded TrueType advance. No question number or text literal is used.
    """
    from .pdf_layout_writer import _pdf_output_text
    from .pdf_source_question_body import (source_question_body_complete,
                                           split_source_question_body)

    try:
        candidates=[]
        for candidate in source_lines:
            groups=split_source_question_body([candidate,*rows],page=page,area_hint='영어 영역')
            if len(groups)==2 and groups[1]==rows:
                candidates.append(groups[0])
        if (len(candidates)!=1 or not source_question_body_complete(
                page,candidates[0],rows,source_lines=source_lines)):
            return set()
        size=rows[-1]['spans'][0]['size']
        right=max(row['bbox'][2] for row in rows[:-1])
        if rows[-1]['bbox'][2]-rows[-1]['bbox'][0] >= (right-rows[1]['bbox'][0])*.5:
            return set()
        raw_face=rows[0]['spans'][0]['font']
        resources=[font for font in page.get_fonts(full=True) if face(font[3])==face(raw_face)]
        if len(resources)!=1:return set()
        font_xref,extension,font_type,basefont,resource,*owner=resources[0]
        if extension!='ttf' or font_type!='Type0':return set()
        if document.xref_get_key(font_xref,'Encoding')!=('name','/Identity-H'):return set()
        kind,value=document.xref_get_key(font_xref,'DescendantFonts')
        descendant=re.fullmatch(r'\[\s*([1-9]\d*) 0 R\s*\]',value or '')
        if kind!='array' or not descendant:return set()
        descendant=int(descendant[1])
        if document.xref_get_key(descendant,'CIDToGIDMap')!=('name','/Identity'):return set()
        cid=cmap_space_cid(document.xref_stream(xref(document,font_xref,'ToUnicode')))
        kind,widths=document.xref_get_key(descendant,'W')
        if kind!='array':return set()
        pdf_cid_width(widths,cid)
        descriptor=xref(document,descendant,'FontDescriptor')
        program_xref=xref(document,descriptor,'FontFile2')
        name,extension,kind,program=document.extract_font(font_xref)
        if extension!='ttf' or face(name)!=face(raw_face):return set()
        # The extracted program must be exactly the referenced actual stream.
        if program!=document.xref_stream(program_xref):return set()
        metrics=ttf_space_width(program,cid)
        traces=[trace for trace in page.get_texttrace() if face(trace.get('font',''))==face(raw_face)
                and trace.get('wmode')==0 and tuple(trace.get('dir',()))==(1.0,0.0)
                and trace.get('type')==0 and trace.get('opacity')==1.0]
        for row in rows:
            for span in row['spans']:
                for char in span['chars']:
                    if char['c']!=' ':continue
                    matches=[(trace,value) for trace in traces for value in trace['chars']
                             if value[0]==32 and max(abs(a-b) for a,b in zip(value[2],char['origin']))<.0001]
                    if (len(matches)!=1 or matches[0][1][1]!=cid
                            or abs(matches[0][0]['size']-span['size'])>.0001
                            or matches[0][0]['flags']!=span['flags']):return set()
        cursor=sum(sum(not c.isspace() for c in _pdf_output_text(char['c']))
                   for row in rows[:-1] for span in row['spans'] for char in span['chars'])
        positions=set();advances=[]
        for span in rows[-1]['spans']:
            for index,char in enumerate(span['chars']):
                value=_pdf_output_text(char['c'])
                if value==' ':
                    if index+1>=len(span['chars']):return set()
                    following=span['chars'][index+1]
                    advance=(following['origin'][0]-char['origin'][0])/span['size']
                    if (not math.isfinite(advance) or abs(advance-metrics['advance_width']/metrics['units_per_em'])>.01
                            or abs(following['origin'][1]-char['origin'][1])>.0001):return set()
                    positions.add(cursor);advances.append(advance)
                cursor+=sum(not c.isspace() for c in value)
        if not 1<=len(advances)<=2 or len(positions)!=len(advances):return set()
        return positions
    except (ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError,
            struct.error,UnicodeError,RuntimeError,OSError):
        return set()
