"""Separate source-proven booklet mastheads into ordinary native sections."""
from copy import deepcopy
import re

from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _printed_parity(record):
    return int(re.sub(r"\s+", "", record["page_number"]["text"])) % 2


def _coherent_running(records):
    """A repeating header needs the same source fields on every relevant page."""
    if not records:
        return False
    if len({round(float(r["source_page_width_pt"]), 2) for r in records}) != 1:
        return False
    for parity in (0, 1):
        peers = [r for r in records if _printed_parity(r) == parity]
        if not peers:
            continue
        label = ("variant_geometry" if peers[0].get("variant_geometry") else
                 "grade_geometry" if peers[0].get("grade_geometry") else None)
        if label is None:
            proofs = [r.get("unvariant_mock") or {} for r in peers]
            if (any(r.get("variant_geometry") or r.get("grade_geometry") for r in peers)
                or any(p.get("period") != "제3교시" or not re.fullmatch(
                    r"\d{4}학년도\s*대학수학능력시험\s*(?:6|9)월\s*모의평가\s*문제지", p.get("title", ""))
                    for p in proofs)
                or len({p["title"] for p in proofs}) != 1
                or any(not r["area"].get("raster_geometry") or int(r["page_number"]["text"]) != r["source_page"]
                       for r in peers)):
                return False
        elif any(not r.get(label) for r in peers):
            return False
        for key in ("area", *([label] if label else []), "page_number"):
            fields = [r[key] for r in peers]
            if key != "page_number" and len({re.sub(r"\s+", "", f["text"]) for f in fields}) != 1:
                return False
            signatures = [tuple((s["font_name"], round(s["font_size_pt"], 1), s["bold"])
                                for s in f["spans"]) for f in fields]
            if len(set(signatures)) != 1:
                return False
            for axis in (1, 3):
                if max(f["bbox_pt"][axis] for f in fields) - min(f["bbox_pt"][axis] for f in fields) > 2:
                    return False
            # The number's outside edge stays fixed as its glyph width changes.
            axes = (0, 2) if key != "page_number" else (0 if fields[0]["bbox_pt"][0] < peers[0]["source_page_width_pt"] / 2 else 2,)
            if any(max(f["bbox_pt"][axis] for f in fields) - min(f["bbox_pt"][axis] for f in fields) > 2 for axis in axes):
                return False
        rules = [r.get("bottom_rule") for r in peers]
        if not all(rules):
            return False
        if any(max(r[key] for r in rules) - min(r[key] for r in rules) > 2
               for key in ("left_pt", "right_pt", "y_pt", "width_pt")):
            return False
        outlines = [r.get("outlines", []) for r in peers]
        if len({len(group) for group in outlines}) != 1:
            return False
        for index in range(len(outlines[0])):
            shapes = [group[index] for group in outlines]
            if len({len(shape["points_pt"]) for shape in shapes}) != 1:
                return False
            values = [[shape["width_pt"], *shape["bbox_pt"],
                       *(v for point in shape["points_pt"] for v in point)] for shape in shapes]
            if any(max(axis) - min(axis) > 2 for axis in zip(*values)):
                return False
    return True


