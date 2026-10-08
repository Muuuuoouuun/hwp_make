"""Compare an isolated renderer wheel with the installed baseline, without installing it.

Run with --candidate-site <pip --target directory> --artifacts <scratch directory>.
Real loaded-face/ambiguity unit tests are additionally recorded in the build report.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import shutil

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "regular": ("Arial", False, False, "Regular Arial preserves its real face."),
    "bold": ("Arial", True, False, "Explicit bold Arial preserves its real face."),
    "italic": ("Arial", False, True, "Italic Arial preserves its real face."),
    "unknown": ("Unknown Black", False, False, "Unknown family retains the previous fallback."),
    "suffix": ("Arial Black Italic", False, False, "A suffix cannot select a similar face."),
    "slant": ("Arial Black", False, True, "An unavailable italic face retains fallback."),
    "blackadder": ("Blackadder ITC", False, False, "Black names cannot imply a heavy weight."),
    "cjk": ("Arial Black", False, False, "한글 글리프 대체는 그대로 유지됩니다"),
    "mixed": ("Arial Black", False, False, "Real face 한글 대체 keeps its own glyphs."),
    "heavy": ("Arial Black", False, False, "Real heavy face preserves its intrinsic weight."),
    "postscript": ("Arial-Black", False, False, "Real heavy face preserves its intrinsic weight."),
}


def worker(folder: Path):
    os.environ["HWP_MAKE_DATA_DIR"] = str(folder / "engine")
    sys.path.insert(0, str(ROOT))
    import fitz
    import rhwp
    from lxml import etree
    from app.hwpx_writer_v2 import HwpxDocument

    folder.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, (family, bold, italic, text) in CASES.items():
        path = folder / (name + ".hwpx")
        if path.exists():
            parsed = rhwp.parse(str(path))
        else:
            create_fixture(HwpxDocument, etree, family, bold, italic, text, path)
            parsed = rhwp.parse(str(path))
        svg = parsed.render_svg(0)
        assert family in svg, (name, "fixture did not request the intended font family")
        png = bytes(parsed.render_png(0))
        pdf = bytes(parsed.render_pdf())
        (folder / (name + ".svg")).write_text(svg, encoding="utf-8")
        (folder / (name + ".png")).write_bytes(png)
        (folder / (name + ".pdf")).write_bytes(pdf)
        with fitz.open(stream=pdf, filetype="pdf") as output:
            painted = [(trace["font"], [(char[0], char[2], char[3]) for char in trace["chars"]])
                       for page in output for trace in page.get_texttrace()]
        results[name] = {"svg": svg, "png_sha256": hashlib.sha256(png).hexdigest(),
                         "painted": painted, "pages": parsed.page_count}
        print("rendered", name, flush=True)
    result = {"version": importlib.metadata.version("rhwp-python"), "module": rhwp.__file__, "cases": results}
    (folder / "render-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def create_fixture(HwpxDocument, etree, family, bold, italic, text, path):
    document = HwpxDocument.new()
    style = document.ensure_run_style(font=family, size=26, bold=bold, italic=italic)
    paragraph = document.add_paragraph("")
    paragraph.add_run(text, char_pr_id_ref=style)
    document.package.set_part("Preview/PrvText.txt", text.encode("utf-8"))
    document.save_to_path(path)
    # The bare HWPX template only registers its two Korean faces. Register
    # the requested face explicitly rather than testing its default font.
    with zipfile.ZipFile(path) as package:
        payloads = {item.filename: (item, package.read(item.filename)) for item in package.infolist()}
    header = etree.fromstring(payloads["Contents/header.xml"][1])
    for font in header.iter("{http://www.hancom.co.kr/hwpml/2011/head}font"):
        font.set("face", family)
    with zipfile.ZipFile(path, "w") as package:
        for part, (item, payload) in payloads.items():
            package.writestr(item, etree.tostring(header) if part == "Contents/header.xml" else payload)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-site", type=Path, help="isolated previous wheel; default: installed renderer")
    parser.add_argument("--candidate-site", type=Path)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    if args.worker:
        worker(args.artifacts)
        return 0
    if not args.candidate_site:
        parser.error("--candidate-site is required")
    for label in ("baseline", "candidate"):
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        env.pop("PYTHONPATH", None)
        if label == "baseline" and args.baseline_site:
            env["PYTHONPATH"] = str(args.baseline_site.resolve())
        if label == "candidate":
            env["PYTHONPATH"] = str(args.candidate_site.resolve())
            (args.artifacts / label).mkdir(exist_ok=True)
            for name in CASES:
                shutil.copyfile(args.artifacts / "baseline" / (name + ".hwpx"), args.artifacts / label / (name + ".hwpx"))
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--artifacts",
                        str((args.artifacts / label).resolve())], cwd=ROOT, env=env, check=True)
    before, after = [json.loads((args.artifacts / label / "render-report.json").read_text(encoding="utf-8"))
                     for label in ("baseline", "candidate")]
    assert before["module"] != after["module"], "candidate must be isolated from the installed baseline"
    checks = []
    for name in CASES:
        a, b = before["cases"][name], after["cases"][name]
        assert a["svg"] == b["svg"] and a["pages"] == b["pages"], (name, "layout changed")
        checks.append(name + ": unchanged SVG/page geometry")
        if name == "mixed":
            old_cjk = [(font, char) for font, chars in a["painted"] for char in chars if char[0] >= 0xAC00]
            new_cjk = [(font, char) for font, chars in b["painted"] for char in chars if char[0] >= 0xAC00]
            assert old_cjk and old_cjk == new_cjk, "mixed CJK changed its original font or glyph bounds"
            assert any("Arial-Black" in trace[0] for trace in b["painted"])
            checks.append(name + ": recovered Latin and unchanged CJK font/glyph/bounds")
        elif name not in ("heavy", "postscript"):
            assert a["png_sha256"] == b["png_sha256"] and a["painted"] == b["painted"], (name, "fallback changed")
            checks.append(name + ": unchanged PNG pixels and PDF glyph/font/bounds")
        else:
            assert a["png_sha256"] != b["png_sha256"], (name, "PNG did not recover the actual heavy face")
            assert all("Arial-Black" in trace[0] for trace in b["painted"]), (name, b["painted"])
            assert a["painted"] != b["painted"], (name, "PDF still uses fallback")
            checks.append(name + ": actual heavy PNG change and PDF Arial-Black glyphs")
    report = {"ok": True, "baseline_version": before["version"], "candidate_version": after["version"], "checks": checks}
    (args.artifacts / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
