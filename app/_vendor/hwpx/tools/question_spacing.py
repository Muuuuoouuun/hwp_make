"""Preserve measured whitespace as real native question-box text margins.

An object-only paragraph can lose its before/after spacing in a reader's
inline-shape cursor calculation. Native text-box padding participates in the
object's actual height and survives text growth and deletion. Convert the
spacing without changing any text, object position offset or content height.
"""
from copy import deepcopy
import re

from lxml import etree
from .paragraph_spacing import paragraph_spacing

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
HC = '{http://www.hancom.co.kr/hwpml/2011/core}'
QUESTION = re.compile(r'question:v\d+:q\d+$')
# Native drawing-text margins are signed 16-bit HWPUNIT values. A larger
# value can be discarded by a reader even when the object's height is valid.
MAX_MARGIN = 32767


def question_host(paragraph):
    children = [c for run in paragraph.findall(HP + 'run') for c in run]
    shapes = [c for c in children if c.tag == HP + 'rect']
    lines = paragraph.findall(HP + 'linesegarray/' + HP + 'lineseg')
    unsupported = any(c.tag not in {HP + 'rect', HP + 'ctrl', HP + 'secPr', HP + 't'}
                      or (c.tag == HP + 't' and (len(c) or (c.text or '').strip())) for c in children)
    if len(shapes) != 1 or len(lines) != 1 or unsupported:
        return None
    shape = shapes[0]
    draw, pos, size = shape.find(HP + 'drawText'), shape.find(HP + 'pos'), shape.find(HP + 'sz')
    if (draw is None or not QUESTION.fullmatch(draw.get('name', '')) or pos is None
        or pos.get('treatAsChar') != '1' or size is None or draw.find(HP + 'textMargin') is None
        or draw.find(HP + 'subList') is None or float(lines[0].get('spacing', '0')) != 0):
        return None
    return shape, draw, lines[0]


def resize_question_box(shape, height):
    """Keep the editable area, rectangle geometry and host line in agreement."""
    draw = shape.find(HP + 'drawText')
    margin = draw.find(HP + 'textMargin')
    inset = sum(float(margin.get(edge, '0')) for edge in ('top', 'bottom'))
    if height <= inset:
        raise ValueError('Question text margins leave no room for its native content')
    for tag in ('sz', 'curSz', 'orgSz'):
        size = shape.find(HP + tag)
        if size is not None:
            size.set('height', str(round(height)))
    for tag in ('pt2', 'pt3'):
        point = shape.find(HC + tag)
        if point is not None:
            point.set('y', str(round(height)))
    rotation = shape.find(HP + 'rotationInfo')
    if rotation is not None:
        rotation.set('centerY', str(round(height) // 2))
    draw.find(HP + 'subList').set('textHeight', str(round(height - inset)))
    paragraph = shape.getparent().getparent()
    for line in paragraph.findall(HP + 'linesegarray/' + HP + 'lineseg'):
        for name in ('vertsize', 'textheight'):
            line.set(name, str(round(height)))
        line.set('baseline', str(round(height * .85)))


class ParagraphSpacingStyles:
    """Copy shared paragraph styles when changing one paragraph's whitespace."""

    def __init__(self, header):
        self.properties = header.find('.//' + HH + 'paraProperties')
        self.styles = {p.get('id'): p for p in self.properties} if self.properties is not None else {}
        self.cache = {}

    def set(self, paragraph, before, after):
        if paragraph_spacing(paragraph, self.styles) == (before, after):
            return False
        base = paragraph.get('paraPrIDRef')
        key = (base, round(before), round(after))
        if key not in self.cache:
            style = deepcopy(self.styles[base])
            identifier = str(max(map(int, self.styles)) + 1)
            style.set('id', identifier)
            for margin in style.findall('.//' + HH + 'margin'):
                for name, amount in [('prev', before), ('next', after)]:
                    edge = margin.find(HC + name)
                    if edge is None:
                        edge = etree.SubElement(margin, HC + name)
                    edge.set('value', str(round(amount)))
                    edge.set('unit', 'HWPUNIT')
            self.properties.append(style)
            self.styles[identifier] = style
            self.cache[key] = identifier
            self.properties.set('itemCnt', str(len(self.properties)))
        paragraph.set('paraPrIDRef', self.cache[key])
        return True


def arrange_question_gaps(section, header, *, before_pagination=False):
    """Conserve occupied height, moving source whitespace into native padding.

    Unpack padding before repagination so whitespace and content are measured
    separately. After pagination, prefer the preceding question's bottom margin
    and put any remainder in the following question's top margin. Only adjacent
    boxes in one page/column may share a gap. This never adds a blank paragraph
    or another drawing object. The box's actual text area remains unchanged.
    """
    spacing = ParagraphSpacingStyles(header)
    if spacing.properties is None:
        return 0
    styles, set_spacing = spacing.styles, spacing.set

    paragraphs = section.findall(HP + 'p')
    changed = 0
    def same_flow(paragraph):
        return (paragraph.get('pageBreak') != '1' and paragraph.get('columnBreak') != '1'
                and paragraph.find('.//' + HP + 'colPr') is None
                and paragraph.find('.//' + HP + 'secPr') is None)

    def add_padding(host, edge, amount):
        shape, draw, _ = host
        margin = draw.find(HP + 'textMargin')
        value = float(margin.get(edge, '0')) + amount
        if not 0 <= value <= MAX_MARGIN:
            raise ValueError('Question whitespace exceeds the native text-margin range')
        margin.set(edge, str(round(value)))
        resize_question_box(shape, float(shape.find(HP + 'sz').get('height')) + amount)

    for paragraph in paragraphs:
        host = question_host(paragraph)
        if host is None:
            continue
        shape, draw, _ = host
        margin = draw.find(HP + 'textMargin')
        top, bottom = [float(margin.get(edge, '0')) for edge in ('top', 'bottom')]
        before, after = paragraph_spacing(paragraph, styles)
        height = float(shape.find(HP + 'sz').get('height'))
        if before_pagination and top + bottom:
            margin.set('top', '0')
            margin.set('bottom', '0')
            resize_question_box(shape, height - top - bottom)
            set_spacing(paragraph, before + top, after + bottom)
            changed += 1
    for previous, paragraph in zip(paragraphs, paragraphs[1:]):
        if not same_flow(paragraph):
            continue
        host = question_host(previous)
        if host is None:
            continue
        before, after = paragraph_spacing(paragraph, styles)
        prev_before, prev_after = paragraph_spacing(previous, styles)
        if before_pagination and prev_after:
            set_spacing(previous, prev_before, 0)
            set_spacing(paragraph, before + prev_after, after)
            changed += 1
        elif not before_pagination and before > 0:
            margin = host[1].find(HP + 'textMargin')
            amount = min(before, MAX_MARGIN - float(margin.get('bottom', '0')))
            # Ordinary paragraphs retain any excess before spacing, which is
            # accounted for normally by text/table flow. Question hosts consume
            # their remainder as top padding in the final pass below.
            add_padding(host, 'bottom', amount)
            set_spacing(paragraph, before - amount, after)
            changed += 1
    if not before_pagination:
        for paragraph in paragraphs:
            host = question_host(paragraph)
            if host is None:
                continue
            before, after = paragraph_spacing(paragraph, styles)
            if before or after:
                add_padding(host, 'top', before)
                add_padding(host, 'bottom', after)
                set_spacing(paragraph, 0, 0)
                changed += 1
    return changed
