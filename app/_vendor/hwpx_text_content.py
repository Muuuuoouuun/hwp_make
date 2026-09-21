"""Read HWPX text/controls without initializing the optional document package."""

CONTROL_TEXT = {
    'lineBreak': '\n', 'tab': '\t', 'nbSpace': '\u00a0', 'fwSpace': '\u2007',
    'hyphen': '-', 'softHyphen': '\u00ad',
}


def iter_text_parts(element):
    """Yield (visible text, control or None), including mixed-content tails."""
    if element.text:
        yield element.text, None
    for child in element:
        name = child.tag.rsplit('}', 1)[-1]
        if name in CONTROL_TEXT:
            yield CONTROL_TEXT[name], child
        else:
            yield from iter_text_parts(child)
        if child.tail:
            yield child.tail, None


def text_with_controls(element):
    return ''.join(value for value, _ in iter_text_parts(element))
