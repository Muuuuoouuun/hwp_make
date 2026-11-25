"""측정 도구: 문항 인식이 어느 문항·지문·그림에도 넣지 않고 버리는 본문 글자(고아 줄).

문항 번호 일치율은 100%여도 본문이 빠질 수 있다. 2026-11-25에 이 측정으로 90책자·81만 자의
약 40%가 버려지던 것을 찾았고(테두리 상자 안 글, 문항 박스 밖 지문), 수정 뒤 0.35%가 됐다.
인식(app/recognition)을 고칠 때 전후로 돌려 본문 보존율을 비교한다. 게이트 대상이 아니다
(로컬 시험지 PDF가 있어야 한다).

분류:
- 상자안_소실: 그림으로 자르지 않는 영역 안인데 문항 본문에도 없는 줄
- 문항박스밖: 어느 문항 박스에도, 공통 지문에도 들어가지 않은 줄
- 그림에_보존: 본문에서는 빠졌지만 잘라 낸 그림 안에 남는 줄(소실 아님)

사용:
  python scripts/audit_recognition_orphans.py                 # data/external_exam_qa 아래 PDF 전부
  python scripts/audit_recognition_orphans.py <폴더> --out report.json --limit 10
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ.setdefault("HWP_MAKE_DATA_DIR", tempfile.mkdtemp(prefix="hwp_make_orphan_audit_"))

import fitz  # noqa: E402

from app.recognition import pdf_segment as seg  # noqa: E402
from app.recognition.pipeline import infer_subject  # noqa: E402
from app.recognition.schema import BlockType  # noqa: E402

LOST_KINDS = ("상자안_소실", "문항박스밖", "문항박스안_기타")


def _key(box, text: str) -> tuple[int, int, str]:
    return round(box.left), round(box.top), text[:40]


def audit(pdf: Path) -> dict:
    data = pdf.read_bytes()
    pages = seg.segment_pdf(data, subject=infer_subject(pdf.name))
    result = {"file": pdf.name, "subject": "", "chars": 0, "orphan": collections.Counter(), "examples": []}
    with fitz.open(stream=data, filetype="pdf") as document:
        for index, model in enumerate(pages):
            if not model.problems:
                continue  # 번호 없는 쪽은 지문·보존 항목 경로가 통째로 맡는다
            result["subject"] = str(getattr(model.subject, "value", model.subject))
            height = float(model.height_px)
            assigned = set()
            titles: collections.Counter = collections.Counter()
            problem_boxes = []
            for block in model.blocks:
                if block.block_type == BlockType.TITLE and block.metadata.get("marker_kind") == "number":
                    titles[block.text] += 1
                    problem_boxes.append(block.bbox)
                else:
                    assigned.add(_key(block.bbox, block.text))
            shared = "\n".join(str(p.get("text") or "") for p in model.metadata.get("shared_passages") or [])
            # 쪽 선두 줄은 앞 쪽에 열린 지문이 있을 때 파이프라인이 그 지문에 이어 붙인다.
            previous = pages[index - 1] if index else None
            if previous is not None and (
                any(p.get("open") for p in previous.metadata.get("shared_passages") or [])
                or (not previous.problems
                    and any(seg._PASSAGE_RANGE_RE.search(str(b.text or "")) for b in previous.blocks))):
                shared += "\n" + str((model.metadata.get("leading_passage") or {}).get("text") or "")
            figures = [seg.Box.from_points(*bbox) for bbox in model.metadata.get("figure_bboxes_px") or []]
            crop = [figures[i] for i in model.metadata.get("figure_crop_indexes") or [] if i < len(figures)]
            for line in seg._extract_text_lines(document[index], float(model.metadata["render_scale"])):
                text, box = line["text"], line["box"]
                if seg._looks_like_footer_band_line(line, height) or box.top <= height * 0.11:
                    continue
                count = len("".join(text.split()))
                result["chars"] += count
                if _key(box, text) in assigned:
                    continue
                if titles.get(text, 0) > 0:
                    titles[text] -= 1
                    continue
                if text.strip() and text.strip() in shared:
                    continue
                cx, cy = (box.left + box.right) / 2, (box.top + box.bottom) / 2

                def inside(region) -> bool:
                    return region.left <= cx <= region.right and region.top <= cy <= region.bottom

                if any(inside(figure) for figure in crop):
                    kind = "그림에_보존"
                elif any(inside(figure) for figure in figures):
                    kind = "상자안_소실"
                elif any(inside(region) for region in problem_boxes):
                    kind = "문항박스안_기타"
                else:
                    kind = "문항박스밖"
                result["orphan"][kind] += count
                if kind in LOST_KINDS and count >= 8 and len(result["examples"]) < 6:
                    result["examples"].append({"page": index + 1, "kind": kind, "text": text[:60]})
    result["orphan"] = dict(result["orphan"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="문항 인식의 본문 보존율 측정")
    parser.add_argument("corpus", nargs="?", default=str(ROOT / "data" / "external_exam_qa"))
    parser.add_argument("--out", help="책자별 결과 JSON 경로")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    pdfs = sorted(p for p in Path(args.corpus).rglob("*.pdf")
                  if not any(part in {"raw", "정답표"} or part.startswith("outputs") for part in p.parts))
    if not pdfs:
        print(f"SKIP: PDF 없음: {args.corpus}")
        return 2
    rows = []
    for pdf in pdfs[: args.limit]:
        try:
            rows.append(audit(pdf))
        except Exception as exc:  # noqa: BLE001 - 측정은 계속한다
            rows.append({"file": pdf.name, "error": f"{type(exc).__name__}: {exc}"})
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(row.get("chars", 0) for row in rows)
    kinds: collections.Counter = collections.Counter()
    by_subject: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for row in rows:
        orphan = row.get("orphan") or {}
        kinds.update(orphan)
        by_subject[row.get("subject") or "?"][0] += row.get("chars", 0)
        by_subject[row.get("subject") or "?"][1] += sum(orphan.get(kind, 0) for kind in LOST_KINDS)
    lost = sum(kinds.get(kind, 0) for kind in LOST_KINDS)
    print(f"책자 {len(rows)} · 본문 글자 {total} · 소실 {lost} ({lost / max(1, total):.2%})")
    for kind, count in kinds.most_common():
        print(f"  {kind}: {count} ({count / max(1, total):.2%})")
    print("과목별 소실률:")
    for subject, (chars, gone) in sorted(by_subject.items(), key=lambda item: -item[1][1]):
        print(f"  {subject}: {gone}/{chars} = {gone / max(1, chars):.2%}")
    errors = [row["file"] for row in rows if row.get("error")]
    if errors:
        print("오류:", errors)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
