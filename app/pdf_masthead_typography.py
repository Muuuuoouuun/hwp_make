"""Measure native masthead text, typography and its source flow geometry."""

import re
from copy import deepcopy
from statistics import median
from lxml import etree
from .pdf_source_page_memo import source_text_dict

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def measure_source_masthead(page, body_top, *, subject_area=""):
    from .pdf_layout_writer import _recover_pdf_font_name

    all_lines = [line for block in source_text_dict(page)["blocks"]
                 for line in block.get("lines", [])]
    lines = [line for line in all_lines if line["bbox"][3] < body_top]
    def text(line):
        return "".join(s.get("text", "") for s in line.get("spans", [])).strip()
    titles = [line for line in lines if re.search(r"\d{4}학년도.*문제지", text(line))]
    areas = [
        line for line in lines if re.fullmatch(r".{1,16}영역(?:\s*\([^\n]+\))?", text(line))
    ]
    if not titles:
        # Only a single prominent heading aligned with the first question's
        # left edge establishes left alignment. A long centered title may
        # also begin near that edge, so require its midpoint to be leftward.
        if not areas and len(lines) == 1:
            line = lines[0]
            x0, _, x1, _ = line["bbox"]
            heading = text(line)
            if (1 < len(heading) <= 80 and (x0 + x1) / 2 < page.rect.width * .4
                    and max(s["size"] for s in line["spans"]) >= 16
                    and any(abs(q["bbox"][0] - x0) <= 2 and q["bbox"][1] >= body_top
                            and re.match(r"^\d{1,3}[.)]\s", text(q)) for q in all_lines)):
                return {"left_title": heading, "left_pt": x0, "top_pt": line["bbox"][1],
                        "source_page_width_pt": page.rect.width}
        return {}
    area = max(areas, key=lambda line: max(s.get("size", 0) for s in line["spans"])) if areas else None
    title = (min(titles, key=lambda line: abs(line["bbox"][1] - area["bbox"][1]))
             if area is not None else titles[0])
    period = next((line for line in lines if re.fullmatch(r"제\s*\d+\s*교시", text(line))), None)
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

    area_record = record(area) if area is not None else None
    if (area_record is None and period is not None
        and re.fullmatch(r"[가-힣]{1,8}\s*영역", subject_area.strip())):
        # Some KICE PDFs store the large subject label as an image. Recreate
        # just that label as editable text at the image's source geometry.
        title_bottom = float(title["bbox"][3])
        candidates = []
        for image in page.get_images(full=True):
            for rect in page.get_image_rects(image[0]):
                center = (rect.x0 + rect.x1) / 2
                if (title_bottom <= rect.y0 < rect.y1 < body_top
                    and 70 <= rect.width <= page.rect.width * .4
                    and 20 <= rect.height <= 80
                    and 2.5 <= rect.width / rect.height <= 6
                    and abs(center - page.rect.width / 2) <= page.rect.width * .08):
                    candidates.append(rect)
        if len(candidates) == 1:
            rect = candidates[0]
            size = max(16.0, min(36.0, rect.height * .72))
            glyphs = len(re.sub(r"\s", "", subject_area))
            width = max(85, min(145, round(rect.width / (size * glyphs) * 100)))
            area_record = {
                "text": subject_area.strip(),
                "bbox_pt": [rect.x0, rect.y0, rect.x1, rect.y1],
                "baseline_pt": rect.y0 + rect.height * .84,
                "spans": [{"text": subject_area.strip(), "font_name": "돋움",
                           "font_size_pt": size, "bold": True,
                           "font_width_percent": width, "letter_spacing_percent": 0}],
            }
    if area_record is None:
        return {}

    numbers = [s for line in lines for s in line["spans"]
               if re.fullmatch(r"\d{1,3}", str(s.get("text", "")).strip())
               and s["bbox"][0] > page.rect.width * .75]
    rules = []
    for drawing in page.get_drawings() if hasattr(page, "get_drawings") else []:
        for item in drawing["items"]:
            if (item[0] == "l" and abs(item[1].y - item[2].y) < .5
                and area_record["bbox_pt"][3] < item[1].y < body_top
                and abs(item[2].x - item[1].x) > page.rect.width * .65):
                rules.append({"y_pt": item[1].y, "left_pt": min(item[1].x, item[2].x),
                              "right_pt": max(item[1].x, item[2].x),
                              "width_pt": float(drawing.get("width") or 0)})
    result = {
        "source_page_width_pt": page.rect.width,
        "title": record(title, is_title=True),
        "area": area_record,
        "period": text(period) if period is not None else "",
    }
    if period is not None:
        result["period_geometry"] = record(period)
    if len(numbers) == 1:
        result["page_number"] = record({"spans": numbers})
    if rules:
        result["bottom_rule"] = min(rules, key=lambda rule: rule["y_pt"])
    return result


