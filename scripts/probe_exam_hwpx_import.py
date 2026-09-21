"""Measure real HWPX imports in a fresh, isolated research database.

Endnote counts are evidence, not a universal question-count oracle. This probe
does not change the user's question bank or award a Hancom GUI compatibility pass.
All source material and the probe DB remain in the specified local output folder.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
import zipfile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def note_evidence(path):
    notes = []
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith("Contents/section") and name.endswith(".xml"):
                notes.extend(etree.fromstring(archive.read(name), parser).iter(HP + "endNote"))
    probes = []
    for note in notes:
        texts = [(node.text or "").strip() for node in note.iter(HP + "t")]
        longest = max(texts, key=len, default="")
        if len(longest) >= 20:
            probes.append(longest)
    return notes, probes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.output_dir.resolve() / f"{stamp}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    # This must precede every app import: storage reads the environment once.
    os.environ["HWP_MAKE_DATA_DIR"] = str(run_dir / "isolated_app_data")
    sys.path.insert(0, str(ROOT))
    from app import importers, storage

    storage.init_db()
    report = {
        "scope": "Actual import_hwpx function; isolated database; no GUI edits performed.",
        "source_code_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("app/importers.py", "app/storage.py")
        },
        "files": [], "errors": [],
    }
    for path in args.files:
        try:
            payload = path.read_bytes()
            notes, probes = note_evidence(path)
            started = time.perf_counter()
            result = importers.import_hwpx(path.name, payload, {"subject": "research"})
            ids = result.get("ordered_ids") or result.get("created", [])
            rows = [storage.get_problem(i if isinstance(i, int) else i["id"]) for i in ids]
            report["files"].append({
                "file": path.name, "source_sha256": hashlib.sha256(payload).hexdigest(),
                "source_endnotes": len(notes), "source_note_numbers": [n.get("number") for n in notes],
                "created": len(result.get("created", [])), "ordered": len(rows),
                "numbers": [r.get("number") for r in rows],
                "answers": sum(bool(r.get("answer")) for r in rows),
                "explanations": sum(bool(r.get("explanation")) for r in rows),
                "notes_with_long_text_probe": len(probes),
                "note_text_probes_found_in_stem": sum(any(p in r.get("stem", "") for r in rows) for p in probes),
                "seconds": round(time.perf_counter() - started, 3),
                "notices": result.get("notices", []),
            })
        except Exception as exc:
            report["errors"].append({"file": str(path), "error": str(exc)})
    target = run_dir / "report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"report": str(target), "files": len(report["files"]), "errors": report["errors"]}, ensure_ascii=False))
    return bool(report["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
