"""Exact supported Latin advances for source-wrapped cache validation only.

The Haansoft Batang ranges are the bundled rhwp-core MIT font metrics
(ce45231c0c88efd5397d8fae9cd7d73de915095d, FONT_6_LATIN_0..2,
1024 units/em). Unknown families/characters fail closed; this is not a new
font fallback or a replacement for the normal editor's text layout.
"""
import math

from .paragraph_floats import HP, HH, is_wrapped_picture
from .paragraph_spacing import paragraph_indentation, line_left_margin

_RANGES = (
    (0x20, (
        341,426,426,853,640,938,853,256,512,512,512,853,298,853,298,341,597,597,597,
        597,597,597,597,597,597,597,341,341,853,853,853,512,1024,768,682,682,725,682,
        640,725,768,384,469,768,640,938,768,725,640,725,682,640,768,768,725,981,682,
        682,640,512,341,512,1024,512,597,512,554,512,554,554,384,554,554,298,298,554,
        298,853,554,554,554,554,426,512,384,554,554,810,597,597,469,597,597,597,810)),
    (0xA0, (
        512,426,512,512,512,682,256,512,512,802,480,512,804,384,802,384,447,831,368,
        368,341,554,640,341,341,384,480,512,575,575,575,512,768,768,768,768,768,768,
        1024,690,682,682,682,682,384,384,384,384,725,768,725,725,725,725,725,831,725,
        768,768,768,768,682,682,640,512,512,512,512,512,512,865,532,554,554,554,554,
        298,298,298,298,554,554,554,554,554,554,554,831,554,554,554,554,554,597,554,597)),
    (0x2000, (
        512,512,512,512,512,512,512,512,512,512,512,512,512,512,512,512,267,369,441,
        441,881,1024,341,561,276,276,276,276,379,379,379,379,492,492,474,477,178,580,
        850,178,512,512,512,512,512,512,512,512,1024,1024,276,447,565,276,485,565,
        404,332,332,780,452,492,641,823,823,365,1024,229,752,328,328,512,817,817,467,
        640,640,640,512,512,823,492,492,512,512,512,512,512,512,512,512,512,512,512,
        512,512,1024,1024,1024,1024,512,512,512,512,512,512,512,512,512,512,512,512)),
)


def _advance(char, style, fonts):
    ref=style.find(HH+'fontRef')
    languages={'hangul','latin','hanja','japanese','other','symbol','user'}
    # These ranges have one family in every script slot. Requiring that same
    # resolved family avoids guessing how a renderer classifies punctuation.
    if ref is None or set(ref.attrib)!=languages or any(fonts.get((lang.upper(),font))!='Haansoft Batang'
                          for lang,font in ref.attrib.items()):
        raise ValueError('unsupported wrapped cache font')
    height=float(style.get('height'))
    ratio=style.find(HH+'ratio');spacing=style.find(HH+'spacing')
    if ratio is None or spacing is None or set(ratio.attrib)!=languages or set(spacing.attrib)!=languages:
        raise ValueError('unsupported wrapped cache script metrics')
    ratios={float(v) for v in ratio.attrib.values()};spacings={float(v) for v in spacing.attrib.values()}
    if (not math.isfinite(height) or height<=0 or len(ratios)!=1 or len(spacings)!=1):
        raise ValueError('unsupported wrapped cache metrics')
    ratio=ratios.pop()/100;tracking=spacings.pop()*height/100
    if not all(math.isfinite(v) for v in (ratio,tracking)) or ratio<=0:
        raise ValueError('invalid wrapped cache metrics')
    code=ord(char)
    if char==' ': base=height*.5
    else:
        width=next((values[code-start] for start,values in _RANGES
                    if start<=code<start+len(values)),None)
        if width is None: raise ValueError('unsupported wrapped cache character')
        if code in (0x2018,0x2019,0x2027,0xB7) and width>=1024: width=307
        elif 0x2018<=code<=0x2027 and width>=1024: width=512
        base=math.floor(width*height/1024)
    natural=base*ratio
    return max(natural+tracking,natural*.5), natural


