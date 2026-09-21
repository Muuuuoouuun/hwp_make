"""Never split a framed math argument or partially mutate a rejected paragraph."""
from copy import deepcopy
from pathlib import Path
import re
import sys

from lxml import etree as E

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'app/_vendor'))
from app.pdf_inline_label_writer import restore_inline_labels
from app.pdf_inline_labels import HP, inline_label_text


def fixture(text):
    root = E.Element(HP+'p', id='1')
    run = E.SubElement(root, HP+'run', charPrIDRef='0')
    eq = E.SubElement(run, HP+'equation', id='2')
    E.SubElement(eq, HP+'script').text = text
    E.SubElement(eq, HP+'sz', width='10000', height='1000')
    label = {'text': '(가)', 'offset': re.sub(r'\s+', '', text).index('(가)'),
             'bbox_pt': [10, 10, 63.82, 26.67], 'ink_bbox_pt': [27, 13, 47, 25],
             'font_size_pt': 10, 'font': 'Batang', 'line_width_pt': .12}
    layout = {'source_inline_labels': [label], 'source_page_width_pt': 595.28,
              'source_typography': {'lines': [{'text': text,
                  'spans': [{'text': text, 'font': 'Batang', 'size': 10}]}]}}
    return root, layout


def main():
    positives = ('a=(가)', '(가) = 0', '(가)<0', 'a>(가)', '(가)', 'a LEQ (가)')
    negatives = ('a^(가)', 'sqrt{(가)}', 'sin(가)', '(가)x', 'x(가)',
                 'f((가))', 'a_{(가)}', '"(가)"', 'a OVER (가)', '(가) LEQX')
    for text in positives + negatives:
        root, layout = fixture(text)
        original = E.tostring(root)
        allocated = []
        def style(*args):
            allocated.append(args)
            return '0'
        count = restore_inline_labels(root, layout, 59528, style, style)
        if text in negatives:
            assert count == 0 and not allocated and E.tostring(root) == original, text
            continue
        assert count == 1
        assert len(root.findall('.//'+HP+'rect')) == 1
        assert len(root.findall(HP+'run')) == 1
        sequence = ''.join(inline_label_text(c) if c.tag == HP+'rect'
                           else c.findtext(HP+'script', '') for c in root.find(HP+'run'))
        assert sequence == text, text
    for kind in ('duplicate', 'offset', 'source_mismatch'):
        root, layout = fixture('a=(가)')
        if kind == 'duplicate':
            layout['source_inline_labels'].append(deepcopy(layout['source_inline_labels'][0]))
        elif kind == 'offset':
            layout['source_inline_labels'][0]['offset'] = 0
        else:
            layout['source_typography']['lines'][0]['spans'][0]['text'] = 'a=(나)'
        original = E.tostring(root)
        def forbidden_style(*args):
            raise AssertionError('rejected source allocated styles')
        assert restore_inline_labels(root, layout, 59528, forbidden_style, forbidden_style) == 0
        assert E.tostring(root) == original, kind
    print('NATIVE_INLINE_LABEL_WRITER_OK', {'positive': len(positives), 'negative': len(negatives)+3})


if __name__ == '__main__':
    main()
