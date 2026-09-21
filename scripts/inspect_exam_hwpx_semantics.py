"""Read-only note identity, numbering and object-placement inventory.

Only structure and style metadata are emitted; question/answer text is omitted.
Source control IDs and display numbers must not be assumed globally unique.
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
import sys
import zipfile

from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def profiles(values):
    counts = Counter(json.dumps(v, sort_keys=True) for v in values)
    return [{"profile": json.loads(k), "count": v} for k, v in sorted(counts.items())]


def inspect(path):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    payload = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = sorted(
            (n for n in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)),
            key=lambda n: int(re.search(r"section(\d+)", n).group(1)),
        )
        if not names:
            raise ValueError("No section XML")
        head = etree.fromstring(archive.read("Contents/header.xml"), parser)
        roots = [etree.fromstring(archive.read(n), parser) for n in names]
    char_prs = {n.get("id"): n for n in head.iter(HH + "charPr")}
    para_prs = {n.get("id"): n for n in head.iter(HH + "paraPr")}
    notes = [n for r in roots for n in r.iter(HP + "endNote")]
    ids = Counter(n.get("instId", "<missing>") for n in notes)
    numbers = Counter(n.get("number", "<missing>") for n in notes)
    anchors = []
    for note in notes:
        host = next(note.iterancestors(HP + "run"), None)
        style = char_prs.get(host.get("charPrIDRef")) if host is not None else None
        anchors.append({
            "char_height_raw": style.get("height") if style is not None else None,
            "text_color": style.get("textColor") if style is not None else None,
            "ancestry": [etree.QName(a).localname for a in note.iterancestors()],
        })
    headings = Counter()
    for root in roots:
        for para in root.findall(HP + "p"):
            style = para_prs.get(para.get("paraPrIDRef"))
            heading = style.find(HH + "heading") if style is not None else None
            headings[heading.get("type", "<missing>") if heading is not None else "<missing>"] += 1
    assets = {}
    for key, tag in (("equations", "equation"), ("tables", "tbl"), ("pictures", "pic")):
        total = sum(len(list(r.iter(HP + tag))) for r in roots)
        inside_notes = sum(len(list(n.iter(HP + tag))) for n in notes)
        assets[key] = {"whole_section_tree": total, "inside_endnotes": inside_notes,
                       "outside_endnotes": total - inside_notes}
    tables = []
    for root in roots:
        for table in root.iter(HP + "tbl"):
            pos = table.find(HP + "pos")
            tables.append({
                "page_break": table.get("pageBreak"),
                "treat_as_char": pos.get("treatAsChar") if pos is not None else None,
                "in_endnote": any(True for _ in table.iterancestors(HP + "endNote")),
            })
    return {
        "file": path.name, "sha256": hashlib.sha256(payload).hexdigest(),
        "endnotes": len(notes),
        "unique_present_inst_ids": len({n.get("instId") for n in notes if n.get("instId")}),
        "duplicate_inst_ids": {k: v for k, v in ids.items() if v > 1},
        "duplicate_display_numbers": {k: v for k, v in numbers.items() if v > 1},
        "note_number_ranges_by_section": [
            {"member": name, "count": len(list(root.iter(HP + "endNote"))),
             "numbers": [n.get("number") for n in root.iter(HP + "endNote")]}
            for name, root in zip(names, roots)
        ],
        "note_anchor_profiles": profiles(anchors),
        "anchor_profile_scope": "Host run's stored charPr only; not a rendered visibility judgment.",
        "top_level_paragraph_heading_types": dict(headings),
        "numbering_definitions": len(list(head.iter(HH + "numbering"))),
        "asset_ownership_counts": assets,
        "table_pagination_profiles": profiles(tables),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"measured_at": datetime.now(timezone.utc).isoformat(),
              "scope": "Stored semantics only; not Hancom GUI execution or import quality certification.",
              "files": [], "errors": []}
    for path in args.files:
        try:
            report["files"].append(inspect(path))
        except Exception as exc:
            report["errors"].append({"file": str(path), "error": str(exc)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"files": len(report["files"]), "errors": report["errors"],
                      "output": str(args.output)}, ensure_ascii=False))
    return bool(report["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
