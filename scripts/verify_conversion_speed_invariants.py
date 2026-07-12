"""Regression pins for conversion optimizations that must preserve output."""
from __future__ import annotations

import builtins
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import pdf_layout_writer as writer  # noqa: E402


def _payload(texts: list[str]) -> dict[str, bytes]:
    root = writer.etree.Element(writer._q("section"))
    for text in texts:
        writer.etree.SubElement(root, writer._q("t")).text = text
    return {"Contents/section0.xml": writer.etree.tostring(root)}


def _legacy_preview(payloads: dict[str, bytes], *, limit: int) -> str:
    texts: list[str] = []
    for name in writer._section_names_from_payloads(payloads):
        section = writer.etree.fromstring(payloads[name])
        for node in section.findall(f".//{writer._q('t')}"):
            if node.text:
                texts.append(node.text)
                if sum(len(text) for text in texts) >= limit:
                    break
        if sum(len(text) for text in texts) >= limit:
            break
    preview = "\r\n".join(texts).strip()
    return (preview or "HWP Make PDF layout export")[:limit]


def main() -> int:
    failures: list[str] = []

    sample = _payload(["alpha", "beta", "gamma", "delta"])
    for limit in (1, 5, 9, 17, 200000):
        expected = _legacy_preview(sample, limit=limit)
        actual = writer._preview_text_from_payloads(sample, limit=limit)
        if actual != expected:
            failures.append(
                f"preview mismatch at limit={limit}: {actual!r} != {expected!r}"
            )

    node_count = 4000
    large = _payload([f"line-{index:04d}" for index in range(node_count)])
    len_calls = 0

    def counting_len(value: Any) -> int:
        nonlocal len_calls
        len_calls += 1
        return builtins.len(value)

    writer.len = counting_len  # type: ignore[attr-defined]
    try:
        preview = writer._preview_text_from_payloads(large, limit=200000)
    finally:
        delattr(writer, "len")

    if not preview.startswith("line-0000\r\nline-0001"):
        failures.append("large preview text order changed")
    if len_calls > node_count + 20:
        failures.append(
            f"preview length accounting is no longer linear: {len_calls} len calls"
        )

    page = SimpleNamespace(rect=writer.fitz.Rect(0, 0, 1000, 1000))
    image_region = writer.fitz.Rect(100, 100, 500, 300)
    label_lines = [
        {
            "bbox": (120, 110 + index * 30, 160, 130 + index * 30),
            "spans": [{"text": label}],
        }
        for index, label in enumerate(("①", "②", "③", "④", "⑤"))
    ]
    kept, text_regions = writer._convert_textual_image_regions(
        page,
        [{"bbox": image_region, "image": b"diagram", "ext": "png"}],
        preserve_editable_text=True,
        text_lines=label_lines,
    )
    if len(kept) != 1 or text_regions:
        failures.append("a five-label diagram was misclassified as editable text")

    prose_lines = [
        {
            "bbox": (120, 110 + index * 30, 420, 130 + index * 30),
            "spans": [{"text": "editable prose inside a bordered region"}],
        }
        for index in range(5)
    ]
    kept, text_regions = writer._convert_textual_image_regions(
        page,
        [{"bbox": image_region, "image": b"prose", "ext": "png"}],
        preserve_editable_text=True,
        text_lines=prose_lines,
    )
    if kept or len(text_regions) != 1:
        failures.append("a prose-heavy bordered region was not kept as editable text")

    if failures:
        for failure in failures:
            print(f"  [FAIL] {failure}")
        print("CONVERSION_SPEED_INVARIANTS_FAIL")
        return 1

    print("  [PASS] preview text is byte-for-byte compatible at all tested limits")
    print(f"  [PASS] preview length accounting is linear ({len_calls} calls / {node_count} nodes)")
    print("  [PASS] sparse diagram labels remain images while prose regions stay editable")
    print("CONVERSION_SPEED_INVARIANTS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
