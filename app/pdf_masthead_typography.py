"""Measure native masthead text, typography and its source flow geometry."""

import re
from statistics import median
from lxml import etree
from .pdf_source_page_memo import source_text_dict
from .pdf_masthead_visibility import visible_masthead_lines

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def _heading_image_boxes(page, body_top):
    width = float(page.rect.width)
    return [list(map(float, image["bbox"])) for image in page.get_image_info()
            if 0 < image["bbox"][1] < image["bbox"][3] < body_top
            and abs((image["bbox"][0] + image["bbox"][2]) / 2 - width / 2) <= width * .06
            and width * .1 <= image["bbox"][2] - image["bbox"][0] <= width * .4
            and 12 <= image["bbox"][3] - image["bbox"][1] <= 65
            and 2 <= (image["bbox"][2] - image["bbox"][0]) / (image["bbox"][3] - image["bbox"][1]) <= 8]


def _visible_header_rules(page, image_box, body_top):
    rules = {}
    for drawing in page.get_drawings():
        if (not drawing.get("width") or drawing.get("stroke_opacity", 0) <= 0
            or drawing.get("color") != (0., 0., 0.)
            or drawing.get("dashes") not in (None, "", "[] 0")):
            continue
        for item in drawing.get("items", []):
            if (item[0] == "l" and abs(item[1].y - item[2].y) < .5
                and image_box[3] < item[1].y < body_top
                and min(item[1].x, item[2].x) < page.rect.width * .2
                and max(item[1].x, item[2].x) > page.rect.width * .8
                and abs(item[2].x - item[1].x) > page.rect.width * .65):
                rule = {"y_pt": item[1].y, "left_pt": min(item[1].x, item[2].x),
                        "right_pt": max(item[1].x, item[2].x), "width_pt": float(drawing["width"])}
                rules[tuple(round(v, 2) for v in rule.values())] = rule
    return list(rules.values())


def _unvariant_mock_proof(page, body_top, area_hint):
    """Identify an official English mock from visible first-page fields.

    A subject hint or a central picture alone is insufficient. The original
    official mock title, third period, printed first page, unique image slot,
    and a visible full-width separator must agree, with no extra header text.
    """
    if (page.number != 0 or re.sub(r"\s+", "", str(area_hint or "")) != "영어영역"
        or not hasattr(page, "get_image_info")):
        return None
    lines = visible_masthead_lines(page, body_top)
    text = lambda line: "".join(s.get("text", "") for s in line["spans"]).strip()
    compact = lambda value: re.sub(r"\s+", "", value)
    titles = [line for line in lines if re.fullmatch(
        r"\d{4}학년도대학수학능력시험(?:6|9)월모의평가문제지", compact(text(line)))]
    periods = [line for line in lines if compact(text(line)) == "제3교시"]
    numbers = [line for line in lines if text(line) == "1"
               and line["bbox"][0] > page.rect.width * .75]
    images = _heading_image_boxes(page, body_top)
    if len(titles) != 1 or len(periods) != 1 or len(numbers) != 1 or len(images) != 1:
        return None
    if any(line not in (titles[0], periods[0], numbers[0]) for line in lines):
        return None
    image, title, period, number = images[0], titles[0], periods[0], numbers[0]
    width = float(page.rect.width)
    if (not title["bbox"][3] < image[1]
        or abs((title["bbox"][0] + title["bbox"][2]) / 2 - width / 2) > width * .08
        or not width * .35 < title["bbox"][2] - title["bbox"][0] < width * .85
        or period["bbox"][2] > width * .3
        or not image[1] <= (period["bbox"][1] + period["bbox"][3]) / 2 <= image[3]
        or not title["bbox"][1] - 15 <= number["bbox"][1] <= title["bbox"][3]):
        return None
    rules = _visible_header_rules(page, image, body_top)
    if len(rules) != 1:
        return None
    return {"title": text(title), "period": "제3교시", "image_bbox_pt": image,
            "bottom_rule": rules[0], "source_page_width_pt": width}


