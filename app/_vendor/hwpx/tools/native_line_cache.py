"""Stage one optional current native line-cache plan without replacing public runs.

Return False on unsupported or failed metric plans. The caller then runs its
unchanged conservative cache builder. No document serialization is used.
"""
from copy import deepcopy
import hashlib, math
from lxml import etree
from .paragraph_spacing import paragraph_indentation, line_left_margin, paragraph_tab_stops
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"

def _number(node, name, default=0):
    return float(node.get(name, default)) if node is not None else float(default)


def _fits_trailing_underline_tab(provider,index,advance,usable,line_start):
    """Closing TAB of one complete native underlined label interval.

    Exact current style-ID coalescing must yield TAB + nonspace label + TAB.
    The complete interval stays on the current line and is followed by a
    distinct-style whitespace/TAB boundary. Only its actually measured final
    blank advance may use the current usable interval beyond the normal97%
    word-wrap margin. No saved/source cache width or coordinate is read.
    """
    units=provider.units
    if not 0<index<len(units) or units[index][1]!='\t' or not math.isfinite(advance) or not 0<=advance<=usable:return False
    sid=units[index][0]
    if index+1>=len(units) or units[index+1][0]==sid or not units[index+1][1].isspace():return False
    first=index
    while first and units[first-1][0]==sid:first-=1
    if first<line_start or units[first][1]!='\t' or index-first<2:return False
    if any(unit[1].isspace() for unit in units[first+1:index]):return False
    underline=provider.styles[sid].find(HH+'underline')
    return underline is not None and dict(underline.attrib)=={'type':'BOTTOM','shape':'SOLID','color':'#000000'}


def _closing_label_separator(provider, index, advance, usable, line_start):
    """Consume only one unpainted plain ASCII separator after a fitted label.

    Current XML/style/font and actual native advance remain authoritative.
    TAB + nonspace label + TAB must already fit; distinct plain style differs
    only in underline/ID, and exactly one ASCII space precedes new ink. The
    blank may cross the ordinary wrap margin; no text or underline may do so.
    """
    units=provider.units
    if not line_start<index<len(units)-1 or units[index][1]!=' ' or units[index+1][1].isspace():return False
    if units[index-1][1]!='\t' or not math.isfinite(advance) or not 0<=advance<=usable:return False
    if not _fits_trailing_underline_tab(provider,index-1,advance,usable,line_start):return False
    underlined=provider.styles[units[index-1][0]];plain=provider.styles[units[index][0]]
    underline=plain.find(HH+'underline')
    if underline is None or underline.get('type')!='NONE':return False
    def metrics(style):
        node=deepcopy(style);node.attrib.pop('id',None)
        child=node.find(HH+'underline')
        if child is not None:node.remove(child)
        return etree.tostring(node,method='c14n')
    return metrics(plain)==metrics(underlined)