def _position_first_title(section, header, title, title_style, page, target_top):
    # Only the template's single empty section-control line may give up space.
    # Transfer its removed height to the title's trailing margin to keep both
    # question columns and the following page at their existing positions.
    paragraphs = section.findall(HP + "p")
    if len(paragraphs) < 2 or paragraphs[1] is not title:
        return
    lead = paragraphs[0]
    runs = lead.findall(HP + "run")
    if (not runs or lead.find(".//" + HP + "secPr") is None
            or any((t.text or "").strip() for t in lead.iter(HP + "t"))
            or any(child.tag not in (HP + "secPr", HP + "ctrl", HP + "t")
                   for run in runs for child in run)):
        return
    props = header.find(".//" + HH + "paraProperties")
    style = props.find(HH + "paraPr[@id='" + lead.get("paraPrIDRef") + "']")
    char = header.find(".//" + HH + "charPr[@id='" + runs[0].get("charPrIDRef") + "']")
    if style is None or char is None:
        return
    spacing = style.find(".//" + HH + "lineSpacing")
    if spacing is None or spacing.get("type") != "PERCENT":
        return
    old_height = round(int(char.get("height")) * int(spacing.get("value")) / 100)
    margin = page.find(HP + "margin")
    lead_height = round(target_top - int(margin.get("top")) - int(margin.get("header", "0")))
    if not 100 <= lead_height < old_height:
        return
    removed = old_height - lead_height
    fixed = deepcopy(style)
    fixed.set("id", str(max(int(p.get("id")) for p in props) + 1))
    for node in fixed.iter(HH + "lineSpacing"):
        node.set("type", "FIXED")
        node.set("unit", "HWPUNIT")
        node.set("value", str(lead_height))
    props.append(fixed)
    props.set("itemCnt", str(len(props)))
    lead.set("paraPrIDRef", fixed.get("id"))
    for edge in title_style.findall(".//" + HH + "margin/{*}next"):
        edge.set("value", str(int(edge.get("value", "0")) + removed))
        edge.set("unit", "HWPUNIT")
    cache = lead.find(HP + "linesegarray/" + HP + "lineseg")
    if cache is not None:
        # Keep the estimated prologue height consistent when question spacing
        # is calculated from the cached line metrics later in this pass.
        cache.set("spacing", str(int(cache.get("spacing", "0")) - removed))


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
    if "left_title" in meta:
        matches = [p for p, text in texts if compact(text) == compact(meta["left_title"])]
        if len(matches) != 1:
            return False
        title = matches[0]
        page = section.find(".//" + HP + "pagePr")
        properties = header.find(".//" + HH + "paraProperties")
        base = next(p for p in properties if p.get("id") == title.get("paraPrIDRef"))
        style = deepcopy(base)
        identifier = str(max(int(p.get("id")) for p in properties) + 1)
        style.set("id", identifier)
        style.find(HH + "align").set("horizontal", "LEFT")
        inset = meta["left_pt"] * int(page.get("width")) / meta["source_page_width_pt"]
        inset -= int(page.find(HP + "margin").get("left"))
        for margin in style.findall(".//" + HH + "margin"):
            left = margin.find("{*}left")
            if left is not None:
                left.set("unit", "HWPUNIT")
                left.set("value", str(max(0, round(inset))))
        properties.append(style)
        properties.set("itemCnt", str(len(properties)))
        title.set("paraPrIDRef", identifier)
        if "top_pt" in meta:
            scale = int(page.get("width")) / meta["source_page_width_pt"]
            _position_first_title(section, header, title, style, page, meta["top_pt"] * scale)
        return True
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