def cached_line_texts(paragraph):
    """Read complete native slices at valid UTF-16/control boundaries."""
    try:
        units=[];offset=0;boundaries={0:0}
        for run in paragraph.findall(HP+'run'):
            for child in run:
                if child.tag==HP+'t' and not len(child):
                    for char in child.text or '':
                        units.append(char);offset+=len(char.encode('utf-16-le'))//2
                        boundaries[offset]=len(units)
                elif is_wrapped_picture(child):
                    offset+=8;boundaries[offset]=len(units)
                else: return None
        starts=[int(line.get('textpos')) for line in paragraph.findall(HP+'linesegarray/'+HP+'lineseg')]
        if (not starts or starts[0]!=0 or any(x not in boundaries or x>=offset for x in starts)
            or any(b<=a for a,b in zip(starts,starts[1:]))): return None
        return [''.join(units[boundaries[a]:boundaries[b] if b<offset else len(units)])
                for a,b in zip(starts,starts[1:]+[offset])]
    except (AttributeError,ValueError,TypeError,UnicodeError):
        return None


def cached_slices_fit(paragraph, para_styles, char_styles):
    """Prove full UTF-16 coverage and each cached slice's native minimum width.

    JUSTIFY can shrink interior spaces by at most half their native advance.
    This mirrors the existing renderer's lower bound, never an arbitrary fit
    tolerance. Quantization permits two HWP units at the final comparison.
    """
    try:
        header=next(iter(char_styles.values())).getroottree().getroot()
        fonts={(face.get('lang'),font.get('id')):font.get('face')
               for face in header.iter(HH+'fontface') for font in face.findall(HH+'font')}
        units=[];offset=0;boundaries={0:0}
        for run in paragraph.findall(HP+'run'):
            style=char_styles.get(run.get('charPrIDRef'))
            if style is None: return False
            for child in run:
                if child.tag==HP+'t' and not len(child):
                    for char in child.text or '':
                        advance,base=_advance(char,style,fonts)
                        units.append((char,advance,base))
                        offset+=len(char.encode('utf-16-le'))//2
                        boundaries[offset]=len(units)
                elif is_wrapped_picture(child):
                    units.append(('\ufffc',0,0));offset+=8;boundaries[offset]=len(units)
                else: return False
        lines=paragraph.findall(HP+'linesegarray/'+HP+'lineseg')
        starts=[int(l.get('textpos')) for l in lines]
        if not starts or starts[0]!=0 or any(x not in boundaries or x>=offset for x in starts): return False
        style=para_styles.get(paragraph.get('paraPrIDRef'))
        justify=style.find(HH+'align').get('horizontal')=='JUSTIFY'
        for i,line in enumerate(lines):
            first=boundaries[starts[i]];last=boundaries[starts[i+1]] if i+1<len(lines) else len(units)
            if first>=last: return False
            # A source word cannot silently lose its first letter to the
            # preceding line. Real hyphens and soft hyphens remain literal.
            if i and not (units[first-1][0].isspace() or units[first-1][0] in '-\u00ad'):
                return False
            visible=units[first:last]
            while visible and visible[-1][0].isspace(): visible=visible[:-1]
            if not visible: return False
            natural=sum(u[1] for u in visible)
            if justify and i+1<len(lines):
                # The renderer uses the first text style's base space width.
                # Per-space lower bounds are no less restrictive for the
                # uniform-family source runs supported by this validator.
                natural-=sum(u[2]*.5 for u in visible if u[0]==' ')
            # Proved wrapped caches encode the effective text width. Native
            # paragraph margins/indent have already been subtracted once.
            available=float(line.get('horzsize'))
            if not math.isfinite(available) or available<=0 or natural>available+2: return False
        return True
    except (AttributeError,ValueError,TypeError,KeyError,IndexError,StopIteration,UnicodeError):
        return False
