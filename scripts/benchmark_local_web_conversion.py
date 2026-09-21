"""Compare real desktop/web workers without writing to the user's application DB.

python scripts/benchmark_local_web_conversion.py --runs 2
Outputs and stage timings stay under data/local_web_benchmark/<timestamp>.
Transport/queue/browser delays are deliberately excluded from worker timings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def source_fingerprints():
    names = ("main.py", "desktop_convert.py", "web_convert.py", "pdf_layout_writer.py",
             "hwpx_writer_v2.py", "pdf_layout_fidelity.py", "importers.py", "pdf_editability.py",
             "pdf_native_content.py", "pdf_math_geometry.py", "hancom_pua_map.py", "recognition/pipeline.py")
    return {name: hashlib.sha256((ROOT / "app" / name).read_bytes()).hexdigest()
            for name in names if (ROOT / "app" / name).is_file()}


def child(spec_path):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    folder = spec_path.parent
    os.environ["HWP_MAKE_DATA_DIR"] = str(folder / "engine")
    os.environ["HWP_MAKE_SETTINGS_DIR"] = str(folder / "settings")
    for key in tuple(os.environ):
        if key.startswith(("OPENAI_", "GOOGLE_", "GEMINI_")):
            os.environ.pop(key, None)
    sources_before = source_fingerprints()
    dump(folder / "source_fingerprints_before.json", sources_before)
    started = time.perf_counter()
    from app import main
    from app.recognition import pipeline
    from app import pdf_editability

    timings = {"engine_import": time.perf_counter() - started}

    def instrument(module, name, key):
        original = getattr(module, name)

        def wrapped(*args, **kwargs):
            begin = time.perf_counter()
            try:
                result = original(*args, **kwargs)
                if key == "writer":
                    # Preserve the writer artifact even when the public API's
                    # subsequent independent content gate rejects delivery.
                    shutil.copyfile(Path(args[1]), folder / "writer_output.hwpx")
                    dump(folder / "writer_stats.json", result)
                if key == "pdf_api":
                    dump(folder / "engine_report.json", result)
                    from app import storage
                    renders = storage.EXPORT_DIR / result["run"]["folder"] / "fidelity_renders"
                    if renders.exists():
                        shutil.copytree(renders, folder / "fidelity_renders", dirs_exist_ok=True)
                return result
            except Exception as exc:
                if key == "pdf_api":
                    dump(folder / "api_error.json", {"type": type(exc).__name__,
                                                     "detail": getattr(exc, "detail", str(exc))})
                raise
            finally:
                timings[key] = timings.get(key, 0) + time.perf_counter() - begin
                dump(folder / "timings.json", timings)
        setattr(module, name, wrapped)

    for module, name, key in (
        (main, "export_pdf_layout", "pdf_api"),
        (main.pdf_layout_writer, "write_pdf_structured_hwpx", "writer"),
        (pdf_editability, "inspect_pdf_editability", "editability"),
        (pipeline, "recognize_pdf", "recognition_nested_in_writer"),
        (main, "_pdf_export_fidelity", "fidelity"),
        (main.pdf_layout_fidelity, "_render_hwpx_page", "hwpx_render_nested_in_fidelity"),
        (main.pdf_layout_writer, "inspect_layout_template_profile", "style_inspection"),
        (main, "_inspect_hwpx_open_safety", "open_safety"),
    ):
        instrument(module, name, key)
    if spec.get("experimental_fast_filter"):
        from scripts.probe_fidelity_filter_speed import Image, separable_filter
        Image.Image.filter = separable_filter
    try:
        if spec["route"] == "desktop":
            from app.desktop_convert import convert
            result = convert(Path(spec["source"]), folder / f"output.{spec['format']}", folder)
            dump(folder / "result.json", result)
        else:
            from app.web_convert import convert
            convert(folder)
    finally:
        timings["child_total"] = time.perf_counter() - started
        dump(folder / "timings.json", timings)
        sources_after = source_fingerprints()
        dump(folder / "source_fingerprints_after.json", sources_after)
        dump(folder / "source_stability.json", {"unchanged_during_conversion": sources_before == sources_after})


def package_parts(path):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        return {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}


def compare_document_parts(left_path, right_path):
    """Ignore only known generated object identities, keeping content/styles/geometry."""
    from lxml import etree
    from collections import Counter

    ignored = {("p", "id"), ("colPr", "id"), ("tbl", "id"), ("rect", "id"), ("rect", "instid"),
               ("pic", "id"), ("pic", "instid"), ("line", "id"), ("line", "instid")}
    changed_ids = Counter()
    differing = []
    with zipfile.ZipFile(left_path) as left, zipfile.ZipFile(right_path) as right:
        for name in sorted(set(left.namelist()) | set(right.namelist())):
            if name not in left.namelist() or name not in right.namelist():
                differing.append(name)
                continue
            a, b = left.read(name), right.read(name)
            if a == b:
                continue
            if name.startswith("Contents/section") and name.endswith(".xml"):
                first, second = etree.fromstring(a), etree.fromstring(b)
                for tree in (first, second):
                    for element in tree.iter():
                        tag = etree.QName(element).localname
                        for attr in tuple(element.attrib):
                            if (tag, attr) in ignored:
                                if tree is first:
                                    changed_ids[f"{tag}@{attr}"] += 1
                                element.set(attr, "GENERATED_OBJECT_ID")
                a, b = etree.tostring(first, method="c14n"), etree.tostring(second, method="c14n")
            if a != b:
                differing.append(name)
    return {"differing_parts_after_object_id_normalization": differing,
            "normalized_object_id_attributes_in_changed_parts": dict(changed_ids)}


def run(args):
    target = (args.output_dir or ROOT / "data/local_web_benchmark" / time.strftime("%Y%m%d_%H%M%S")).resolve()
    target.mkdir(parents=True, exist_ok=False)
    text = target / "questions.txt"
    text.write_text("7. 다음 계산의 결과는?\n2 + 3 = ?\n① 3\n② 4\n③ 5\n④ 6\n⑤ 7\n\n12. x와 X는 같은 변수인가?", encoding="utf-8")
    samples = ROOT / "data/full_subject_qa/sources"
    cases = [("math", samples / "2026-06-고1-수학-문제.pdf", "hwpx"),
             ("english", samples / "2026-06-고1-영어-문제.pdf", "hwpx"),
             ("history", samples / "2026-06-고1-한국사-문제.pdf", "hwpx"),
             ("txt_hwpx", text, "hwpx"), ("txt_docx", text, "docx")]
    if args.cases:
        cases = [case for case in cases if case[0] in args.cases]
    report = {"python": sys.version, "platform": platform.platform(),
              "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "scope": "fresh process, same PC, actual worker functions; excludes network, queue, UI polling; instrumented timings include report capture",
              "runs": [], "comparisons": []}
    print(f"REPORT_DIR={target}", flush=True)
    for index in range(args.runs):
        for name, source, fmt in cases:
            if not source.is_file():
                raise FileNotFoundError(source)
            outputs = {}
            for route in (("desktop", "web") if index % 2 == 0 else ("web", "desktop")):
                folder = target / f"{name}_{index + 1}_{route}"
                folder.mkdir()
                spec = {"source": str(source), "filename": source.name, "kind": "pdf" if source.suffix == ".pdf" else "text", "format": fmt, "route": route}
                dump(folder / "spec.json", spec)
                print(f"START {name} run={index + 1} {route}", flush=True)
                started = time.perf_counter()
                with (folder / "worker.log").open("w", encoding="utf-8") as log:
                    process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", str(folder / "spec.json")], cwd=ROOT, stdout=log, stderr=log, timeout=1200,
                                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                seconds = time.perf_counter() - started
                row = {"case": name, "run": index + 1, "route": route, "seconds": round(seconds, 4), "exit_code": process.returncode,
                       "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "source_bytes": source.stat().st_size, "folder": str(folder)}
                if (folder / "timings.json").exists():
                    row["timings"] = json.loads((folder / "timings.json").read_text(encoding="utf-8"))
                if process.returncode == 0:
                    outputs[route] = folder / f"output.{fmt}"
                    row["output_bytes"] = outputs[route].stat().st_size
                    row["package_valid"] = bool(package_parts(outputs[route]))
                report["runs"].append(row)
                dump(target / "results.json", report)
                print(f"DONE {name} {route} {seconds:.3f}s exit={process.returncode} stages={row.get('timings')}", flush=True)
            if len(outputs) == 2:
                left, right = package_parts(outputs["desktop"]), package_parts(outputs["web"])
                different = [key for key in sorted(left.keys() | right.keys()) if left.get(key) != right.get(key)]
                report["comparisons"].append({"case": name, "run": index + 1, "parts": len(left), "differing_parts": different,
                                              **compare_document_parts(outputs["desktop"], outputs["web"])})
            dump(target / "results.json", report)
    report["medians"] = {name: {route: statistics.median(row["seconds"] for row in report["runs"] if row["case"] == name and row["route"] == route) for route in ("desktop", "web")} for name, *_ in cases}
    dump(target / "results.json", report)
    print(json.dumps({"medians": report["medians"], "comparisons": report["comparisons"]}, ensure_ascii=False, indent=2), flush=True)
    return int(any(row["exit_code"] for row in report["runs"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", type=Path)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    known_cases = {"math", "english", "history", "txt_hwpx", "txt_docx"}
    if args.cases and not set(args.cases) <= known_cases:
        parser.error("--cases contains an unknown sample")
    if args.child:
        child(args.child)
    else:
        raise SystemExit(run(args))