def _running_unvariant_mock(page, body_top, area_hint, lines, numbers):
    if page.number < 1 or len(numbers) != 1 or len(lines) != 1:
        return None
    from .pdf_layout_writer import _page_body_top
    first = page.parent[0]
    proof = _unvariant_mock_proof(first, _page_body_top(first), area_hint)
    if proof is None or abs(proof["source_page_width_pt"] - page.rect.width) > .5:
        return None
    number = numbers[0]
    if "".join(s.get("text", "") for s in number["spans"]).strip() != str(page.number + 1):
        return None
    # The source itself proves the alternating printed-number rail.
    if ((page.number + 1) % 2 == 0) != (number["bbox"][2] < page.rect.width * .25):
        return None
    images = _heading_image_boxes(page, body_top)
    if len(images) != 1:
        return None
    image, full_image = images[0], proof["image_bbox_pt"]
    ratio = (image[2] - image[0]) / (image[3] - image[1])
    full_ratio = (full_image[2] - full_image[0]) / (full_image[3] - full_image[1])
    if abs(ratio / full_ratio - 1) > .02:
        return None
    rules = _visible_header_rules(page, image, body_top)
    if len(rules) != 1 or any(abs(rules[0][key] - proof["bottom_rule"][key]) > .5
                            for key in ("left_pt", "right_pt", "width_pt")):
        return None
    return proof, image, rules[0]


def _raster_english_area(page, lines, titles, body_top, area_hint):
    """Use one measured heading image slot for an independently verified area.

    The image supplies only geometry. The known English-area text stays native;
    neither the image nor any source prose is copied into the output header.
    Refuse ambiguous images or documents without the other official masthead
    fields, rather than guessing an area from arbitrary artwork.
    """
    from .pdf_layout_writer import _recover_pdf_font_name

    if re.sub(r"\s+", "", str(area_hint or "")) != "영어영역":
        return None
    if not hasattr(page, "get_image_info"):
        return None
    text = lambda line: "".join(span.get("text", "") for span in line.get("spans", [])).strip()
    period = next((line for line in lines if re.fullmatch(r"제\s*\d+\s*교시", text(line))), None)
    variant = next((line for line in lines if text(line) in ("홀수형", "짝수형")), None)
    mock_proof = _unvariant_mock_proof(page, body_top, area_hint) if variant is None else None
    if period is None or (variant is None and mock_proof is None):
        return None
    page_width = float(page.rect.width)
    title_bottom = min(float(line["bbox"][3]) for line in titles)
    candidates = []
    for image in page.get_image_info():
        left, top, right, bottom = map(float, image["bbox"])
        width, height = right - left, bottom - top
        if (title_bottom < top < bottom < body_top
            and abs((left + right) / 2 - page_width / 2) <= page_width * .06
            and page_width * .1 <= width <= page_width * .4
            and 12 <= height <= 65 and 2 <= width / height <= 8):
            candidates.append((left, top, right, bottom))
    if len(candidates) != 1:
        return None
    left, top, right, bottom = candidates[0]
    area_text = "영어 영역"
    height = bottom - top
    # The source image has no font metadata. Use its measured em box and the
    # source's independent Gothic variant face when one exists. An unlabelled
    # official mock uses a native Gothic fallback fitted to the same slot.
    font = (_recover_pdf_font_name(variant["spans"][0].get("font", "")).lstrip("*")
            if variant is not None else "Malgun Gothic")
    result = {
        "text": area_text,
        "bbox_pt": [left, top, right, bottom],
        "baseline_pt": top + height * .85,
        "raster_geometry": True,
        "spans": [{"text": area_text, "font_name": font or "Malgun Gothic",
                   "font_size_pt": height, "bold": True,
                   "font_width_percent": (right - left) / (height * 4.5) * 100,
                   "letter_spacing_percent": 0}],
    }
    if mock_proof:
        result["unvariant_mock"] = mock_proof
    return result


