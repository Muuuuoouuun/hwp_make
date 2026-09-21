"""Native square-wrapped pictures anchored to an editable paragraph."""
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def is_wrapped_picture(node):
    pos = node.find(HP + "pos")
    return (node.tag == HP + "pic" and node.get("textWrap") == "SQUARE"
            and pos is not None and pos.get("treatAsChar") == "0"
            and pos.get("flowWithText") == "1" and pos.get("vertRelTo") == "PARA"
            and pos.get("horzRelTo") in {"PARA", "COLUMN"})


def available_interval(paragraph, width, top, height):
    intervals = [(0.0, float(width))]
    for run in paragraph.findall(HP + "run"):
        for picture in run:
            if not is_wrapped_picture(picture):
                continue
            pos, size, margin = (picture.find(HP + tag) for tag in ("pos", "sz", "outMargin"))
            def number(node, key):
                return float(node.get(key, 0)) if node is not None else 0
            x, y = number(pos, "horzOffset"), number(pos, "vertOffset")
            end = x + number(size, "width") + number(margin, "right")
            x -= number(margin, "left")
            bottom = y + number(size, "height") + number(margin, "bottom")
            y -= number(margin, "top")
            if min(top + height, bottom) <= max(top, y):
                continue
            remaining = []
            for left, right in intervals:
                if end <= left or x >= right:
                    remaining.append((left, right))
                else:
                    if x > left:
                        remaining.append((left, min(x, right)))
                    if end < right:
                        remaining.append((max(end, left), right))
            intervals = remaining
    if not intervals:
        raise ValueError("Floating picture leaves no horizontal interval for editable text")
    left, right = max(intervals, key=lambda interval: interval[1] - interval[0])
    return left, right - left
