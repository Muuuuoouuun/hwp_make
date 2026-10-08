"""Prove the renderer's cell Square branch leaves unsupported/native paths intact.

Both isolated wheels read exactly the same immutable HWPX for each case. Source
completeness, actual rules/image coordinates, and public editing are checked by
the separate verify_native_wrapped_prose_frame.py oracle.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
ROOT = Path(__file__).resolve().parents[1]


def worker(folder):
    import rhwp

    results = {}
    for path in sorted((folder.parent / "fixtures").glob("*.hwpx")):
        parsed = rhwp.parse(str(path))
        svg = parsed.render_svg(3)
        png = bytes(parsed.render_png(3))
        (folder / (path.stem + ".svg")).write_text(svg, encoding="utf-8")
        (folder / (path.stem + ".png")).write_bytes(png)
        results[path.stem] = {"pages": parsed.page_count, "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "svg_sha256": hashlib.sha256(svg.encode()).hexdigest(), "png_sha256": hashlib.sha256(png).hexdigest()}
        print("rendered", path.stem, flush=True)
    (folder / "report.json").write_text(json.dumps({"module": rhwp.__file__,
        "version": importlib.metadata.version("rhwp-python"), "cases": results}, indent=2), encoding="utf-8")


def fixtures(source, destination):
    with zipfile.ZipFile(source) as archive:
        parts = {item.filename: (item, archive.read(item.filename)) for item in archive.infolist()}
    for part, (_, payload) in parts.items():
        if not part.startswith("Contents/section") or not part.endswith(".xml"):
            continue
        original = etree.fromstring(payload)
        draws = [node for node in original.iter(HP + "drawText") if node.get("name") == "question:v1:q27"]
        if draws:
            break
    else:
        raise AssertionError("Q27 native drawText fixture is required")
    cases = ["positive", "tac", "no_flow", "top_bottom", "behind", "in_front", "page_h", "paper_h", "page_v",
             "paper_v", "negative_x", "negative_y", "no_cache", "zero_width", "huge_width", "invalid_baseline",
             "second_picture", "cell_center", "math_control"]
    for case in cases:
        root = deepcopy(original)
        draw = next(node for node in root.iter(HP + "drawText") if node.get("name") == "question:v1:q27")
        pictures = list(draw.iter(HP + "pic"))
        assert len(pictures) == 1, "fixture must own exactly one real native picture"
        picture = pictures[0]
        position = picture.find(HP + "pos")
        paragraph = picture.getparent().getparent()
        assert paragraph.tag == HP + "p" and position is not None
        if case == "tac": position.set("treatAsChar", "1")
        elif case == "no_flow": position.set("flowWithText", "0")
        elif case in ("top_bottom", "behind", "in_front"):
            picture.set("textWrap", {"top_bottom": "TOP_AND_BOTTOM", "behind": "BEHIND_TEXT", "in_front": "IN_FRONT_OF_TEXT"}[case])
        elif case in ("page_h", "paper_h"): position.set("horzRelTo", case.split("_")[0].upper())
        elif case in ("page_v", "paper_v"): position.set("vertRelTo", case.split("_")[0].upper())
        elif case == "negative_x": position.set("horzOffset", "-100")
        elif case == "negative_y": position.set("vertOffset", "-100")
        elif case == "no_cache": paragraph.remove(paragraph.find(HP + "linesegarray"))
        elif case in ("zero_width", "huge_width", "invalid_baseline"):
            line = paragraph.find(HP + "linesegarray/" + HP + "lineseg")
            key, value = {"zero_width": ("horzsize", "0"), "huge_width": ("horzsize", "9999999"),
                          "invalid_baseline": ("baseline", "9999999")}[case]
            line.set(key, value)
        elif case == "second_picture": picture.getparent().append(deepcopy(picture))
        elif case == "cell_center":
            cell = next(parent for parent in paragraph.iterancestors() if parent.tag == HP + "tc")
            cell.find(HP + "subList").set("vertAlign", "CENTER")
        elif case == "math_control":
            equation = etree.SubElement(picture.getparent(), HP + "equation", id="99", baseUnit="798", font="HancomEQN")
            etree.SubElement(equation, HP + "sz", width="1500", height="1500", widthRelTo="ABSOLUTE", heightRelTo="ABSOLUTE")
            etree.SubElement(equation, HP + "pos", treatAsChar="1", flowWithText="1", vertRelTo="PARA", horzRelTo="PARA", vertOffset="0", horzOffset="0")
            etree.SubElement(equation, HP + "script").text = "x^{2}+1"
        path = destination / (case + ".hwpx")
        with zipfile.ZipFile(path, "w") as archive:
            for name, (item, value) in parts.items():
                archive.writestr(item, etree.tostring(root) if name == part else value)
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hwpx", type=Path)
    parser.add_argument("--baseline-site", type=Path)
    parser.add_argument("--candidate-site", type=Path)
    parser.add_argument("--artifacts", type=Path, default=ROOT / "tmp/renderer-square/scope-verification")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    if args.worker:
        worker(args.artifacts)
        return 0
    if not any((args.hwpx, args.baseline_site, args.candidate_site)):
        print("SKIP: explicit HWPX and two isolated renderer sites are required")
        return 2
    if not all((args.hwpx, args.baseline_site, args.candidate_site)):
        parser.error("--hwpx, --baseline-site and --candidate-site are required")
    fixture_folder = args.artifacts / "fixtures"
    fixture_folder.mkdir(exist_ok=True)
    cases = fixtures(args.hwpx, fixture_folder)
    for label, site in (("baseline", args.baseline_site), ("candidate", args.candidate_site)):
        folder = args.artifacts / label
        folder.mkdir(exist_ok=True)
        env = dict(os.environ, PYTHONPATH=str(site.resolve()), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--artifacts", str(folder.resolve())],
                       cwd=ROOT, env=env, check=True)
    before, after = [json.loads((args.artifacts / label / "report.json").read_text(encoding="utf-8"))
                     for label in ("baseline", "candidate")]
    assert before["module"] != after["module"], "two isolated renderer sites are required"
    for case in cases:
        a, b = before["cases"][case], after["cases"][case]
        assert a["input_sha256"] == b["input_sha256"], "input changed during comparison"
        if case == "positive":
            assert a["pages"] == b["pages"] == 8 and a["svg_sha256"] != b["svg_sha256"]
        else:
            assert a == b, (case, "unsupported or existing route changed")
    result = {"ok": True, "baseline": before["version"], "candidate": after["version"],
              "unchanged_native_paths": len(cases) - 1, "negative_cases": cases[1:], "positive_changed_only_in_separate_oracle": True}
    (args.artifacts / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
