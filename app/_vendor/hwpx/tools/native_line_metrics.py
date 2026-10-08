"""Optional native current-line metric backend, no document serialization.

Plain fonts/styles only, immutable current XML context, exact UTF16 boundaries,
renderer-native style/language segmentation, shared bounded operation budget.
Missing/unsupported context is None; a metric failure must cause the caller to
discard its entire staged plan and use its original conservative cache builder.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib, io, math, re, time, zipfile, unicodedata
from lxml import etree
from hwpx.templates import _generated_blank_document_bytes
from hwpx.tools.paragraph_spacing import paragraph_tab_stops
HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
SVG = '{http://www.w3.org/2000/svg}'
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
# Bound XML TAB volume independently of native unit/probe/time budgets.
_MAX_PLAIN_TABS = 16

def _xml_int(value, *, signed=False):
    pattern = '-?(?:0|[1-9][0-9]*)' if signed else '(?:0|[1-9][0-9]*)'
    if not (isinstance(value, str) and re.fullmatch(pattern, value) is not None):
        raise ValueError('unsupported current native XML or metric')
    return int(value)

def _current_xml_metrics(p, header):
    known = {'charPr', 'charProperties', 'fontface', 'fontfaces', 'font', 'paraPr', 'paraProperties', 'ratio', 'spacing', 'fontRef', 'relSz', 'offset', 'underline', 'strikeout', 'outline', 'shadow', 'bold', 'italic', 'emboss', 'engrave', 'tabPr', 'tabItem'}
    for n in header.iter():
        if etree.QName(n).localname in known:
            if not n.tag == HH + etree.QName(n).localname:
                raise ValueError('unsupported current native XML or metric')
    _xml_int(p.get('paraPrIDRef'))
    for r in p.findall(HP + 'run'):
        _xml_int(r.get('charPrIDRef'))
    for tag in ('charPr', 'paraPr', 'tabPr', 'font'):
        for n in header.iter(HH + tag):
            _xml_int(n.get('id'))
    for n in header.iter(HH + 'charPr'):
        _xml_int(n.get('height'))
        for child in n:
            if child.tag in {HH + 'ratio', HH + 'spacing', HH + 'relSz', HH + 'offset', HH + 'fontRef'}:
                for value in child.attrib.values():
                    _xml_int(value, signed=child.tag in {HH + 'spacing', HH + 'offset'})
    for n in header.iter(HH + 'tabItem'):
        _xml_int(n.get('pos'))
    para = next((n for n in header.iter(HH + 'paraPr') if n.get('id') == p.get('paraPrIDRef')))
    margins = para.findall('.//' + HH + 'margin')
    values = []
    for margin in margins:
        entries = []
        for edge in margin:
            if not (edge.tag.startswith('{http://www.hancom.co.kr/hwpml/2011/core}') and edge.get('unit', 'HWPUNIT') == 'HWPUNIT'):
                raise ValueError('unsupported current native XML or metric')
            entries.append((etree.QName(edge).localname, _xml_int(edge.get('value'), signed=True)))
        if not (len(entries) == 5 and len({k for k, v in entries}) == 5 and ({k for k, v in entries} == {'left', 'right', 'intent', 'prev', 'next'})):
            raise ValueError('unsupported current native XML or metric')
        values.append(tuple(sorted(entries)))
    if not (values and len(set(values)) == 1):
        raise ValueError('unsupported current native XML or metric')

def _multiply(a, b):
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3], a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])

def _transform(value):
    matrix = IDENTITY
    parts = re.findall('([A-Za-z]+)\\s*\\(([^)]*)\\)', value or '')
    if value and (not parts):
        raise ValueError('unsupported SVG transform')
    for name, args in parts:
        numbers = [float(x) for x in re.findall('[-+]?(?:\\d*\\.\\d+|\\d+)(?:[eE][-+]?\\d+)?', args)]
        if name == 'translate' and 1 <= len(numbers) <= 2:
            item = (1, 0, 0, 1, numbers[0], numbers[1] if len(numbers) > 1 else 0)
        elif name == 'scale' and 1 <= len(numbers) <= 2:
            item = (numbers[0], 0, 0, numbers[-1], 0, 0)
        elif name == 'matrix' and len(numbers) == 6:
            item = tuple(numbers)
        elif name == 'rotate' and len(numbers) in (1, 3):
            angle = math.radians(numbers[0])
            item = (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0, 0)
            if len(numbers) == 3:
                x, y = numbers[1:]
                item = _multiply(_multiply((1, 0, 0, 1, x, y), item), (1, 0, 0, 1, -x, -y))
        else:
            raise ValueError('unsupported SVG transform')
        matrix = _multiply(matrix, item)
    return matrix

def plain_units(p, header):
    try:
        _current_xml_metrics(p, header)
        if not (all((c.tag in {HP + 'run', HP + 'linesegarray'} for c in p)) and len(p.findall(HP + 'linesegarray')) <= 1):
            raise ValueError('unsupported current native XML or metric')
        paras = list(header.iter(HH + 'paraPr'))
        para_by_id = {n.get('id'): n for n in paras}
        if not len(paras) == len(para_by_id):
            raise ValueError('unsupported current native XML or metric')
        para = para_by_id[p.get('paraPrIDRef')]
        if not (para.get('textDir') == 'LTR' and para.find(HH + 'align').get('horizontal') == 'LEFT'):
            raise ValueError('unsupported current native XML or metric')
        if not para.get('condense', '0') == '0':
            raise ValueError('unsupported current native XML or metric')
        heading = para.find(HH + 'heading')
        if not (heading is None or heading.get('type') == 'NONE'):
            raise ValueError('unsupported current native XML or metric')
        autospace = para.find(HH + 'autoSpacing')
        if not (autospace is None or all((v == '0' for v in autospace.attrib.values()))):
            raise ValueError('unsupported current native XML or metric')
        tabprops = list(header.iter(HH + 'tabPr'))
        tab_by_id = {n.get('id'): n for n in tabprops}
        if not len(tabprops) == len(tab_by_id):
            raise ValueError('unsupported current native XML or metric')
        tabprop = tab_by_id[para.get('tabPrIDRef')]
        nodes = list(tabprop.iter(HH + 'tabItem'))
        if not (nodes and all((n.get('type') == 'LEFT' and n.get('leader') == 'NONE' for n in nodes))):
            raise ValueError('unsupported current native XML or metric')
        tabs = p.findall(HP + 'run/' + HP + 'tab')
        stops = paragraph_tab_stops(p, para_by_id)
        if not (1 <= len(tabs) <= _MAX_PLAIN_TABS and len(stops) == len(tabs) and all((math.isfinite(n) and n > 0 and (n == int(n)) for n in stops))):
            raise ValueError('unsupported current native XML or metric')
        if not all((t.get('type') == '1' and t.get('leader') == '0' and (not len(t)) for t in tabs)):
            raise ValueError('unsupported current native XML or metric')
        languages = {'hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user'}
        props = list(header.iter(HH + 'charPr'))
        styles = {c.get('id'): c for c in props}
        if len(styles) != len(props):
            return None
        faces = {}
        for ff in header.iter(HH + 'fontface'):
            lang = ff.get('lang', '').lower()
            nodes = ff.findall(HH + 'font')
            if lang in faces or len({n.get('id') for n in nodes}) != len(nodes):
                return None
            faces[lang] = {n.get('id'): n.get('face') for n in nodes}
        allowed = {HH + t for t in ('fontRef', 'ratio', 'spacing', 'relSz', 'offset', 'outline', 'shadow', 'underline', 'bold', 'italic')}
        keys = []
        for r in p.findall(HP + 'run'):
            style = styles.get(r.get('charPrIDRef'))
            if style is None or len({c.tag for c in style}) != len(style) or any((c.tag not in allowed for c in style)):
                return None
            if any((style.get(k) != v for k, v in (('useFontSpace', '0'), ('useKerning', '0'), ('symMark', 'NONE')))):
                return None
            size = float(style.get('height'))
            if not (math.isfinite(size) and size == int(size) and (200 <= size <= 5000)):
                raise ValueError('unsupported current native XML or metric')
            refs = style.find(HH + 'fontRef')
            if not (refs is not None and set(refs.attrib) == languages):
                raise ValueError('unsupported current native XML or metric')
            names = [faces[l][refs.get(l)] for l in languages]
            if not (all(names) and len(set(names)) == 1):
                raise ValueError('unsupported current native XML or metric')
            for tag in ('ratio', 'spacing', 'relSz', 'offset'):
                n = style.find(HH + tag)
                if not (n is not None and set(n.attrib) == languages):
                    raise ValueError('unsupported current native XML or metric')
                values = [float(v) for v in n.attrib.values()]
                if not (all((math.isfinite(v) and v == int(v) for v in values)) and len(set(values)) == 1):
                    raise ValueError('unsupported current native XML or metric')
                if tag == 'relSz':
                    if not values[0] == 100:
                        raise ValueError('unsupported current native XML or metric')
                elif tag == 'offset':
                    if not values[0] == 0:
                        raise ValueError('unsupported current native XML or metric')
                elif tag == 'ratio':
                    if not 50 <= values[0] <= 200:
                        raise ValueError('unsupported current native XML or metric')
                elif not -50 <= values[0] <= 50:
                    raise ValueError('unsupported current native XML or metric')
            for tag in ('outline', 'shadow'):
                if not (style.find(HH + tag) is not None and style.find(HH + tag).get('type') == 'NONE'):
                    raise ValueError('unsupported current native XML or metric')
            underline=style.find(HH+'underline')
            if underline is None:raise ValueError('missing current underline style')
            if underline.get('type')!='NONE':
                if dict(underline.attrib)!={'type':'BOTTOM','shape':'SOLID','color':'#000000'}:
                    raise ValueError('only opaque black native BOTTOM SOLID underline is qualified for native metrics')
                if style.get('textColor')!='#000000' or style.get('shadeColor')!='none':
                    raise ValueError('unsupported underlined current paint')
            for c in r:
                if c.tag == HP + 'tab':
                    if not not len(c):
                        raise ValueError('unsupported current native XML or metric')
                    continue
                if not (c.tag == HP + 't' and (not len(c))):
                    raise ValueError('unsupported current native XML or metric')
                for char in c.text or '':
                    if not (char not in '\t\r\n' and len(char.encode('utf-16-le')) == 2 and (not char.isspace() or char == ' ')):
                        raise ValueError('unsupported current native XML or metric')
                    if not unicodedata.category(char) not in {'Mn', 'Mc', 'Me', 'Cf', 'Cc', 'Cs', 'Co'}:
                        raise ValueError('unsupported current native XML or metric')
                    if not not (4352 <= ord(char) <= 4607 or 43360 <= ord(char) <= 43391 or 55216 <= ord(char) <= 55295):
                        raise ValueError('unsupported current native XML or metric')
                    keys.append((r.get('charPrIDRef'), char))
        if not (keys and len(keys) <= 4096):
            raise ValueError('unsupported current native XML or metric')
        return (list(dict.fromkeys(keys)), styles)
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration, UnicodeError):
        return None

class ProbeBudget:
    """Fixed volume plus cumulative native metric time, excluding caller idle time."""

    def __init__(self, *, max_units=512, max_probes=1024, max_prefix_units=100000, seconds=1.0):
        for value in (max_units, max_probes, max_prefix_units):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('invalid native metric volume budget')
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or (not math.isfinite(seconds)) or (seconds < 0):
            raise ValueError('invalid native metric time budget')
        self.max_units = max_units
        self.max_probes = max_probes
        self.max_prefix_units = max_prefix_units
        self.seconds = float(seconds)
        self.probes = 0
        self.prefix_units = 0
        self.spent = 0.0
        self._active_since = None

    def check_time(self):
        current = self.spent + (time.monotonic() - self._active_since if self._active_since is not None else 0.0)
        if current >= self.seconds:
            raise RuntimeError('native metric cumulative time budget exhausted')

    def begin_native(self):
        self.check_time()
        if self._active_since is not None:
            raise RuntimeError('nested native metric operation')
        self._active_since = time.monotonic()

    def end_native(self):
        if self._active_since is not None:
            self.spent += time.monotonic() - self._active_since
            self._active_since = None

    def reserve(self, units, probes, prefix_units):
        self.check_time()
        if units > self.max_units or self.probes + probes > self.max_probes or self.prefix_units + prefix_units > self.max_prefix_units:
            raise RuntimeError('native metric deterministic probe budget exhausted')
        self.probes += probes
        self.prefix_units += prefix_units

class LineRangeAdvance:

    def __init__(self, p, header, *, budget=None):
        proof = plain_units(p, header)
        if proof is None:
            raise ValueError('unsupported current plain paragraph/header')
        self.p = p
        self.header = header
        self.styles = proof[1]
        self.units = []
        self.memo = {}
        self.probes = 0
        self.budget = budget
        for r in p.findall(HP + 'run'):
            sid = r.get('charPrIDRef')
            height = int(self.styles[sid].get('height'))
            for child in r:
                if child.tag == HP + 'tab':
                    self.units.append((sid, '\t', 8, height, child))
                else:
                    for char in child.text or '':
                        self.units.append((sid, char, 1, height, None))
        self.header_digest = hashlib.sha256(etree.tostring(header, encoding='utf-8')).hexdigest()
        self.paragraph_digest = hashlib.sha256(etree.tostring(p, encoding='utf-8')).hexdigest()

    def _measure_from(self, start):
        specs = [None] + list(range(start + 1, len(self.units) + 1))
        if self.budget is not None:
            self.budget.reserve(len(self.units), len(specs), sum((end - start for end in specs[1:])))
        head = deepcopy(self.header)
        props = next(head.iter(HH + 'charProperties'))
        sentinels = {}
        for sid in dict.fromkeys((u[0] for u in self.units[start:])):
            style = deepcopy(self.styles[sid])
            newid = str(max((int(c.get('id')) for c in props)) + 1)
            style.set('id', newid)
            props.append(style)
            sentinels[sid] = newid
        props.set('itemCnt', str(len(props)))
        head.set('secCnt', '1')
        first = etree.fromstring(self.context.parts['Contents/section0.xml'])
        root = etree.Element(first.tag, nsmap=first.nsmap)
        secpr = deepcopy(first.find('.//' + HP + 'secPr'))
        for child in list(secpr):
            if etree.QName(child).localname in {'header', 'footer', 'headerApply', 'footerApply', 'masterPage'}:
                secpr.remove(child)
        page = secpr.find(HP + 'pagePr')
        page.set('width', '500000')
        page.set('height', '20000')
        margin = page.find(HP + 'margin')
        for k in ('top', 'bottom', 'left', 'right'):
            margin.set(k, '1000')
        for k in ('header', 'footer', 'gutter'):
            margin.set(k, '0')
        first_sid = self.units[start][0]
        for index, end in enumerate(specs):
            p = etree.Element(HP + 'p', **dict(self.p.attrib))
            p.set('pageBreak', '1' if index else '0')
            p.set('columnBreak', '0')
            run = None
            last_sid = None
            for sid, char, utf16, height, tab in [] if end is None else self.units[start:end]:
                if sid != last_sid:
                    run = etree.SubElement(p, HP + 'run', charPrIDRef=sid)
                    last_sid = sid
                if char == '\t':
                    etree.SubElement(run, HP + 'tab', width='1', leader='0', type='1')
                else:
                    t = run[-1] if len(run) and run[-1].tag == HP + 't' else etree.SubElement(run, HP + 't')
                    t.text = (t.text or '') + char
            sid = last_sid or first_sid
            sentinel = etree.SubElement(p, HP + 'run', charPrIDRef=sentinels[sid])
            etree.SubElement(sentinel, HP + 't').text = '|'
            if not index:
                sentinel.insert(0, secpr)
                ctrl = etree.Element(HP + 'ctrl')
                etree.SubElement(ctrl, HP + 'colPr', id='0', type='NEWSPAPER', layout='LEFT', colCount='1', sameSz='1', sameGap='0')
                sentinel.insert(1, ctrl)
            height = max([int(self.styles[first_sid].get('height'))] + [u[3] for u in self.units[start:end] if end is not None])
            cache = etree.SubElement(p, HP + 'linesegarray')
            etree.SubElement(cache, HP + 'lineseg', textpos='0', vertpos='0', vertsize=str(height), textheight=str(height), baseline=str(round(height * 0.85)), spacing='0', horzpos='0', horzsize='490000', flags='393216')
            root.append(p)
        parts = dict(self.context.parts)
        parts['Contents/header.xml'] = etree.tostring(head, encoding='utf-8')
        parts['Contents/section0.xml'] = etree.tostring(root, encoding='utf-8')
        manifest = etree.fromstring(parts['Contents/content.hpf'])
        opf = '{' + etree.QName(manifest).namespace + '}'
        removed = set()
        for item in list(manifest.find(opf + 'manifest')):
            if re.fullmatch('(?:Contents/)?section[1-9]\\d*\\.xml', item.get('href', '')):
                removed.add(item.get('id'))
                item.getparent().remove(item)
        for item in list(manifest.find(opf + 'spine')):
            if item.get('idref') in removed:
                item.getparent().remove(item)
        parts['Contents/content.hpf'] = etree.tostring(manifest, encoding='utf-8')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as z:
            for name, data in parts.items():
                if not re.fullmatch('Contents/section[1-9]\\d*\\.xml', name):
                    z.writestr(name, data)
        doc = self.context.native.Document.from_bytes(buffer.getvalue())
        if not doc.page_count == len(specs):
            raise ValueError('unsupported current native XML or metric')
        xs = []
        for index in range(len(specs)):
            if self.budget is not None:
                self.budget.check_time()
            svg = etree.fromstring(doc.render_svg(index).encode())
            pipes = []
            for n in svg.iter(SVG + 'text'):
                if ''.join(n.itertext()) != '|':
                    continue
                matrix = IDENTITY
                for a in [*reversed(list(n.iterancestors())), n]:
                    matrix = _multiply(matrix, _transform(a.get('transform', '')))
                x, y = (float(n.get('x', 0)), float(n.get('y', 0)))
                pipes.append((matrix[0] * x + matrix[2] * y + matrix[4]) * 75)
            if not len(pipes) == 1:
                raise ValueError('unsupported current native XML or metric')
            xs.append(pipes[0])
        for end, value in zip(specs[1:], xs[1:]):
            natural = value - xs[0]
            if not (math.isfinite(natural) and natural >= 0):
                raise ValueError('unsupported current native XML or metric')
            self.memo[start, end] = natural
        self.probes += len(specs)

    def advance(self, start, end, tab_widths):
        self._assert_current()
        if start == end:
            return 0.0
        if (start, end) not in self.memo:
            self._measure_from(start)
        return self.memo[start, end] + sum((tab_widths[i] - 1 for i in range(start, end) if self.units[i][1] == '\t'))

    def before_tab(self, start, index, tab_widths):
        self._assert_current()
        current = dict(tab_widths)
        current[index] = 1
        return self.advance(start, index + 1, current) - 1

def _assert_current(self):
    if getattr(self, '_planning_snapshot', False):
        return
    if self.paragraph_digest != hashlib.sha256(etree.tostring(self.p, encoding='utf-8')).hexdigest():
        raise ValueError('stale native paragraph')
    if self.header_digest != hashlib.sha256(etree.tostring(self.header, encoding='utf-8')).hexdigest():
        raise ValueError('stale native header')
    if self.context.header_digest != self.header_digest:
        raise ValueError('foreign native header')

def _boundary_map(self):
    result = {0: 0}
    offset = 0
    for index, unit in enumerate(self.units):
        offset += unit[2]
        result[offset] = index + 1
    return result

def _native_tabs(self, tab_advances):
    boundaries = _boundary_map(self)
    result = {}
    for offset, value in tab_advances.items():
        if isinstance(offset, bool) or not isinstance(offset, int) or offset not in boundaries:
            raise ValueError('invalid native TAB UTF16 position')
        index = boundaries[offset]
        if index >= len(self.units) or self.units[index][1] != '\t':
            raise ValueError('not current TAB boundary')
        if isinstance(value, bool) or not isinstance(value, int) or (not 1 <= value <= 65535):
            raise ValueError('invalid current TAB advance')
        result[index] = value
    return result

def _range_advance(self, line_start_utf16, prefix_end_utf16, tab_advances):
    boundaries = _boundary_map(self)
    if any((isinstance(x, bool) or not isinstance(x, int) or x not in boundaries for x in (line_start_utf16, prefix_end_utf16))):
        raise ValueError('invalid native UTF16 range')
    start, end = (boundaries[line_start_utf16], boundaries[prefix_end_utf16])
    if end < start:
        raise ValueError('reversed native UTF16 range')
    return self.advance(start, end, _native_tabs(self, tab_advances))

def _before_tab_advance(self, line_start_utf16, tab_utf16, tab_advances):
    boundaries = _boundary_map(self)
    if any((isinstance(x, bool) or not isinstance(x, int) or x not in boundaries for x in (line_start_utf16, tab_utf16))):
        raise ValueError('invalid native TAB UTF16 range')
    start, index = (boundaries[line_start_utf16], boundaries[tab_utf16])
    if start > index or index >= len(self.units) or self.units[index][1] != '\t':
        raise ValueError('not current native TAB range')
    return self.before_tab(start, index, _native_tabs(self, tab_advances))
LineRangeAdvance._assert_current = _assert_current
LineRangeAdvance.range_advance = _range_advance
LineRangeAdvance.before_tab_advance = _before_tab_advance

def _begin_plan(self):
    self._assert_current()
    if getattr(self, '_planning_snapshot', False):
        raise ValueError('nested native metric plan')
    self._source_paragraph = self.p
    self._source_header = self.header
    self.p = deepcopy(self.p)
    self.header = deepcopy(self.header)
    self.styles = {n.get('id'): n for n in self.header.iter(HH + 'charPr')}
    self._planning_snapshot = True

def _finish_plan(self):
    if not getattr(self, '_planning_snapshot', False):
        raise ValueError('no native metric plan')
    if self.paragraph_digest != hashlib.sha256(etree.tostring(self._source_paragraph, encoding='utf-8')).hexdigest():
        raise ValueError('current native paragraph changed during plan')
    if self.header_digest != hashlib.sha256(etree.tostring(self._source_header, encoding='utf-8')).hexdigest():
        raise ValueError('current native header changed during plan')
    self._cancel_plan()

def _cancel_plan(self):
    if getattr(self, '_planning_snapshot', False):
        self.p = self._source_paragraph
        self.header = self._source_header
        self.styles = {n.get('id'): n for n in self.header.iter(HH + 'charPr')}
        self._planning_snapshot = False
LineRangeAdvance.begin_plan = _begin_plan
LineRangeAdvance.finish_plan = _finish_plan
LineRangeAdvance._cancel_plan = _cancel_plan

class NativeAdvanceContext:
    """Lazy current-header context; one bounded optional backend per refresh."""

    def __init__(self, header, *, native=None, budget=None):
        self._native = native
        self.header = header
        self.header_digest = hashlib.sha256(etree.tostring(header, encoding='utf-8')).hexdigest()
        self.budget = budget or ProbeBudget()
        self._parts = None
        self.capability_evidence = None
        if any((f.get('isEmbedded', '0') not in ('0', 'false', 'False') for f in header.iter(HH + 'font'))):
            raise ValueError('embedded font backend unavailable')

    @property
    def native(self):
        if self._native is None:
            import rhwp
            self._native = rhwp
        return self._native

    @property
    def parts(self):
        if self._parts is None:
            with zipfile.ZipFile(io.BytesIO(_generated_blank_document_bytes())) as package:
                self._parts = {name: package.read(name) for name in package.namelist()}
            self._parts['Contents/header.xml'] = etree.tostring(self.header, encoding='utf-8')
        return self._parts

    def for_paragraph(self, paragraph):
        try:
            self.budget.check_time()
            if self.header_digest != hashlib.sha256(etree.tostring(self.header, encoding='utf-8')).hexdigest():
                return None
            provider = LineRangeAdvance(paragraph, self.header, budget=self.budget)
            if len(provider.units) > self.budget.max_units:
                return None
            provider.context = self
            if not _native_tab_capability(self, provider):
                return None
            return provider
        except (ValueError, KeyError, TypeError, RuntimeError, AttributeError, StopIteration, UnicodeError, ImportError, OSError):
            return None

def optional_native_context(header, *, native=None, budget=None):
    try:
        return NativeAdvanceContext(header, native=native, budget=budget)
    except (ImportError, OSError, ValueError, RuntimeError):
        return None
_CAPABILITIES = {}

def _pipe_x(document, index):
    svg = etree.fromstring(document.render_svg(index).encode('utf-8'))
    pipes = []
    for n in svg.iter(SVG + 'text'):
        if ''.join(n.itertext()) != '|':
            continue
        matrix = IDENTITY
        for ancestor in [*reversed(list(n.iterancestors())), n]:
            matrix = _multiply(matrix, _transform(ancestor.get('transform', '')))
        x = float(n.get('x', 0))
        y = float(n.get('y', 0))
        pipes.append((matrix[0] * x + matrix[2] * y + matrix[4]) * 75)
    if len(pipes) != 1 or not math.isfinite(pipes[0]):
        raise ValueError('unsupported native capability paint')
    return pipes[0]

def _native_tab_capability(context, provider):
    """Actual native fractional LEFT advance, style-TAB slicing and ID merging.

    Four tiny synthetic pages use only known explicit TAB advances37/113 HWP.
    Identical cloned styles preserve sentinel bearing; no glyph width, source
    PDF, old cache or previously saved TAB width supplies an expected result.
    """
    native = context.native
    key = id(native)
    cached = _CAPABILITIES.get(key)
    if cached is not None and cached[0] is native:
        return cached[1]
    budget = context.budget
    budget.begin_native()
    try:
        budget.reserve(0, 4, 0)
        head = deepcopy(context.header)
        props = next(head.iter(HH + 'charProperties'))
        sid = provider.units[0][0]
        base = provider.styles[sid]
        ids = []
        for unused in range(2):
            cloned = deepcopy(base)
            newid = str(max((int(c.get('id')) for c in props)) + 1)
            cloned.set('id', newid)
            props.append(cloned)
            ids.append(newid)
        props.set('itemCnt', str(len(props)))
        head.set('secCnt', '1')
        first = etree.fromstring(context.parts['Contents/section0.xml'])
        root = etree.Element(first.tag, nsmap=first.nsmap)
        secpr = deepcopy(first.find('.//' + HP + 'secPr'))
        page = secpr.find(HP + 'pagePr')
        page.set('width', '30000')
        page.set('height', '20000')
        margin = page.find(HP + 'margin')
        for k in ('top', 'bottom', 'left', 'right'):
            margin.set(k, '1000')
        for k in ('header', 'footer', 'gutter'):
            margin.set(k, '0')
        specs = ((), ((sid, 37),), ((sid, 37), (sid, 113)), ((sid, 37), (ids[0], 113)))
        for index, spec in enumerate(specs):
            p = etree.SubElement(root, HP + 'p', **dict(provider.p.attrib))
            p.set('pageBreak', '1' if index else '0')
            p.set('columnBreak', '0')
            for charid, width in spec:
                run = etree.SubElement(p, HP + 'run', charPrIDRef=charid)
                etree.SubElement(run, HP + 'tab', width=str(width), leader='0', type='1')
            sentinel = etree.SubElement(p, HP + 'run', charPrIDRef=ids[1])
            etree.SubElement(sentinel, HP + 't').text = '|'
            if not index:
                sentinel.insert(0, secpr)
                ctrl = etree.Element(HP + 'ctrl')
                etree.SubElement(ctrl, HP + 'colPr', id='0', type='NEWSPAPER', layout='LEFT', colCount='1', sameSz='1', sameGap='0')
                sentinel.insert(1, ctrl)
            height = int(base.get('height'))
            cache = etree.SubElement(p, HP + 'linesegarray')
            etree.SubElement(cache, HP + 'lineseg', textpos='0', vertpos='0', vertsize=str(height), textheight=str(height), baseline=str(round(height * 0.85)), spacing='0', horzpos='0', horzsize='28000', flags='393216')
        parts = dict(context.parts)
        parts['Contents/header.xml'] = etree.tostring(head, encoding='utf-8')
        parts['Contents/section0.xml'] = etree.tostring(root, encoding='utf-8')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as package:
            for name, data in parts.items():
                package.writestr(name, data)
        document = native.Document.from_bytes(buffer.getvalue())
        if document.page_count != 4:
            raise ValueError('unsupported native capability pages')
        positions = []
        for i in range(4):
            budget.check_time()
            positions.append(_pipe_x(document, i))
        residuals = [positions[i] - positions[0] - expected for i, expected in enumerate((0.0, 37.0, 150.0, 150.0))]
        supported = all((abs(r) < 0.01 for r in residuals))
        context.capability_evidence = {'probe_pages': 4, 'advances_hwp': [x - positions[0] for x in positions], 'expected_hwp': [0, 37, 150, 150], 'supported': supported}
        _CAPABILITIES[key] = (native, supported)
        return supported
    finally:
        budget.end_native()
_untimed_measure_from = LineRangeAdvance._measure_from

def _timed_measure_from(self, start):
    if self.budget is None:
        return _untimed_measure_from(self, start)
    self.budget.begin_native()
    try:
        return _untimed_measure_from(self, start)
    finally:
        self.budget.end_native()
LineRangeAdvance._measure_from = _timed_measure_from
