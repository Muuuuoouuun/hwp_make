"""Source-derived oracle for a picture crossing an editable prose paragraph.

This checks actual source rules, glyphs, pixels and render coordinates. It does
not prescribe a table topology or accept producer flags as proof of wrapping.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import sys
import zipfile

import fitz
from lxml import etree

import verify_native_illustrated_prose_frame_flow as shared

HP, HC = shared.HP, shared.HC
ROOT = Path(__file__).resolve().parents[1]


def verification_snapshot(source, native):
    """Tie a result to immutable input, verifier and loaded renderer bytes."""
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    paths = set((ROOT / "app").rglob("*.py"))
    paths.update((Path(__file__).resolve(), Path(shared.__file__).resolve()))
    code = {str(path.relative_to(ROOT)).replace("\\", "/"): digest(path)
            for path in sorted(paths) if path.is_file()}
    renderer_root = Path(shared.rhwp.__file__).resolve().parent
    runtime = {str(path.relative_to(renderer_root)).replace("\\", "/"): digest(path)
               for path in sorted(renderer_root.rglob("*"))
               if path.is_file() and path.suffix.lower() in (".py", ".pyd", ".so", ".dll")}
    try:
        version = metadata.version("rhwp-python")
    except metadata.PackageNotFoundError:
        version = None
    aggregate = lambda values: hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    return {"source_sha256": digest(source), "input_sha256": digest(native),
            "code_sha256": aggregate(code), "code_files": code,
            "renderer_module": str(renderer_root), "renderer_version": version,
            "renderer_sha256": aggregate(runtime), "renderer_files": runtime}


def snapshot_summary(snapshot):
    return {key: value for key, value in snapshot.items()
            if key not in ("code_files", "renderer_files")}


def source_oracle(path, page_number, question):
    with fitz.open(path) as pdf:
        page = pdf[page_number]
        rows = []
        raw = page.get_text("rawdict")
        for block in raw["blocks"]:
            for line in block.get("lines", []):
                chars = [char for span in line["spans"] for char in span["chars"]]
                rows.append({"text": "".join(char["c"] for char in chars),
                             "bbox": list(line["bbox"]), "chars": chars,
                             "baseline": line["spans"][0]["origin"][1]})
        prompts = [row for row in rows if re.match(rf"^{question}\.\s", row["text"])]
        shared.check(len(prompts) == 1, "printed source question number independently identifies one prompt")
        prompt = prompts[0]
        next_prompt = [row for row in rows if re.match(rf"^{question + 1}\.\s", row["text"])
                       and abs(row["bbox"][0] - prompt["bbox"][0]) < 15
                       and row["bbox"][1] > prompt["bbox"][3]]
        shared.check(len(next_prompt) == 1, "one independently printed next question follows the frame")
        rules = shared.source_rules(page)
        horizontal = [(min(a, c), b, max(a, c)) for a, b, c, d in rules
                      if abs(b-d) < .01 and abs(c-a) > page.rect.width / 4]
        vertical = [(a, min(b, d), max(b, d)) for a, b, c, d in rules if abs(a-c) < .01]
        pictures = [block for block in page.get_text("dict")["blocks"] if block.get("type") == 1]
        frames = []
        for left, top, right in horizontal:
            if not prompt["bbox"][3] < top < next_prompt[0]["bbox"][1]:
                continue
            for other_left, bottom, other_right in horizontal:
                if not top < bottom < next_prompt[0]["bbox"][1] or max(abs(left-other_left), abs(right-other_right)) > .3:
                    continue
                if not all(any(abs(x-edge) < .3 and start <= top+.1 and stop >= bottom-.1
                               for x, start, stop in vertical) for edge in (left, right)):
                    continue
                frame = fitz.Rect(left, top, right, bottom)
                selected = sorted([row for row in rows if frame.contains(fitz.Rect(row["bbox"]))],
                                  key=lambda row: (row["baseline"], row["bbox"][0]))
                images = [image for image in pictures if frame.contains(fitz.Rect(image["bbox"]))]
                if selected and len(images) == 1:
                    frames.append((frame, selected, images[0]))
        shared.check(len(frames) == 1, "four actual source rules enclose one prose frame and one source picture")
        frame, selected, image = frames[0]
        image_box = fitz.Rect(image["bbox"])
        crossing = [index for index, row in enumerate(selected)
                    if row["bbox"][1] < image_box.y0 < row["bbox"][3]]
        shared.check(len(crossing) == 1 and crossing[0] > 1,
                     "source picture starts inside a prose line's vertical interval")
        shared.check(all((fitz.Rect(char["bbox"]) & image_box).get_area() < .1
                         for row in selected for char in row["chars"] if not char["c"].isspace()),
                     "every actual source prose glyph avoids the crossing picture")
        # The introductory paragraph is independently bounded by title, first
        # line indent and the heading after the crossing line. Printed rows
        # themselves are never made into separate native paragraphs here.
        intro = selected[1:crossing[0] + 1]
        shared.check(len(intro) > 1 and intro[0]["bbox"][0] > intro[1]["bbox"][0] + 1,
                     "source introductory paragraph has a first-line indent and several complete rows")
        payload = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=image_box, alpha=False).tobytes("png")
        return {"source": str(path), "page": page_number, "question": question,
                "page_width": page.rect.width, "page_height": page.rect.height,
                "frame": list(frame), "rows": selected, "image_bbox": list(image_box),
                "image_pixels": shared.pixels(payload), "title": selected[0],
                "intro": " ".join(row["text"].strip() for row in intro),
                "intro_raw": "".join(row["text"] for row in intro),
                "text": "".join(row["text"] for row in selected),
                "prompt": prompt, "next_prompt": next_prompt[0]}


def package(path, question):
    with zipfile.ZipFile(path) as archive:
        data = {name: archive.read(name) for name in archive.namelist()}
    roots = {name: etree.fromstring(payload) for name, payload in data.items()
             if re.fullmatch(r"Contents/section\d+\.xml", name)}
    found = [(root, draw) for root in roots.values() for draw in root.iter(HP + "drawText")
             if draw.get("name") == f"question:v1:q{question}"]
    if len(found) != 1:
        raise AssertionError("expected one actual native question owner")
    return data, roots, *found[0]


def unique_in_frame(values, text, complete):
    selected = shared.locate(values, complete)
    sequence, target = "".join(value[0] for value in selected), shared.compact(text)
    if sequence.count(target) != 1:
        raise AssertionError("expected unique complete row within native frame inventory")
    start = sequence.index(target)
    return selected[start:start + len(target)]


def native_issues(oracle, draw):
    issues = []
    if shared.compact(oracle["text"]) not in shared.compact("".join(t.text or "" for t in draw.iter(HP + "t"))):
        issues.append("source_prose_inventory")
    paragraphs = [p for p in draw.iter(HP + "p")
                  if shared.compact(shared.direct_text(p)) == shared.compact(oracle["intro"])]
    if len(paragraphs) != 1:
        issues.append("intro_not_one_semantic_paragraph")
    pictures = list(draw.iter(HP + "pic"))
    if len(pictures) != 1:
        issues.append("source_picture_owner_count")
    for picture in pictures:
        pos = picture.find(HP + "pos")
        if pos is None or pos.get("flowWithText") != "1":
            issues.append("picture_does_not_follow_text")
        if pos is not None and pos.get("treatAsChar") != "1" and (
            pos.get("vertRelTo") in ("PAGE", "PAPER") or pos.get("horzRelTo") in ("PAGE", "PAPER")
        ):
            issues.append("page_anchored_picture")
        if picture.get("textWrap") in ("IN_FRONT_OF_TEXT", "BEHIND_TEXT") or (pos is not None and pos.get("allowOverlap") == "1"):
            issues.append("overlapping_picture_anchor")
    return issues


def glyph_report(path, expected, pictures, root):
    """Measure actual PDF glyph ink, separately from SVG/XML text coverage."""
    parsed = shared.rhwp.parse(str(path))
    with fitz.open(stream=bytes(parsed.render_pdf()), filetype="pdf") as pdf:
        records = []
        sequence = ""
        for index, page in enumerate(pdf):
            for trace in page.get_texttrace():
                for char in trace["chars"]:
                    value = shared.compact(chr(char[0])).replace("\xad", "")
                    sequence += value
                    records.extend((index, char) for _ in value)
        target = shared.compact(expected.replace("\xad", ""))
        if sequence.count(target) != 1:
            return {"ok": False, "failure": "actual_pdf_glyph_inventory", "count": sequence.count(target)}
        start = sequence.index(target)
        selected = records[start:start + len(target)]
        page_pr = root.find(".//" + HP + "pagePr")
        margin = page_pr.find(HP + "margin")
        bounds = fitz.Rect(float(margin.get("left")) / 100,
                           (float(margin.get("top")) + float(margin.get("header", "0"))) / 100,
                           (float(page_pr.get("width")) - float(margin.get("right"))) / 100,
                           (float(page_pr.get("height")) - float(margin.get("bottom"))) / 100)
        outside, overlaps = [], []
        for index, char in selected:
            box = fitz.Rect(char[3])
            if not fitz.Rect(bounds.x0-.3, bounds.y0-.3, bounds.x1+.3, bounds.y1+.3).contains(box):
                outside.append({"char": chr(char[0]), "page": index, "bbox": list(box)})
            for _, image_page, image_box in pictures:
                if index == image_page and (box & fitz.Rect(*(value * .75 for value in image_box))).get_area() > .1:
                    overlaps.append({"char": chr(char[0]), "page": index, "bbox": list(box)})
        # U+00AD is already a separately known PDF-backend paint defect. Do not
        # count XML/SVG presence or exclusion from this inventory as a fix.
        return {"ok": not (outside or overlaps), "actual_glyphs": len(selected),
                "actual_bullet_glyphs": sum(shared.compact(chr(char[0])) == shared.compact('•')
                                           for _, char in selected),
                "outside_printable": outside, "picture_overlaps": overlaps,
                "source_soft_hyphens_requiring_separate_paint_proof": expected.count("\xad")}


def edit_flow(oracle, path, folder, initial_values, initial_images, initial_pages):
    """Public run append, deletion, fresh reopen and actual glyph/flow checks."""
    expected = oracle["text"]
    before_start = shared.locate(initial_values, expected)[0]
    before_next = shared.locate(initial_values, oracle["next_prompt"]["text"])[0]
    _, _, initial_root, initial_draw = package(path, oracle["question"])
    original_height = float(initial_draw.getparent().find(HP + "sz").get("height"))
    original_text = "".join(t.text or "" for t in initial_draw.iter(HP + "t"))
    page_height = float(initial_root.find(".//" + HP + "pagePr").get("height")) / 75
    position = lambda value: value[1] * page_height + value[3]
    before_distance = position(before_next) - position(before_start)
    addition = " Volunteer teams will receive additional instructions before planting seedlings." * 4
    outcomes = []
    previous = path
    grown_height, grown_distance = None, None
    for stage in ("intro-grown", "intro-deleted"):
        document = shared.HwpxDocument.open(previous)
        section, draw = next((section, draw) for section in document.sections
                             for draw in section.element.iter(HP + "drawText")
                             if draw.get("name") == f"question:v1:q{oracle['question']}")
        target_text = oracle["intro"] if stage == "intro-grown" else oracle["intro"] + addition
        paragraph = next(p for p in draw.iter(HP + "p")
                         if shared.compact(shared.direct_text(p)) == shared.compact(target_text))
        public = shared.HwpxOxmlParagraph(paragraph, section)
        original_count = sum(1 for _ in draw.iter(HP + "p"))
        if stage == "intro-grown":
            last = next(run for run in reversed(public.runs) if run.text)
            public.add_run(addition, char_pr_id_ref=last.element.get("charPrIDRef"))
            expected = oracle["text"].replace(oracle["intro_raw"], oracle["intro_raw"] + addition, 1)
        else:
            last = next(run for run in reversed(public.runs) if run.text)
            if last.text != addition:
                raise AssertionError("public appended run did not remain independently editable")
            last.text = ""
            expected = oracle["text"]
        shared.check(paragraph.find(HP + "linesegarray") is None, "public edit invalidates the source paragraph cache")
        target = folder / f"{stage}.hwpx"
        document.save_to_path(target)
        data, roots, root, updated = package(target, oracle["question"])
        changed = {**oracle, "text": expected,
                   "intro": oracle["intro"] + addition if stage == "intro-grown" else oracle["intro"]}
        issues = native_issues(changed, updated)
        if sum(1 for _ in updated.iter(HP + "p")) != original_count:
            issues.append("semantic_paragraph_count_changed")
        parsed, values, images, _ = shared.painted(target)
        frame_start = shared.locate(values, expected)[0]
        following = shared.locate(values, oracle["next_prompt"]["text"])[0]
        pictures = [image for image in images if image[0] == oracle["image_pixels"]]
        if len(pictures) != 1:
            issues.append("source_picture_pixel_inventory")
        height = float(updated.getparent().find(HP + "sz").get("height"))
        distance = position(following) - position(frame_start)
        if stage == "intro-grown":
            if height <= original_height or distance <= before_distance + .5:
                issues.append("growing_intro_does_not_move_following_question")
            grown_height, grown_distance = height, distance
        else:
            if height >= grown_height or distance >= grown_distance - .5:
                issues.append("deleting_intro_does_not_shrink_native_flow")
            if parsed.page_count != initial_pages:
                issues.append("deleting_intro_does_not_restore_initial_page_count")
            if height != original_height or abs(distance - before_distance) > .15:
                issues.append("deleting_intro_does_not_restore_initial_native_flow")
            if (following[1] != before_next[1]
                or max(abs(following[index] - before_next[index]) for index in (2, 3)) > .15):
                issues.append("deleting_intro_does_not_restore_following_question_position")
            if "".join(t.text or "" for t in updated.iter(HP + "t")) != original_text:
                issues.append("deleting_intro_does_not_restore_exact_original_text")
            if (len(pictures) != len(initial_images)
                or any(current[0:2] != original[0:2]
                       or max(abs(a-b) for a, b in zip(current[2], original[2])) > .15
                       for current, original in zip(pictures, initial_images))):
                issues.append("deleting_intro_does_not_restore_original_picture_position")
        glyphs = glyph_report(target, expected, pictures, root)
        if not glyphs["ok"]:
            issues.append("edited_actual_pdf_glyph_bounds")
        validation = shared.validate_package(target)
        if not validation.ok or validation.warnings:
            issues.append("edited_native_package_invalid")
        reopened = folder / f"{stage}-reopened.hwpx"
        shared.HwpxDocument.open(target).save_to_path(reopened)
        again = package(reopened, oracle["question"])
        _, again_values, again_images, _ = shared.painted(reopened)
        if ([etree.tostring(node) for node in roots.values()] != [etree.tostring(node) for node in again[1].values()]
            or values != again_values or images != again_images):
            issues.append("fresh_reopen_resave_not_stable")
        (folder / f"{stage}-p{frame_start[1]+1}.png").write_bytes(bytes(parsed.render_png(frame_start[1])))
        outcomes.append({"case": stage, "ok": not issues, "failures": issues,
                         "pages": parsed.page_count, "question_height_hwp": height,
                         "following_distance_px": distance, "glyphs": glyphs,
                         "picture_bounds": [picture[2] for picture in pictures],
                         "initial_pages": initial_pages, "initial_question_height_hwp": original_height,
                         "initial_following_distance_px": before_distance,
                         "following_position": list(following[1:4]),
                         "initial_following_position": list(before_next[1:4])})
        previous = reopened
    return outcomes


def inspect(oracle, path, folder, edits, before=None):
    failures = []
    data, roots, root, draw = package(path, oracle["question"])
    failures.extend(native_issues(oracle, draw))
    parsed, values, images, rules = shared.painted(path)
    scale = float(root.find(".//" + HP + "pagePr").get("width")) / 75 / oracle["page_width"]
    selected = shared.locate(values, oracle["text"])
    page = selected[0][1]
    if page != oracle["page"]:
        failures.append("source_frame_page")
    matched_images = [image for image in images if image[0] == oracle["image_pixels"]]
    if len(matched_images) != 1:
        failures.append("source_picture_pixel_inventory")
    frame = [value * scale for value in oracle["frame"]]
    row_errors = []
    for row in oracle["rows"]:
        native = unique_in_frame(values, row["text"], oracle["text"])
        ink = next(char for char in row["chars"] if not char["c"].isspace())
        source_chars = [char for char in row["chars"] for _ in shared.compact(char["c"])]
        if len(native) != len(source_chars):
            raise AssertionError("complete source and native row glyph inventories differ")
        horizontal_errors = [value[2] - char["origin"][0] * scale
                             for value, char in zip(native, source_chars)]
        outside_origins = [{"char": value[0], "x_px": value[2]}
                           for value in native if not frame[0]-.6 <= value[2] <= frame[2]+.6]
        delta = [native[0][2] - ink["origin"][0] * scale,
                 native[0][3] - row["baseline"] * scale]
        spread = max(record[3] for record in native) - min(record[3] for record in native)
        row_errors.append({"text": row["text"], "first_ink_delta_px": delta, "baseline_spread_px": spread,
                           "last_glyph_origin_x_delta_px": horizontal_errors[-1],
                           "maximum_glyph_origin_x_error_px": max(map(abs, horizontal_errors)),
                           "glyph_origins_outside_source_frame": outside_origins})
        if abs(delta[0]) > .6 or abs(delta[1]) > .6 or spread > .15:
            failures.append("source_prose_row_geometry")
        if outside_origins:
            failures.append("source_prose_glyph_origin_outside_frame")
    edge_lines = [line for index, line in rules if index == page]
    for y in (frame[1], frame[3]):
        parts = [(min(a, c), max(a, c)) for a, b, c, d in edge_lines if max(abs(b-y), abs(d-y)) < .5]
        if not shared.union_covers(parts, frame[0], frame[2]):
            failures.append("source_frame_horizontal_rule")
    for x in (frame[0], frame[2]):
        parts = [(min(b, d), max(b, d)) for a, b, c, d in edge_lines if max(abs(a-x), abs(c-x)) < .5]
        if not shared.union_covers(parts, frame[1], frame[3]):
            failures.append("source_frame_vertical_rule")
    image_delta = None
    if matched_images:
        image_delta = [a-b*scale for a, b in zip(matched_images[0][2], oracle["image_bbox"])]
        if matched_images[0][1] != page or max(map(abs, image_delta)) > .6:
            failures.append("source_picture_display_bounds")
    next_values = shared.locate(values, oracle["next_prompt"]["text"])
    next_delta = next_values[0][3] - oracle["next_prompt"]["baseline"] * scale
    if abs(next_delta) > .6:
        failures.append("following_question_absolute_baseline")
    # These mutants exercise the independent owner checks, not a source flag.
    negative_count = 0
    if not native_issues(oracle, draw):
        for case in ("missingprose", "missingpicture", "pageanchor", "overlap"):
            changed = deepcopy(draw)
            if case == "missingprose":
                intro = next(p for p in changed.iter(HP + "p")
                             if shared.compact(shared.direct_text(p)) == shared.compact(oracle["intro"]))
                next(intro.iter(HP + "t")).text = "omitted original prose"
            elif case == "missingpicture":
                picture = next(changed.iter(HP + "pic")); picture.getparent().remove(picture)
            else:
                picture = next(changed.iter(HP + "pic")); pos = picture.find(HP + "pos")
                pos.set("treatAsChar", "0")
                if case == "pageanchor":
                    pos.set("vertRelTo", "PAGE")
                else:
                    pos.set("allowOverlap", "1"); picture.set("textWrap", "IN_FRONT_OF_TEXT")
            shared.check(bool(native_issues(oracle, changed)), f"independent wrapped-prose oracle rejects {case}")
            negative_count += 1
    glyphs = glyph_report(path, oracle["text"], matched_images, root)
    if not glyphs["ok"]:
        failures.append("original_actual_pdf_glyph_bounds")
    edit_results = None
    if edits:
        try:
            edit_results = edit_flow(oracle, path, folder, values, matched_images, parsed.page_count)
            if not all(result["ok"] for result in edit_results):
                failures.append("public_edit_flow")
        except Exception as error:
            edit_results = {"ok": False, "error": f"{type(error).__name__}: {error}"}
            failures.append("public_edit_flow")
    after = verification_snapshot(Path(oracle["source"]), path)
    before = before or after
    stable = before == after
    if not stable:
        failures.append("verification_inputs_or_code_changed_during_run")
    changed = sorted(key for key in before["code_files"].keys() | after["code_files"].keys()
                     if before["code_files"].get(key) != after["code_files"].get(key))
    (folder / "verification-snapshots.json").write_text(
        json.dumps({"before": before, "after": after}, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"ok": not failures, "source": oracle["source"], "hwpx": str(path), "pages": parsed.page_count,
              "stable_verification_snapshot": stable, "changed_code_files": changed,
              "verification_before": snapshot_summary(before), "verification_after": snapshot_summary(after),
              "failures": sorted(set(failures)), "source_rows": len(oracle["rows"]),
              "row_errors": row_errors, "picture_delta_px": image_delta,
              "following_question_baseline_delta_px": next_delta,
              "independent_native_negative_cases": negative_count,
              "actual_pdf_glyphs": glyphs,
              "edit_proof": edit_results if edits else "not_requested"}
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / f"initial-p{page + 1}.png").write_bytes(bytes(parsed.render_png(page)))
    print("WRAPPED_PROSE_" + ("OK" if report["ok"] else "FAIL"), json.dumps(report, ensure_ascii=False))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "data/external_exam_qa/2026_september_high2/english.pdf")
    parser.add_argument("--page", type=int, default=3, help="zero-based physical source page")
    parser.add_argument("--question", type=int, default=27)
    parser.add_argument("--hwpx", type=Path)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--edits", action="store_true")
    args = parser.parse_args()
    if not args.source.is_file() or (args.hwpx and not args.hwpx.is_file()):
        print("SKIP: source or HWPX fixture missing"); return 2
    args.artifacts.mkdir(parents=True, exist_ok=True)
    before = verification_snapshot(args.source, args.hwpx) if args.hwpx else None
    oracle = source_oracle(args.source, args.page, args.question)
    (args.artifacts / "source-oracle.json").write_text(json.dumps(oracle, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.hwpx:
        print("SOURCE_WRAPPED_PROSE_OK"); return 0
    return 0 if inspect(oracle, args.hwpx, args.artifacts, args.edits, before)["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