def measure_source_masthead(page, body_top, *, area_hint=""):
    from .pdf_layout_writer import _recover_pdf_font_name

    lines = visible_masthead_lines(page, body_top)
    def text(line):
        return "".join(s.get("text", "") for s in line.get("spans", [])).strip()
    titles = [line for line in lines if re.search(r"\d{4}학년도.*문제지", text(line))]
    areas = [
        line for line in lines if re.fullmatch(r".{1,16}영역(?:\s*\([^\n]+\))?", text(line))
    ]
    if not titles:
        return {}
    raster_area = None
    if areas:
        area = max(areas, key=lambda line: max(s.get("size", 0) for s in line["spans"]))
    else:
        raster_area = _raster_english_area(page, lines, titles, body_top, area_hint)
        if raster_area is None:
            return {}
        area = {"bbox": raster_area["bbox_pt"]}
    title = min(titles, key=lambda line: abs(line["bbox"][1] - area["bbox"][1]))
    raw_spans = {tuple(s.get("bbox", ())): s for b in page.get_text("rawdict")["blocks"]
                 for l in b.get("lines", []) for s in l.get("spans", [])}

    def record(line, *, is_title=False):
        spans = line["spans"]
        if is_title:
            # PDF text extraction may put the large page number on the same
            # line as the title. It is not part of the title's text or size.
            raw_text = "".join(s.get("text", "") for s in line["spans"])
            spans, remaining = [], raw_text.find("문제지") + len("문제지")
            for span in line["spans"]:
                part = str(span.get("text", ""))[:remaining]
                if part:
                    spans.append({**span, "text": part})
                remaining -= len(part)
                if remaining <= 0:
                    break
        measured_spans = []
        for span in spans:
            chars = raw_spans.get(tuple(span.get("bbox", ())), {}).get("chars", [])[:len(span.get("text", ""))]
            tracking, ratios = [], []
            for left, right in zip(chars, chars[1:]):
                if re.fullmatch("[가-힣]", left.get("c", "")) and re.fullmatch("[가-힣]", right.get("c", "")):
                    size = float(span["size"])
                    ratios.append((left["bbox"][2] - left["bbox"][0]) / size * 100)
                    tracking.append((right["origin"][0] - left["bbox"][2]) / size * 100)
            measured_spans.append({
                "text": span.get("text", ""),
                "font_name": _recover_pdf_font_name(span.get("font", "")).lstrip("*"),
                "font_size_pt": span["size"], "bold": bool(span.get("flags", 0) & 16),
                "font_width_percent": median(ratios) if ratios else 100,
                "letter_spacing_percent": median(tracking) if tracking else 0,
            })
        baselines = [s["origin"][1] for s in spans if s.get("origin")]
        return {
            "text": "".join(s.get("text", "") for s in spans).strip(),
            "bbox_pt": [min(s["bbox"][0] for s in spans), min(s["bbox"][1] for s in spans),
                        max(s["bbox"][2] for s in spans), max(s["bbox"][3] for s in spans)],
            "baseline_pt": median(baselines) if baselines else None,
            "spans": measured_spans,
        }

    period = next((line for line in lines if re.fullmatch(r"제\s*\d+\s*교시", text(line))), None)
    variant = next((line for line in lines if text(line) in ("홀수형", "짝수형")), None)
    numbers = [s for line in lines for s in line["spans"]
               if re.fullmatch(r"\d{1,3}", str(s.get("text", "")).strip())
               and s["bbox"][0] > page.rect.width * .75]
    rules = []
    for drawing in page.get_drawings() if hasattr(page, "get_drawings") else []:
        for item in drawing["items"]:
            if (item[0] == "l" and abs(item[1].y - item[2].y) < .5
                and area["bbox"][3] < item[1].y < body_top
                and abs(item[2].x - item[1].x) > page.rect.width * .65):
                rules.append({"y_pt": item[1].y, "left_pt": min(item[1].x, item[2].x),
                              "right_pt": max(item[1].x, item[2].x),
                              "width_pt": float(drawing.get("width") or 0)})
    result = {
        "source_page_width_pt": page.rect.width,
        "title": record(title, is_title=True),
        "area": raster_area or record(area),
        "period": text(period) if period is not None else "",
    }
    if raster_area and raster_area.get("unvariant_mock"):
        result["unvariant_mock"] = raster_area["unvariant_mock"]
    if period is not None:
        result["period_geometry"] = record(period)
    if variant is not None:
        result["variant_geometry"] = record(variant)
    if len(numbers) == 1:
        result["page_number"] = record({"spans": numbers})
    if rules:
        result["bottom_rule"] = min(rules, key=lambda rule: rule["y_pt"])
    return result


def _page_field(page, line):
    """Measure one independently identified native masthead field."""
    from .pdf_layout_writer import _recover_pdf_font_name

    raw = {tuple(s.get("bbox", ())): s for b in source_text_dict(page, "rawdict")["blocks"]
           for l in b.get("lines", []) for s in l.get("spans", [])}
    measured = []
    for span in line["spans"]:
        chars = raw.get(tuple(span.get("bbox", ())), {}).get("chars", [])
        ratios, tracking = [], []
        for left, right in zip(chars, chars[1:]):
            if re.fullmatch("[가-힣]", left.get("c", "")) and re.fullmatch("[가-힣]", right.get("c", "")):
                size = float(span["size"])
                ratios.append((left["bbox"][2] - left["bbox"][0]) / size * 100)
                tracking.append((right["origin"][0] - left["bbox"][2]) / size * 100)
        measured.append({"text": span.get("text", ""),
                         "font_name": _recover_pdf_font_name(span.get("font", "")).lstrip("*"),
                         "font_size_pt": span["size"], "bold": bool(span.get("flags", 0) & 16),
                         "font_width_percent": median(ratios) if ratios else 100,
                         "letter_spacing_percent": median(tracking) if tracking else 0})
    spans = line["spans"]
    return {"text": "".join(s.get("text", "") for s in spans).strip(),
            "bbox_pt": [min(s["bbox"][0] for s in spans), min(s["bbox"][1] for s in spans),
                        max(s["bbox"][2] for s in spans), max(s["bbox"][3] for s in spans)],
            "baseline_pt": median(s["origin"][1] for s in spans), "spans": measured}


