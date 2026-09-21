"""Measure native masthead text, typography and its source flow geometry."""

import re
from statistics import median
from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def measure_source_masthead(page, body_top):
    from .pdf_layout_writer import _recover_pdf_font_name

    lines = [
        line
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        if line["bbox"][3] < body_top
    ]
    def text(line):
        return "".join(s.get("text", "") for s in line.get("spans", [])).strip()
    titles = [line for line in lines if re.search(r"\d{4}학년도.*문제지", text(line))]
    areas = [
        line for line in lines if re.fullmatch(r".{1,16}영역(?:\s*\([^\n]+\))?", text(line))
    ]
    if not titles or not areas:
        return {}
    area = max(areas, key=lambda line: max(s.get("size", 0) for s in line["spans"]))
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
        "area": record(area),
        "period": text(period) if period is not None else "",
    }
    if period is not None:
        result["period_geometry"] = record(period)
    if len(numbers) == 1:
        result["page_number"] = record({"spans": numbers})
    if rules:
        result["bottom_rule"] = min(rules, key=lambda rule: rule["y_pt"])
    return result


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