def _staged_native_cache(p, width, styles, paras, *, provider=None, wrap_context=None, leading=None):
    if provider is None or wrap_context is not None:
        return False
    staged = deepcopy(p)
    try:
        if not provider.paragraph_digest == hashlib.sha256(etree.tostring(p, encoding='utf-8')).hexdigest():
            raise ValueError('unsupported current native XML or metric')
        if not provider.header_digest == hashlib.sha256(etree.tostring(provider.header, encoding='utf-8')).hexdigest():
            raise ValueError('unsupported current native XML or metric')
        if not all((etree.tostring(styles[sid], encoding='utf-8') == etree.tostring(provider.styles[sid], encoding='utf-8') for sid in {u[0] for u in provider.units})):
            raise ValueError('unsupported current native XML or metric')
        current_para = next((c for c in provider.header.iter(HH + 'paraPr') if c.get('id') == p.get('paraPrIDRef')))
        if not etree.tostring(paras[p.get('paraPrIDRef')], encoding='utf-8') == etree.tostring(current_para, encoding='utf-8'):
            raise ValueError('unsupported current native XML or metric')
        units = provider.units
        tabs = {}
        lines = []
        start = 0
        top = 0
        left, right, indent = paragraph_indentation(p, paras)
        stops = paragraph_tab_stops(p, paras)
        style = paras[p.get('paraPrIDRef')]
        spacing = style.find('.//' + HH + 'lineSpacing')
        percent = _number(spacing, 'value', 150) if spacing is None or spacing.get('type') == 'PERCENT' else 150
        while start < len(units):
            margin = line_left_margin(left, indent, len(lines))
            usable = width - margin - right
            if not usable > 0:
                raise ValueError('unsupported current native XML or metric')
            end = start
            space = None
            consumed_separator = False
            while end < len(units):
                if units[end][1] == '\t':
                    before = provider.before_tab(start, end, tabs)
                    current = margin + before
                    stop = next((s for s in stops if s > current + 1), (int(current // 3600) + 1) * 3600)
                    tabs[end] = min(65535, max(1, round(stop - current)))
                amount = provider.advance(start, end + 1, tabs)
                if end > start and amount > usable * 0.97 and not _fits_trailing_underline_tab(provider, end, amount, usable, start):
                    before = provider.advance(start, end, tabs)
                    if _closing_label_separator(provider,end,before,usable,start):
                        # Include that one nonpainted delimiter in this row's
                        # UTF16 coverage. The next ink starts at its own rail.
                        end += 1
                        space = end
                        consumed_separator = True
                    break
                end += 1
                if units[end - 1][1].isspace():
                    space = end
            if end < len(units) and space is not None and (space > start):
                end = space
            if not end > start:
                raise ValueError('unsupported current native XML or metric')
            tabs = {i: v for i, v in tabs.items() if i < end}
            for index in range(start, end):
                if units[index][1] == '\t':
                    before = provider.before_tab(start, index, tabs)
                    current = margin + before
                    stop = next((s for s in stops if s > current + 1), (int(current // 3600) + 1) * 3600)
                    tabs[index] = min(65535, max(1, round(stop - current)))
            advance = provider.advance(start, end, tabs)
            if consumed_separator:
                full_advance=advance
                advance=provider.advance(start,end-1,tabs)
                separator=full_advance-advance
                if not (math.isfinite(separator) and 0<separator<=units[end-1][3]
                        and _closing_label_separator(provider,end-1,advance,usable,start)):
                    raise ValueError('unsupported trailing label separator advance')
            if not (math.isfinite(advance) and 0 <= advance <= usable):
                raise ValueError('unsupported current native XML or metric')
            height = max((u[3] for u in units[start:end]))
            step = max(height, height * percent / 100)
            lines.append((start, end, height, step, advance))
            start = end
        old = staged.find(HP + 'linesegarray')
        if old is not None:
            staged.remove(old)
        cache = etree.SubElement(staged, HP + 'linesegarray')
        offset = top = 0
        from .native_gap_state import step as native_gap_step
        for index,(start, end, height, step, advance) in enumerate(lines):
            step = native_gap_step(height,step,index,len(lines),leading)
            etree.SubElement(cache, HP + 'lineseg', textpos=str(offset), vertpos=str(round(top)), vertsize=str(height), textheight=str(height), baseline=str(round(height * 0.85)), spacing=str(round(step - height)), horzpos='0', horzsize=str(round(width)), flags='393216')
            offset += sum((u[2] for u in units[start:end]))
            top += step
        for index, tab in zip((i for i, u in enumerate(units) if u[1] == '\t'), staged.findall(HP + 'run/' + HP + 'tab')):
            tab.set('width', str(tabs[index]))
        provider.finish_plan()
        current_tabs = p.findall(HP + 'run/' + HP + 'tab')
        planned_tabs = staged.findall(HP + 'run/' + HP + 'tab')
        if len(current_tabs) != len(planned_tabs):
            raise ValueError('current TAB ownership changed before commit')
        planned_cache = staged.find(HP + 'linesegarray')
        if planned_cache is None:
            raise ValueError('missing staged native cache')
        for current, planned in zip(current_tabs, planned_tabs):
            current.set('width', planned.get('width'))
        old_cache = p.find(HP + 'linesegarray')
        if old_cache is not None:
            p.remove(old_cache)
        p.append(planned_cache)
        return True
    except Exception:
        return False

def cache_lines_native(paragraph, width, styles, para_styles, *, native_advance=None, wrap_context=None, leading=None):
    """Use one current immutable metric transaction, or exact conservative flow.

 Factory caller supplies a current-header-bound provider per paragraph. The
 staged row plan validates original text/header again immediately before commit.
 Unsupported and failed native paths never leave partial cache/TAB writes.
 """
    if native_advance is None or wrap_context is not None:
        return False
    try:
        native_advance.begin_plan()
    except Exception:
        return False
    try:
        return _staged_native_cache(paragraph, width, styles, para_styles, provider=native_advance, wrap_context=wrap_context, leading=leading)
    finally:
        native_advance._cancel_plan()