def measure_source_page_masthead(page, body_top, *, area_hint=""):
    """Identify each full/running English masthead from its own source evidence.

    Raster area names require an independently verified area and the official
    variant, printed page number and separating rule. Only geometry is read
    from that heading image; its pixels never enter the editable header.
    """
    if re.sub(r"\s+", "", str(area_hint or "")) != "영어영역":
        return {}
    full = measure_source_masthead(page, body_top, area_hint=area_hint)
    if full:
        if re.sub(r"\s+", "", full["area"]["text"]) != "영어영역":
            return {}
        meta = {**full, "kind": "full"}
    else:
        lines = visible_masthead_lines(page, body_top)
        text = lambda line: "".join(s.get("text", "") for s in line["spans"]).strip()
        variants = [line for line in lines if text(line) in ("홀수형", "짝수형")]
        grades = [line for line in lines if re.fullmatch(r"고\s*[123]", text(line))]
        numbers = [line for line in lines if re.fullmatch(r"\d{1,3}", text(line))
                   and (line["bbox"][2] < page.rect.width * .25
                        or line["bbox"][0] > page.rect.width * .75)]
        unvariant = (_running_unvariant_mock(page, body_top, area_hint, lines, numbers)
                     if not variants and not grades else None)
        if (len(variants) + len(grades) != 1 and unvariant is None) or len(numbers) != 1:
            return {}
        areas = [line for line in lines if re.sub(r"\s+", "", text(line)) == "영어영역"]
        if len(areas) == 1:
            area = _page_field(page, areas[0])
        elif areas:
            return {}
        else:
            if not variants and unvariant is None:
                return {}
            images = [image["bbox"] for image in page.get_image_info()
                      if 0 < image["bbox"][1] < image["bbox"][3] < body_top
                      and abs((image["bbox"][0] + image["bbox"][2]) / 2 - page.rect.width / 2) < page.rect.width * .06
                      and page.rect.width * .1 <= image["bbox"][2] - image["bbox"][0] <= page.rect.width * .4
                      and 12 <= image["bbox"][3] - image["bbox"][1] <= 65
                      and 2 <= (image["bbox"][2] - image["bbox"][0]) / (image["bbox"][3] - image["bbox"][1]) <= 8]
            if len(images) != 1:
                return {}
            left, top, right, bottom = images[0]
            font_name = (_page_field(page, variants[0])["spans"][0]["font_name"]
                         if variants else "Malgun Gothic")
            height = bottom - top
            area = {"text": "영어 영역", "bbox_pt": list(images[0]),
                    "baseline_pt": top + height * .85, "raster_geometry": True,
                    "spans": [{"text": "영어 영역", "font_name": font_name,
                               "font_size_pt": height, "bold": True,
                               "font_width_percent": (right - left) / (height * 4.5) * 100,
                               "letter_spacing_percent": 0}]}
        rules = {}
        for drawing in page.get_drawings():
            for item in drawing.get("items", []):
                if (item[0] == "l" and abs(item[1].y - item[2].y) < .5
                    and area["bbox_pt"][3] <= item[1].y < body_top
                    and abs(item[2].x - item[1].x) > page.rect.width * .65
                    and drawing.get("width")):
                    rule = {"y_pt": item[1].y, "left_pt": min(item[1].x, item[2].x),
                            "right_pt": max(item[1].x, item[2].x), "width_pt": float(drawing["width"])}
                    rules[tuple(round(v, 2) for v in rule.values())] = rule
        if len(rules) != 1:
            return {}
        meta = {"kind": "running", "source_page_width_pt": page.rect.width,
                "area": area,
                "page_number": _page_field(page, numbers[0]), "bottom_rule": next(iter(rules.values()))}
        if variants or grades:
            meta["variant_geometry" if variants else "grade_geometry"] = _page_field(page, (variants or grades)[0])
        elif unvariant:
            meta["unvariant_mock"] = unvariant[0]
    meta.update(source_page=page.number + 1, body_top_pt=body_top)
    # Rounded field outlines are native source vector paths, not glyphs.
    outlines = []
    for field in (meta.get("period_geometry"), meta.get("variant_geometry")):
        if not field:
            continue
        bounds = field["bbox_pt"]
        candidates = []
        for drawing in page.get_drawings():
            box = drawing["rect"]
            segments = drawing.get("items", [])
            if (not drawing.get("width") or drawing.get("color") != (0., 0., 0.)
                or box.y1 >= body_top or box.width > page.rect.width * .2
                or not (box.x0 <= bounds[0] and box.x1 >= bounds[2]
                        and box.y0 <= bounds[1] + 3 and box.y1 >= bounds[3] - 3)
                or not segments or any(item[0] != "l" for item in segments)):
                continue
            if any(abs(a[2].x - b[1].x) > .5 or abs(a[2].y - b[1].y) > .5
                   for a, b in zip(segments, segments[1:])):
                continue
            points = [list(segments[0][1]), *[list(item[2]) for item in segments]]
            if max(abs(a - b) for a, b in zip(points[0], points[-1])) > .5:
                continue
            candidates.append({"bbox_pt": list(box), "width_pt": float(drawing["width"]), "points_pt": points})
        if len(candidates) == 1:
            outlines.extend(candidates)
    meta["outlines"] = outlines
    return meta


