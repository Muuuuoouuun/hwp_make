"""Actual mixed source resource/program/trace guards through the product helper."""
from copy import deepcopy
from pathlib import Path
import argparse,hashlib,json,re,struct,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import fitz
from app import pdf_source_body_spaces as product
from app.pdf_native_content import extract_native_content
from app.pdf_source_font_spaces import face,xref
class PageProxy:
    def __init__(self,page,mode):self.page,self.mode=page,mode
    def __getattr__(self,name):return getattr(self.page,name)
    def get_fonts(self,*args,**kwargs):
        fonts=self.page.get_fonts(*args,**kwargs)
        return fonts+fonts if self.mode=='ambiguous_resource' else fonts
    def get_texttrace(self):
        traces=deepcopy(self.page.get_texttrace())
        if not self.mode.startswith('trace_'):return traces
        key=self.mode.removeprefix('trace_')
        for trace in traces:
            if face(trace.get('font',''))!='TimesNewRoman':continue
            if key in ('type','opacity','wmode','dir','flags','size'):
                trace[key]={'type':1,'opacity':.5,'wmode':1,'dir':(0.,1.),'flags':6,'size':trace['size']+1}[key]
            elif key=='gid':trace['chars']=[(c[0],4 if c[0]==32 else c[1],*c[2:]) for c in trace['chars']]
        return traces
class DocumentProxy:
    def __init__(self,document,mode):self.document,self.mode=document,mode;self.programs={}
    def __getattr__(self,name):return getattr(self.document,name)
    def __len__(self):return len(self.document)
    def __getitem__(self,index):return PageProxy(self.document[index],self.mode)
    def __enter__(self):return self
    def __exit__(self,*args):self.document.close()
    def xref_get_key(self,owner,key):
        if self.mode=='width_not_quarter' and key=='W':return ('array','[3 [300]]')
        if self.mode=='encoding' and key=='Encoding':return ('name','/WinAnsiEncoding')
        if self.mode=='cid_gid' and key=='CIDToGIDMap':return ('name','/Other')
        return self.document.xref_get_key(owner,key)
    def program(self,reference):
        if reference not in self.programs:
            value=bytearray(self.document.xref_stream(reference));count=struct.unpack_from('>H',value,4)[0]
            tables={bytes(value[12+i*16:16+i*16]):struct.unpack_from('>I',value,20+i*16)[0] for i in range(count)}
            offset=tables[b'hmtx']+3*4;struct.pack_into('>H',value,offset,520);self.programs[reference]=bytes(value)
        return self.programs[reference]
    def xref_stream(self,reference):
        kind=self.document.xref_get_key(reference,'Length1')
        value=self.document.xref_stream(reference)
        if self.mode=='cmap_invalid' and b'/CMapType 2' in value:return b'invalid'
        if self.mode in ('program_mismatch','program_not_quarter') and value[:4]==b'\x00\x01\x00\x00':return self.program(reference)
        return value
    def extract_font(self,reference):
        name,ext,kind,program=self.document.extract_font(reference)
        if self.mode=='program_not_quarter' and face(name)=='TimesNewRoman':
            descendant=int(re.search(r'(\d+)\s+0\s+R',self.document.xref_get_key(reference,'DescendantFonts')[1])[1])
            program=self.program(xref(self.document,xref(self.document,descendant,'FontDescriptor'),'FontFile2'))
        return name,ext,kind,program

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'data/external_exam_qa/2027_kice_september_high3/english.pdf')
    parser.add_argument('--output',type=Path,default=ROOT/'tmp/september-exam-matrix/mixed-terminal-source-body-regression/font-guards')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    fingerprint=lambda:{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'app').rglob('*.py'))}
    before=fingerprint();items,_=extract_native_content(args.source,max_pages=3,area_hint='영어 영역');fixtures={i['layout']['question_number']:i['layout'] for i in items if i['layout'].get('source_question_body')}
    old_open=product.fitz.open;checks=[]
    try:
        for number,count in ((21,5),(24,1)):
            assert len(product.source_body_space_styles(fixtures[number]))==count
            checks.append({'question':number,'case':'actual_resource_program_trace','passed':True})
            for mode in ('ambiguous_resource','width_not_quarter','encoding','cid_gid','cmap_invalid','program_mismatch','program_not_quarter',
                         'trace_type','trace_opacity','trace_wmode','trace_dir','trace_flags','trace_size','trace_gid'):
                product.fitz.open=lambda *args,_mode=mode,**kwargs:DocumentProxy(old_open(*args,**kwargs),_mode)
                try:result=product.source_body_space_styles(fixtures[number])
                finally:product.fitz.open=old_open
                assert result=={},(number,mode,result)
                checks.append({'question':number,'case':mode,'passed':True});print('PASS',number,mode,flush=True)
        assert fingerprint()==before
        report={'ok':True,'positive_cases':2,'negative_cases':len(checks)-2,'checks':checks,'app_stable':True}
    finally:product.fitz.open=old_open
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print('MIXED_TERMINAL_FONT_GUARDS',json.dumps(report),flush=True)
    return 0
if __name__=='__main__':raise SystemExit(main())