def split_measured_masthead_sections(section, paragraphs, source_groups,
                                     paragraph_sources, header, items, char_style):
    """Return all sections only when every source page proves its own header.

    Full first-page mastheads and each following run receive separate sections.
    A combined odd/even booklet therefore has four sections, retaining ordinary
    editable paragraphs and automatic page fields in its repeating headers.
    """
    from .pdf_masthead_flow import restore_measured_page_header
    from .pdf_native_typography import _number, _paginate
    from .pdf_source_spacing import (apply_source_flow_spacing, source_anchor,
                                     source_paragraph_top)

    records = next(((item.get("layout") or {}).get("source_page_mastheads")
                    for item in items if (item.get("layout") or {}).get("source_page_mastheads")), [])
    pages = sorted({int(group[0]) for group in source_groups})
    if (not paragraphs or len(paragraphs) != len(source_groups)
            or [r.get("source_page") for r in records] != pages
            or not records or records[0].get("kind") != "full"):
        return None
    metadata = {r["source_page"]: r for r in records}
    boundaries = [0]
    for index in range(1, len(paragraphs)):
        previous, current = int(source_groups[index-1][0]), int(source_groups[index][0])
        if current != previous and (metadata[current]["kind"] == "full"
                                    or metadata[previous]["kind"] == "full"):
            boundaries.append(index)
    boundaries.append(len(paragraphs))
    if len(boundaries) < 3:
        return None
    secpr = section.find(".//" + HP + "secPr")
    columns = next((c for c in section.iter(HP + "ctrl")
                    if (p := c.find(HP + "colPr")) is not None and p.get("colCount") == "2"), None)
    if secpr is None or columns is None:
        return None
    page_width = _number(secpr.find(HP + "pagePr"), "width")
    spacing = {p: [] for p in paragraphs}
    for source, layout in paragraph_sources:
        owner = source
        while owner is not None and owner not in spacing:
            owner = owner.getparent()
        if owner is None:
            return None
        spacing[owner].append(layout)
    if not all(spacing.values()):
        return None
    plans = []
    for start, end in zip(boundaries, boundaries[1:]):
        source_pages = sorted({int(g[0]) for g in source_groups[start:end]})
        peers = [metadata[p] for p in source_pages]
        kind = peers[0]["kind"]
        if (kind == "full" and len(peers) != 1
                or kind == "running" and (any(r["kind"] != "running" for r in peers)
                                            or not _coherent_running(peers))):
            return None
        printed = [int(re.sub(r"\s+", "", r["page_number"]["text"])) for r in peers]
        if printed != list(range(printed[0], printed[0] + len(printed))):
            return None
        anchors = []
        for source, layout in paragraph_sources:
            anchor = source_anchor([layout])
            if anchor and anchor[0] in source_pages:
                anchors.append(source_paragraph_top(source, layout, page_width))
        if not anchors or any(a is None for a in anchors):
            return None
        body_top = min(anchors)
        if not 0 < body_top < _number(secpr.find(HP + "pagePr"), "height") * .3:
            return None
        # Check geometry without changing the caller's header/style registries.
        # The real callbacks allocate styles only once after all plans pass.
        probe_section = deepcopy(section)
        probe_header = deepcopy(header)
        def probe_style(base, *args, **kwargs):
            return base
        header_peers = [("BOTH", peers[0])] if kind == "full" else [
            (name, next(r for r in peers if _printed_parity(r) == parity))
            for name, parity in (("EVEN", 0), ("ODD", 1))
            if any(_printed_parity(r) == parity for r in peers)]
        header_top = min((field["baseline_pt"] - max(s["font_size_pt"] for s in field["spans"]) * .85)
                         * page_width / record["source_page_width_pt"]
                         for _, record in header_peers
                         for key in ("title", "area", "period_geometry", "variant_geometry", "grade_geometry", "page_number")
                         if (field := record.get(key)))
        if not all(restore_measured_page_header(probe_section, probe_header, record, probe_style,
                    body_top_hwp=body_top, automatic_page_number=kind == "running", page_type=name,
                    header_top_hwp=header_top)
                   for name, record in header_peers):
            return None
        plans.append((start, end, body_top, printed[0], header_peers, kind, header_top))
    base_properties, base_columns = deepcopy(secpr), deepcopy(columns)
    sections = []
    for section_index, (start, end, body_top, printed, header_peers, kind, header_top) in enumerate(plans):
        current = section if section_index == 0 else etree.Element(section.tag, nsmap=section.nsmap)
        local = paragraphs[start:end]
        if section_index:
            for paragraph in local:
                current.append(paragraph)
            run = local[0].find(HP + "run")
            properties = deepcopy(base_properties)
            properties.set("id", str(section_index))
            run.insert(0, properties)
            run.insert(1, deepcopy(base_columns))
        properties = current.find(".//" + HP + "secPr")
        start_num = properties.find(HP + "startNum")
        if start_num is not None:
            start_num.set("page", str(printed))
            start_num.set("pageStartsOn", "BOTH")
        # PAGE auto fields use the native restart control. startNum is also
        # retained for editors, but some readers ignore that property alone.
        restart = etree.Element(HP + "ctrl")
        etree.SubElement(restart, HP + "newNum", num=str(printed), numType="PAGE")
        local[0].find(HP + "run").insert(2, restart)
        for name, record in header_peers:
            if not restore_measured_page_header(current, header, record, char_style,
                    body_top_hwp=body_top, automatic_page_number=kind == "running", page_type=name,
                    header_top_hwp=header_top):
                raise ValueError("source-proven native masthead restoration failed")
        apply_source_flow_spacing(current, local, [spacing[p] for p in local], header,
                                  repeating_header=True)
        local_groups = source_groups[start:end]
        _paginate(current, local, local_groups, header)
        sections.append(current)
    return sections