def apply_source_masthead(section, header, items, char_style):
    from .pdf_native_typography import _flow_height

    meta = next(
        (
            (item.get("layout") or {}).get("source_masthead_typography")
            for item in items
            if (item.get("layout") or {}).get("source_masthead_typography")
        ),
        None,
    )
    if not meta:
        return False
    def compact(text):
        return re.sub(r"\s+", "", text)
    texts = [
        (p, "".join(t.text or "" for t in p.findall(HP + "run/" + HP + "t")))
        for p in section.findall(HP + "p")
        if p.get("nativeSourceItem") is None
    ]
    title = next(
        (p for p, text in texts if compact(text) == compact(meta["title"]["text"])),
        None,
    )
    area_pair = next(
        (
            (p, text)
            for p, text in texts
            if compact(text).startswith(compact(meta["area"]["text"]))
        ),
        None,
    )
    if title is None or area_pair is None:
        return False
    area, area_text = area_pair
    from .pdf_masthead_flow import restore_masthead_flow
    if restore_masthead_flow(section, header, meta, title, area, char_style, items):
        return True
    old_total = round(_flow_height(title) + _flow_height(area))
    page = section.find(".//" + HP + "pagePr")
    scale = float(page.get("width")) / meta["source_page_width_pt"]
    heights = [
        max(span["font_size_pt"] for span in meta[name]["spans"]) * scale
        for name in ("title", "area")
    ]
    if sum(heights) > old_total:
        return False
    padding = old_total - sum(heights)
    budgets = [round(heights[0] + padding * 0.45), 0]
    budgets[1] = old_total - budgets[0]
    for p, name, height, budget in zip(
        (title, area), ("title", "area"), heights, budgets
    ):
        runs = p.findall(HP + "run")
        base = runs[0].get("charPrIDRef", "0")
        for run in runs:
            p.remove(run)
        for span in meta[name]["spans"]:
            style = char_style(
                base, span["font_size_pt"] * scale, span["font_name"], 0, 100, bool(span["bold"])
            )
            run = etree.SubElement(p, HP + "run", charPrIDRef=style)
            etree.SubElement(run, HP + "t").text = span["text"]
        if name == "area":
            # Keep the existing small period/variant text, never enlarge it as
            # though it were part of the measured area/subject source spans.
            original_prefix = meta["area"]["text"]
            match = re.match(
                "".join(re.escape(c) + r"\s*" for c in compact(original_prefix)),
                area_text,
            )
            tail = area_text[match.end() :] if match else ""
            if tail:
                run = etree.SubElement(p, HP + "run", charPrIDRef=base)
                etree.SubElement(run, HP + "t").text = "   " + tail.lstrip()
        cache = p.find(HP + "linesegarray")
        if cache is not None:
            p.remove(cache)
        cache = etree.SubElement(p, HP + "linesegarray")
        etree.SubElement(
            cache,
            HP + "lineseg",
            textpos="0",
            vertpos="0",
            vertsize=str(round(height)),
            textheight=str(round(height)),
            baseline=str(round(height * 0.85)),
            spacing=str(budget - round(height)),
            horzpos="0",
            horzsize=str(round(float(page.get("width")) - 11338)),
            flags="393216",
        )
    return True
