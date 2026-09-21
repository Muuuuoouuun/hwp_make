"""Verify that native question text is painted visibly inside the rendered page.

SVG text content alone is not proof: white, transparent, off-page and clipped
text must not count towards the rendered-content comparison.
"""

from __future__ import annotations

from collections import Counter
import base64
import hashlib
import io
import math
from pathlib import Path
import re
import zipfile

from lxml import etree
from PIL import Image, ImageColor

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
SVG = "{http://www.w3.org/2000/svg}"
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _contrast_on_white(color, opacity=1.0):
    try:
        rgb = ImageColor.getrgb(color)
    except (ValueError, TypeError):
        return 0.0
    if len(rgb) == 4:
        opacity *= rgb[3] / 255
    channels = [(channel * opacity + 255 * (1 - opacity)) / 255 for channel in rgb[:3]]
    linear = [
        x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in channels
    ]
    return 1.05 / (sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722))) + 0.05)


def _style(node):
    values = dict(node.attrib)
    for pair in node.get("style", "").split(";"):
        if ":" in pair:
            key, value = pair.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def _multiply(a, b):
    return (
        a[0] * b[0] + a[2] * b[1],
        a[1] * b[0] + a[3] * b[1],
        a[0] * b[2] + a[2] * b[3],
        a[1] * b[2] + a[3] * b[3],
        a[0] * b[4] + a[2] * b[5] + a[4],
        a[1] * b[4] + a[3] * b[5] + a[5],
    )


def _transform(value):
    matrix = IDENTITY
    parts = re.findall(r"([A-Za-z]+)\s*\(([^)]*)\)", value or "")
    if value and not parts:
        raise ValueError("unsupported SVG transform")
    for name, args in parts:
        numbers = [
            float(x)
            for x in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", args)
        ]
        if name == "translate" and 1 <= len(numbers) <= 2:
            item = (1, 0, 0, 1, numbers[0], numbers[1] if len(numbers) > 1 else 0)
        elif name == "scale" and 1 <= len(numbers) <= 2:
            item = (numbers[0], 0, 0, numbers[-1], 0, 0)
        elif name == "matrix" and len(numbers) == 6:
            item = tuple(numbers)
        elif name == "rotate" and len(numbers) in (1, 3):
            angle = math.radians(numbers[0])
            item = (
                math.cos(angle),
                math.sin(angle),
                -math.sin(angle),
                math.cos(angle),
                0,
                0,
            )
            if len(numbers) == 3:
                x, y = numbers[1:]
                item = _multiply(
                    _multiply((1, 0, 0, 1, x, y), item), (1, 0, 0, 1, -x, -y)
                )
        else:
            raise ValueError("unsupported SVG transform")
        matrix = _multiply(matrix, item)
    return matrix


