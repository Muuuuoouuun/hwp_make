"""Read body content without interleaving repeating HWPX page furniture."""
from lxml import etree

from ._vendor.hwpx_text_content import text_with_controls

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
RUNNING_CONTROLS = {HP + 'header', HP + 'footer'}


def body_elements(root):
    """Headers/footers may be anchored between two runs of one body paragraph."""
    walker = etree.iterwalk(root, events=('start',))
    for _, node in walker:
        if node.tag in RUNNING_CONTROLS:
            walker.skip_subtree()
        else:
            yield node


def body_text(root, *, include_equations=True, omit_script_markers=False):
    parts = []
    for node in body_elements(root):
        if node.tag == HP + 't':
            parts.append(text_with_controls(node))
        elif (include_equations and node.tag == HP + 'script'
              and node.getparent().tag == HP + 'equation'):
            value = node.text or ''
            if omit_script_markers:
                value = value.replace('^', '').replace('_', '')
            parts.append(value)
    return ''.join(parts)
