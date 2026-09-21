"""Read-only HWP/HWPX structural inventory, without copying exam text.

Counts include headers, tables and notes; they are not question counts or a
rendering/editability score. HWP fields follow Hancom's HWP 5.0 revision 1.2.
Usage: python scripts/inspect_exam_hwp_structure.py FILE... --output report.json
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import zipfile
import zlib

import olefile
from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
PAGE_FIELDS = ("width", "height", "left", "right", "top", "bottom", "header", "footer", "gutter")


def mm(value):
    return round(int(value) * 25.4 / 7200, 3)


def records(raw):
    pos = 0
    while pos < len(raw):
        if pos + 4 > len(raw):
            raise ValueError("Truncated HWP record header")
        header = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        size = header >> 20
        if size == 0xFFF:
            if pos + 4 > len(raw):
                raise ValueError("Truncated HWP extended record size")
            size = struct.unpack_from("<I", raw, pos)[0]
            pos += 4
        if pos + size > len(raw):
            raise ValueError("Truncated HWP record payload")
        yield header & 0x3FF, (header >> 10) & 0x3FF, raw[pos:pos + size]
        pos += size


def unique(items):
    return [json.loads(s) for s in sorted({json.dumps(x, sort_keys=True) for x in items})]


def inspect_hwp(payload):
    with olefile.OleFileIO(io.BytesIO(payload)) as ole:
        header = ole.openstream("FileHeader").read()
        if not header.startswith(b"HWP Document File") or len(header) < 40:
            raise ValueError("Invalid HWP FileHeader")
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & 6:
            raise ValueError("Encrypted/distribution HWP is outside this inventory's scope")

        def stream(name):
            raw = ole.openstream(name).read()
            return zlib.decompress(raw, -15) if flags & 1 else raw

        section_names = sorted(
            [x for x in ole.listdir() if len(x) == 2 and x[0] == "BodyText" and re.fullmatch(r"Section\d+", x[1])],
            key=lambda x: int(x[1][7:]),
        )
        if not section_names:
            raise ValueError("No HWP BodyText sections")
        tags, controls, breaks = Counter(), Counter(), Counter()
        pages, columns = [], []
        body_paragraphs = 0
        for section in section_names:
            for tag, level, data in records(stream(section)):
                tags[tag] += 1
                if tag == 66:
                    body_paragraphs += level == 0
                    if len(data) >= 12:
                        for bit, name in ((1, "section"), (2, "column_definition"), (4, "page"), (8, "column")):
                            breaks[name] += bool(data[11] & bit)
                elif tag == 71:
                    if len(data) < 4:
                        raise ValueError("Truncated HWP control ID")
                    ctrl = data[:4][::-1].decode("ascii", errors="replace")
                    controls[ctrl] += 1
                    if ctrl == "cold" and len(data) >= 8:
                        attrs, gap = struct.unpack_from("<Hh", data, 4)
                        columns.append({"count": (attrs >> 2) & 255, "type_code": attrs & 3,
                                        "same_width": bool(attrs & 4096), "gap_mm": mm(gap)})
                elif tag == 73 and len(data) >= 40:
                    page = {k + "_mm": mm(v) for k, v in zip(PAGE_FIELDS, struct.unpack_from("<9I", data))}
                    page["landscape"] = bool(struct.unpack_from("<I", data, 36)[0] & 1)
                    pages.append(page)
        fonts = set()
        info_tags = Counter()
        for tag, _, data in records(stream("DocInfo")):
            info_tags[tag] += 1
            if tag == 19 and len(data) >= 3:
                length = struct.unpack_from("<H", data, 1)[0]
                if 3 + length * 2 > len(data):
                    raise ValueError("Truncated HWP face name")
                fonts.add(data[3:3 + length * 2].decode("utf-16le"))
        return {
            "format": "HWP5", "version": ".".join(map(str, header[32:36][::-1])),
            "sections": len(section_names), "page_definitions": unique(pages),
            "column_definitions": unique(columns), "paragraphs_total": tags[66],
            "body_paragraphs": body_paragraphs, "equations": tags[88], "tables": tags[77],
            "pictures": tags[85], "rectangle_records": tags[79],
            "text_boxes": None, "text_boxes_note": "Rectangle records are not equivalent to text boxes.",
            "endnotes": controls["en  "], "footnotes": controls["fn  "],
            "headers": controls["head"], "footers": controls["foot"],
            "automatic_number_controls": controls["atno"], "explicit_breaks": dict(breaks),
            "font_faces_defined": sorted(fonts), "styles_defined": info_tags[26],
            "controls": dict(controls), "body_record_counts": dict(tags),
        }


def inspect_hwpx(payload):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = sorted([n for n in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)],
                       key=lambda n: int(re.search(r"section(\d+)", n).group(1)))
        if not names:
            raise ValueError("No HWPX section XML")
        roots = [etree.fromstring(archive.read(n), parser) for n in names]
        head = etree.fromstring(archive.read("Contents/header.xml"), parser)
    counts = Counter()
    pages, columns, anchors, box_sizes = [], [], [], []
    breaks = Counter()
    body_paragraphs = 0
    for root in roots:
        body_paragraphs += len(root.findall(HP + "p"))
        for node in root.iter():
            if not isinstance(node.tag, str) or not node.tag.startswith(HP):
                continue
            name = etree.QName(node).localname
            counts[name] += 1
            if name == "pagePr":
                page = {k + "_mm": mm(node.get(k)) for k in ("width", "height")}
                margin = node.find(HP + "margin")
                if margin is not None:
                    page.update({k + "_mm": mm(v) for k, v in margin.attrib.items()})
                page["landscape_raw"] = node.get("landscape")
                pages.append(page)
            elif name == "colPr":
                columns.append({"count": int(node.get("colCount", "1")), "type": node.get("type"),
                                "same_width": node.get("sameSz"), "gap_mm": mm(node.get("sameGap", "0"))})
            elif name == "pos":
                anchors.append({k: node.get(k) for k in ("treatAsChar", "flowWithText", "allowOverlap", "vertRelTo", "horzRelTo")})
            elif name == "rect" and node.find(HP + "drawText") is not None:
                size = node.find(HP + "sz")
                box_sizes.append(dict(size.attrib) if size is not None else {})
            elif name == "p":
                for key in ("pageBreak", "columnBreak"):
                    breaks[key] += node.get(key) == "1"
    return {
        "format": "HWPX", "sections": len(roots), "page_definitions": unique(pages),
        "column_definitions": unique(columns), "paragraphs_total": counts["p"],
        "body_paragraphs": body_paragraphs, "equations": counts["equation"],
        "tables": counts["tbl"], "pictures": counts["pic"], "rectangle_records": counts["rect"],
        "text_boxes": counts["drawText"], "endnotes": counts["endNote"], "footnotes": counts["footNote"],
        "headers": counts["header"], "footers": counts["footer"],
        "automatic_number_controls": counts["autoNum"], "explicit_breaks": dict(breaks),
        "font_faces_defined": sorted({n.get("face") for n in head.iter(HH + "font") if n.get("face")}),
        "styles_defined": len(list(head.iter(HH + "style"))),
        "object_anchor_variants": unique(anchors),
        "text_box_protect_flags": dict(Counter(x.get("protect", "unspecified") for x in box_sizes)),
        "text_box_height_range_mm": [mm(min(int(x["height"]) for x in box_sizes)), mm(max(int(x["height"]) for x in box_sizes))] if box_sizes and all("height" in x for x in box_sizes) else None,
    }


def inspect(path):
    payload = path.read_bytes()
    result = {"file": path.name, "path": str(path.resolve()), "bytes": len(payload),
              "sha256": hashlib.sha256(payload).hexdigest()}
    if payload.startswith(b"PK"):
        result.update(inspect_hwpx(payload))
    elif olefile.isOleFile(io.BytesIO(payload)):
        result.update(inspect_hwp(payload))
    else:
        raise ValueError("Unsupported file signature")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"measured_at": datetime.now(timezone.utc).isoformat(),
              "scope": "Structural inventory only; no Hancom GUI or visual-quality pass is implied.",
              "count_scope": "Entire section trees including notes, headers and nested tables.",
              "files": [], "errors": []}
    for path in args.files:
        try:
            report["files"].append(inspect(path))
        except Exception as exc:
            report["errors"].append({"path": str(path), "error": str(exc)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"files": len(report["files"]), "errors": report["errors"], "output": str(args.output)}, ensure_ascii=False))
    return bool(report["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
