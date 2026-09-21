"""Conservative source evidence for intentional verse lines and stanza gaps."""
import re
from statistics import median

LABEL = re.compile(r'^\([가-힣A-Za-z]\)$')
CREDIT = re.compile(r'^[-–—]\s*[^,，]{1,60}[,，]\s*[「『｢“\"].+[」』｣”\"]\s*[-–—]?$')
LIST_ITEM = re.compile(r'^(?:[①-⑳○●•]|\d+[.)]|[ㄱ-ㅎ][.)])')


def source_verse_stanzas(records, column_width):
    """Return complete source groups, or None when verse evidence is weak.

    A short line alone is never a verse claim. Require a named-work credit,
    several aligned short lines, variable right edges and plausible baseline
    intervals. A frame containing any unclassified segment is left as prose.
    """
    if column_width <= 0 or not records:
        return None
    credits = [i for i, r in enumerate(records) if CREDIT.fullmatch(r['text'].strip())]
    if not credits or credits[-1] != len(records) - 1:
        return None
    result, start = [], 0
    for end in credits:
        body = records[start:end]
        labels = []
        while body and LABEL.fullmatch(body[0]['text'].strip()):
            labels.append(body[0])
            body = body[1:]
        if len(body) < 6 or any(LIST_ITEM.match(r['text'].strip()) for r in body):
            return None
        size = median(float(r.get('font_size_pt') or 0) for r in body)
        if size <= 0:
            return None
        lefts = [float(r['bbox_pt'][0]) for r in body]
        widths = [float(r['bbox_pt'][2]) - x for r, x in zip(body, lefts)]
        right = max(float(r['bbox_pt'][2]) for r in records[start:end + 1])
        if (median(widths) > column_width * .72
            or sum(w < column_width * .9 for w in widths) < len(body) * .8
            or sum(abs(x - median(lefts)) <= size * .45 for x in lefts) < len(body) * .8
            or sum(right - float(r['bbox_pt'][2]) < size * 2 for r in body) > len(body) * .25):
            return None
        gaps = [float(b['baseline_pt']) - float(a['baseline_pt']) for a, b in zip(body, body[1:])]
        if any(g < size * .8 or g > size * 4 for g in gaps):
            return None
        regular = [g for g in gaps if g < size * 2.1]
        if len(regular) < len(gaps) * .5:
            return None
        step = median(regular)
        if any(g <= step * 1.5 and abs(g - step) > size * .35 for g in gaps):
            return None
        result.extend([label] for label in labels)
        stanza = []
        for i, line in enumerate(body):
            if stanza and gaps[i - 1] > step * 1.5:
                result.append(stanza)
                stanza = []
            stanza.append(line)
        result.append(stanza)
        result.append([records[end]])
        start = end + 1
    return result
