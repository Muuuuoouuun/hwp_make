"""Native HWP drawing groups: original graph bitmap plus editable annotations."""
from xml.etree import ElementTree

from lxml import etree

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HC = '{http://www.hancom.co.kr/hwpml/2011/core}'
NAME = 'source-graph-annotation'


def restore_graph_groups(section, paragraphs, layouts, header, page_width, column_width, para_style):
    from hwpx.oxml._document_impl import _create_rectangle_element
    from .hwpx_writer_v2 import _set_paragraph_element_lineseg
    from .pdf_picture_geometry import set_picture_display_size

    next_id = max((int(n.get('id')) for n in section.iter() if n.get('id', '').isdigit()), default=0)+1

    def identifier():
        nonlocal next_id
        next_id += 1
        return str(next_id)

    def rectangle(width, height):
        node = etree.fromstring(ElementTree.tostring(_create_rectangle_element(
            width, height, line_width='1', fill_color=None, treat_as_char=True)))
        node.set('id', identifier())
        node.set('instid', node.get('id'))
        node.find(HP+'lineShape').attrib.update({'style': 'NONE', 'alpha': '0'})
        for margin in node.findall(HP+'outMargin'):
            for side in ('left', 'right', 'top', 'bottom'):
                margin.set(side, '0')
        return node

    def translate(node, x, y):
        node.set('groupLevel', '1')
        node.find(HP+'offset').attrib.update({'x': str(x), 'y': str(y)})
        node.find(HP+'renderingInfo/'+HC+'transMatrix').attrib.update({'e3': str(x), 'e6': str(y)})

    removed, restored = set(), 0
    for paragraph, layout in zip(paragraphs, layouts):
        graph = layout.get('source_native_graph')
        if not graph:
            continue
        annotations = [(p, meta) for p, meta in zip(paragraphs, layouts)
                       if meta.get('source_graph_annotation') == graph['key']]
        pictures = paragraph.findall(HP+'run/'+HP+'pic')
        if len(pictures) != 1 or len(annotations) != graph['annotation_count']:
            raise ValueError('Graph annotation/bitmap inventory mismatch')
        x0,y0,x1,y1 = graph['bbox_pt']
        scale = page_width / layout['source_page_width_pt']
        width, height = round((x1-x0)*scale), round((y1-y0)*scale)
        inset = round((x0-layout['column_left_pt'])*scale)
        group = rectangle(round(column_width), height)
        group.tag = HP+'container'
        # A group has common shape geometry but no rectangle-specific paint.
        for child in list(group):
            if etree.QName(child).localname in {'lineShape','fillBrush','shadow','pt0','pt1','pt2','pt3'}:
                group.remove(child)
        group.find(HP+'shapeComment').text = 'Source graph with editable annotations'
        group.set('textWrap', 'TOP_AND_BOTTOM')
        group.find(HP+'pos').attrib.update({'treatAsChar': '1', 'affectLSpacing': '1',
            'flowWithText': '1', 'allowOverlap': '0', 'vertRelTo': 'PARA', 'horzRelTo': 'COLUMN',
            'vertOffset': '0', 'horzOffset': '0'})
        picture = pictures[0]
        set_picture_display_size(picture, width, height)
        translate(picture, inset, 0)
        picture.find(HP+'pos').attrib.update({'treatAsChar': '1', 'vertOffset': '0', 'horzOffset': '0'})
        group.append(picture)
        for label, meta in annotations:
            bounds = meta['source_typography']['source_bbox_pt']
            label_width, label_height = round((bounds[2]-bounds[0])*scale), round((bounds[3]-bounds[1])*scale)
            shape = rectangle(label_width, label_height)
            translate(shape, inset+round((bounds[0]-x0)*scale), round((bounds[1]-y0)*scale))
            shape.find(HP+'shapeComment').text = 'Editable graph annotation'
            draw = etree.Element(HP+'drawText', name=NAME, lastWidth=str(label_width), editable='1')
            etree.SubElement(draw, HP+'textMargin', left='0', right='0', top='0', bottom='0')
            sub = etree.SubElement(draw, HP+'subList', id='', textDirection='HORIZONTAL',
                lineWrap='BREAK', vertAlign='TOP', linkListIDRef='0', linkListNextIDRef='0',
                textWidth=str(label_width), textHeight=str(label_height), hasTextRef='0', hasNumRef='0')
            for cache in label.findall(HP+'linesegarray/'+HP+'lineseg'):
                cache.attrib.update({'vertpos': '0', 'horzpos': '0', 'horzsize': str(label_width)})
            label.set('pageBreak', '0')
            label.set('columnBreak', '0')
            label.set('paraPrIDRef', para_style(label.get('paraPrIDRef'), 'LEFT', label_height, label_height))
            sub.append(label)
            shape.insert(shape.index(shape.find(HP+'shadow')), draw)
            group.append(shape)
            removed.add(id(label))
        run = paragraph.find(HP+'run')
        run.append(group)
        paragraph.set('paraPrIDRef', para_style(paragraph.get('paraPrIDRef'), 'LEFT', 1000, 1000))
        paragraph.set('nativeParagraphWidth', str(round(column_width)))
        _set_paragraph_element_lineseg(paragraph, height+300, width=round(column_width), spacing_ratio=0)
        restored += 1
    pairs = [(p, meta) for p, meta in zip(paragraphs, layouts) if id(p) not in removed]
    return [p for p,_ in pairs], [meta for _,meta in pairs], restored