def _bounds(matrix, x, y, width, height):
    points = [
        (
            matrix[0] * a + matrix[2] * b + matrix[4],
            matrix[1] * a + matrix[3] * b + matrix[5],
        )
        for a, b in [(x, y), (x + width, y), (x, y + height), (x + width, y + height)]
    ]
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def _intersect(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def _bitmap_identity(payload):
    with Image.open(io.BytesIO(payload)) as image:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        white.alpha_composite(rgba)
        pixels = white.convert("RGB")
        return (
            f"{pixels.width}x{pixels.height}:"
            + hashlib.sha256(pixels.tobytes()).hexdigest()
        )


def _visible_svg_images(svg):
    """Count actual, fully visible image pixels; unused defs are not painting.

    Pattern/mask/filter paints are deliberately unassessed rather than treating
    an image resource or XML reference as proof that a frame is visible.
    """
    root = etree.fromstring(svg.encode())
    view = [float(x) for x in root.get("viewBox", "").split()]
    viewport = (
        (view[0], view[1], view[0] + view[2], view[1] + view[3])
        if len(view) == 4
        else (0, 0, float(root.get("width")), float(root.get("height")))
    )
    clips = {node.get("id"): node for node in root.iter(SVG + "clipPath")}
    result = Counter()
    candidates = []
    covers = []
    for index, node in enumerate(root.iter()):
        if node.tag not in (SVG + "image", SVG + "rect"):
            continue
        ancestors = [*reversed(list(node.iterancestors())), node]
        if any(
            etree.QName(a).localname in {"defs", "pattern", "clipPath", "mask"}
            for a in ancestors
        ):
            continue
        try:
            matrix, opacity, limits = IDENTITY, 1.0, [viewport]
            inherited = {
                "fill": "#000000",
                "fill-opacity": "1",
                "visibility": "visible",
            }
            for ancestor in ancestors:
                style = _style(ancestor)
                if (
                    style.get("display") == "none"
                    or style.get("filter", "none") != "none"
                    or style.get("mask", "none") != "none"
                ):
                    raise ValueError("unassessed or hidden image paint")
                opacity *= float(style.get("opacity", "1"))
                inherited.update({k: style[k] for k in inherited if k in style})
                matrix = _multiply(matrix, _transform(style.get("transform", "")))
                clip = style.get("clip-path", "none")
                if clip != "none":
                    match = re.fullmatch(r"url\(#([^)]*)\)", clip)
                    definition = clips.get(match[1]) if match else None
                    rects = (
                        definition.findall(SVG + "rect")
                        if definition is not None
                        else []
                    )
                    if (
                        len(rects) != 1
                        or definition.get("clipPathUnits", "userSpaceOnUse")
                        != "userSpaceOnUse"
                    ):
                        raise ValueError("unassessed image clip")
                    rect = rects[0]
                    limits.append(
                        _bounds(
                            _multiply(matrix, _transform(rect.get("transform", ""))),
                            float(rect.get("x", "0")),
                            float(rect.get("y", "0")),
                            float(rect.get("width", "0")),
                            float(rect.get("height", "0")),
                        )
                    )
            if opacity < 0.999 or inherited["visibility"] in ("hidden", "collapse"):
                continue
            bounds = _bounds(
                matrix,
                float(node.get("x", "0")),
                float(node.get("y", "0")),
                float(node.get("width", "0")),
                float(node.get("height", "0")),
            )
            clipped = bounds
            for limit in limits:
                clipped = _intersect(clipped, limit)
            area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
            if (
                area <= 0
                or (max(0, clipped[2] - clipped[0]) * max(0, clipped[3] - clipped[1]))
                < area * 0.98
            ):
                continue
            if node.tag == SVG + "rect":
                if (
                    inherited["fill"] != "none"
                    and float(inherited["fill-opacity"]) >= 0.999
                    and not node.get("rx")
                    and not node.get("ry")
                ):
                    covers.append((index, bounds))
                continue
            href = node.get("href") or node.get(
                "{http://www.w3.org/1999/xlink}href", ""
            )
            if not re.match(r"data:image/[^;,]+;base64,", href):
                continue
            identity = _bitmap_identity(
                base64.b64decode(href.split(",", 1)[1], validate=True)
            )
            candidates.append((index, bounds, identity))
        except (ValueError, TypeError, OSError, OverflowError):
            continue
    for index, bounds, identity in candidates:
        if any(
            later > index
            and cover[0] <= bounds[0]
            and cover[1] <= bounds[1]
            and cover[2] >= bounds[2]
            and cover[3] >= bounds[3]
            for later, cover in covers
        ):
            continue
        result[identity] += 1
    return result


def _expose_painted_dot_leaders(root):
    """Expose rhwp's actual circular dot glyphs to the same visibility checks.

    Recognize the renderer's dot radius and baseline relative to adjacent real
    text, including list bullets and leaders whose marker wraps to another line.
    Each observed dot keeps its fill/opacity/transform/clip; missing or invisible
    circles cannot manufacture the expected source character count.
    """
    for parent in list(root.iter()):
        children = list(parent)
        index = 0
        while index < len(children):
            end = index
            while end < len(children) and children[end].tag == SVG + "circle":
                end += 1
            dots = children[index:end]
            index = max(index + 1, end)
            if not dots:
                continue
            try:
                xs = [float(dot.get("cx")) for dot in dots]
                ys = [float(dot.get("cy")) for dot in dots]
                radii = [float(dot.get("r")) for dot in dots]
                gap = xs[1] - xs[0] if len(dots) > 1 else radii[0] * 4
                if (
                    not 0.1 <= min(radii) <= max(radii) <= 2.5
                    or max(ys) - min(ys) > 0.05
                    or max(radii) - min(radii) > 0.05
                    or not 2 * max(radii) <= gap <= 8 * max(radii)
                    or any(abs((b - a) - gap) > 0.05 for a, b in zip(xs, xs[1:]))
                ):
                    continue
                neighbours = []
                start = end - len(dots)
                if start:
                    neighbours.append((children[start - 1], True))
                if end < len(children):
                    neighbours.append((children[end], False))
                adjacent_text = False
                for neighbour, before in neighbours:
                    if neighbour.tag != SVG + "text":
                        continue
                    size = float(neighbour.get("font-size", "0"))
                    anchor = _bounds(
                        _transform(neighbour.get("transform", "")),
                        float(neighbour.get("x", "0")),
                        float(neighbour.get("y", "0")), 0, 0,
                    )
                    distance = xs[0] - anchor[0] if before else anchor[0] - xs[-1]
                    numbered_leader = (
                        not before and len(dots) >= 3
                        and re.fullmatch(r"[①-⑳]", "".join(neighbour.itertext()).strip())
                        and 0 <= distance <= gap * 4
                        and 0 <= anchor[1] - ys[-1] <= max(radii) * 7
                    )
                    if numbered_leader or (size > 0 and abs(radii[0] - size * .08) <= .01
                        and abs(anchor[1] - ys[0] - size * .35) <= .1
                        and 0 <= distance <= size * 1.6):
                        adjacent_text = True
                        break
                if not adjacent_text:
                    continue
            except (ValueError, TypeError):
                continue
            for dot, x, y, radius in zip(dots, xs, ys, radii):
                dot.tag = SVG + "text"
                dot.set("x", str(x - radius))
                dot.set("y", str(y + radius * 0.6))
                dot.set("font-size", str(radius * 2))
                dot.set("textLength", str(radius * 2))
                dot.text = "·"


def _visible_svg_text(svg):
    root = etree.fromstring(svg.encode())
    _expose_painted_dot_leaders(root)
    view = [float(x) for x in root.get("viewBox", "").split()]
    viewport = (
        (view[0], view[1], view[0] + view[2], view[1] + view[3])
        if len(view) == 4
        else (0, 0, float(root.get("width")), float(root.get("height")))
    )
    clips = {node.get("id"): node for node in root.iter(SVG + "clipPath")}
    visible = []
    invisible = []
    unassessed = []
    for text in root.iter(SVG + "text"):
        if any(etree.QName(a).localname in {"defs", "pattern", "clipPath", "mask", "symbol"}
               for a in text.iterancestors()):
            continue
        value = "".join(text.itertext())
        if not value.strip():
            continue
        try:
            inherited = {
                "fill": "#000000",
                "fill-opacity": "1",
                "font-size": "16",
                "visibility": "visible",
            }
            opacity = 1.0
            matrix = IDENTITY
            limits = [viewport]
            displayed = True
            for ancestor in [*reversed(list(text.iterancestors())), text]:
                style = _style(ancestor)
                displayed = displayed and style.get("display") != "none"
                opacity *= float(style.get("opacity", "1"))
                matrix = _multiply(matrix, _transform(style.get("transform", "")))
                inherited.update(
                    {
                        key: style[key]
                        for key in (
                            "fill",
                            "fill-opacity",
                            "font-size",
                            "visibility",
                            "text-anchor",
                        )
                        if key in style
                    }
                )
                clip = style.get("clip-path")
                if clip and clip != "none":
                    match = re.fullmatch(r"url\(#([^)]*)\)", clip)
                    definition = clips.get(match[1]) if match else None
                    rects = (
                        definition.findall(SVG + "rect")
                        if definition is not None
                        else []
                    )
                    if (
                        len(rects) != 1
                        or definition.get("clipPathUnits", "userSpaceOnUse")
                        != "userSpaceOnUse"
                    ):
                        raise ValueError("unassessed SVG clip")
                    rect = rects[0]
                    local = _multiply(matrix, _transform(rect.get("transform", "")))
                    limits.append(
                        _bounds(
                            local,
                            float(rect.get("x", "0")),
                            float(rect.get("y", "0")),
                            float(rect.get("width", "0")),
                            float(rect.get("height", "0")),
                        )
                    )
            opacity *= float(inherited["fill-opacity"])
            size = float(re.sub(r"px$", "", inherited["font-size"]))
            x = float(text.get("x", "0"))
            y = float(text.get("y", "0"))
            width = float(
                text.get(
                    "textLength",
                    str(size * sum(1 if ord(c) > 255 else 0.6 for c in value)),
                )
            )
            if inherited.get("text-anchor") == "middle":
                x -= width / 2
            elif inherited.get("text-anchor") == "end":
                x -= width
            # Baseline-to-ascent band; demand actual interior intersection, not
            # just an SVG element whose coordinates lie beyond the page clip.
            bounds = _bounds(matrix, x, y - size * 0.8, width, size)
            clipped = bounds
            for limit in limits:
                clipped = _intersect(clipped, limit)
            usable = clipped[2] - clipped[0] > 0.1 and clipped[3] - clipped[1] > 0.1
            painted = (
                displayed
                and inherited["visibility"] not in ("hidden", "collapse")
                and size > 0
                and width > 0
                and opacity > 0
                and _contrast_on_white(inherited["fill"], max(0, min(1, opacity))) >= 3
            )
            (visible if painted and usable else invisible).append(value)
        except (ValueError, TypeError, OverflowError):
            unassessed.append(value)
    return "".join(visible), invisible, unassessed


def inspect_question_rendering(output: Path, renderer) -> dict:
    if renderer is None:
        return {"available": False, "ok": None, "reason": "renderer_unavailable"}
    chunks = []
    unsupported = 0
    native_invisible = []
    backgrounds = Counter()
    pictures = Counter()
    floating_pictures = Counter()
    with zipfile.ZipFile(output) as archive:
        header = etree.fromstring(archive.read("Contents/header.xml"))
        styles = {style.get("id"): style for style in header.iter(HH + "charPr")}
        manifest = etree.fromstring(archive.read("Contents/content.hpf"))
        hrefs = {
            node.get("id"): node.get("href", "")
            for node in manifest.iter("{http://www.idpf.org/2007/opf/}item")
        }
        from .pdf_source_backgrounds import native_background_assets

        for name in archive.namelist():
            if not re.fullmatch(r"Contents/section\d+\.xml", name):
                continue
            root = etree.fromstring(archive.read(name))
            for _, payload in native_background_assets(root, header, hrefs, archive):
                backgrounds[_bitmap_identity(payload)] += 1
            for picture in root.iter(HP + "pic"):
                pos = picture.find(HP + "pos")
                bitmap = picture.find(".//{http://www.hancom.co.kr/hwpml/2011/core}img")
                href = hrefs.get(bitmap.get("binaryItemIDRef")) if bitmap is not None else None
                if not href or href not in archive.namelist():
                    native_invisible.append({"kind": "unresolved_picture"})
                    continue
                identity = _bitmap_identity(archive.read(href))
                pictures[identity] += 1
                if pos is None or pos.get("treatAsChar") != "0":
                    continue
                floating_pictures[identity] += 1
                paragraph = picture.getparent().getparent()
                if not any(a.tag == HP + "drawText" for a in paragraph.iterancestors()):
                    chunks.extend(re.sub(r"\s+", "", t.text or "")
                                  for t in paragraph.findall(HP + "run/" + HP + "t")
                                  if len(re.sub(r"\s+", "", t.text or "")) >= 4)
            for draw in root.findall(".//" + HP + "drawText"):
                unsupported += len(draw.findall(".//" + HP + "tbl//" + HP + "tbl"))
                for node in draw.iter(HP + "t"):
                    value = re.sub(r"\s+", "", "".join(node.itertext()))
                    if not value:
                        continue
                    if len(value) >= 4:
                        chunks.append(value)
                    run = next(
                        (a for a in node.iterancestors() if a.tag == HP + "run"), None
                    )
                    style = (
                        styles.get(run.get("charPrIDRef")) if run is not None else None
                    )
                    if (
                        style is None
                        or float(style.get("height", "0")) <= 0
                        or _contrast_on_white(style.get("textColor", "#000000")) < 3
                    ):
                        native_invisible.append(
                            {
                                "question": draw.get("name"),
                                "kind": "text",
                                "text": value[:80],
                            }
                        )
                for equation in draw.iter(HP + "equation"):
                    if (
                        float(equation.get("baseUnit", "0")) <= 0
                        or _contrast_on_white(equation.get("textColor", "#000000")) < 3
                    ):
                        native_invisible.append(
                            {
                                "question": draw.get("name"),
                                "kind": "equation",
                                "text": equation.findtext(HP + "script", "")[:80],
                            }
                        )
    # Short labels such as (가) are semantically complete. The usual four-
    # character prose chunk floor must not hide a reader dropping their boxes.
    from .pdf_inline_labels import native_inline_labels
    label_roots = []
    with zipfile.ZipFile(output) as package:
        for name in package.namelist():
            if re.fullmatch(r'Contents/section\d+\.xml', name):
                label_roots.append(etree.fromstring(package.read(name)))
    required_labels = native_inline_labels(label_roots)
    painted_labels = []
    document = renderer.parse(str(output))
    visible = []
    invisible = []
    unassessed = []
    painted_images = Counter()
    for page in range(document.page_count):
        svg = document.render_svg(page)
        if required_labels:
            from .pdf_inline_label_rendering import painted_label_frames
            painted_labels.extend(painted_label_frames(svg, {entry['text'] for entry in required_labels}))
        text, hidden, unknown = _visible_svg_text(svg)
        if backgrounds or pictures:
            painted_images.update(_visible_svg_images(svg))
        visible.append(text)
        invisible.extend(hidden)
        unassessed.extend(unknown)
    rendered = re.sub(r"\s+", "", "".join(visible))
    required = Counter(chunks)
    missing = sorted(
        value for value, count in required.items() if rendered.count(value) < count
    )
    missing_backgrounds = backgrounds - painted_images
    missing_pictures = pictures - (painted_images - backgrounds)
    missing_floating_pictures = floating_pictures - (painted_images - backgrounds)
    from .pdf_inline_label_rendering import missing_label_frames
    missing_labels = missing_label_frames(required_labels, painted_labels)
    return {
        "available": True,
        "ok": not missing
        and not unsupported
        and not native_invisible
        and not unassessed
        and not missing_backgrounds
        and not missing_pictures
        and not missing_labels,
        "checked_text_chunks": len(chunks),
        "missing_rendered_text": missing,
        "checked_inline_label_instances": len(required_labels),
        "missing_rendered_inline_labels": missing_labels,
        "checked_background_instances": sum(backgrounds.values()),
        "checked_picture_instances": sum(pictures.values()),
        "missing_rendered_pictures": [
            {"pixel_identity": identity, "count": count}
            for identity, count in sorted(missing_pictures.items())
        ],
        "checked_floating_picture_instances": sum(floating_pictures.values()),
        "missing_rendered_floating_pictures": [
            {"pixel_identity": identity, "count": count}
            for identity, count in sorted(missing_floating_pictures.items())
        ],
        "missing_rendered_backgrounds": [
            {"pixel_identity": identity, "count": count}
            for identity, count in sorted(missing_backgrounds.items())
        ],
        "unsupported_nested_tables": unsupported,
        "invisible_native_content": native_invisible,
        "invisible_svg_text_nodes": len(invisible),
        "unassessed_svg_text_nodes": len(unassessed),
        "rendered_pages": int(document.page_count),
    }
