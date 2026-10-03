"""Regression pins for the per-page PDF text-layer memo (2026-10-03 speed work).

The memo must be invisible to callers: identical structures, fresh copies that
callers may mutate, no sharing for memory-opened documents, content-keyed
sharing between two paths holding the same bytes, bounded memory, and the
``_pdf_output_text`` string cache must equal the uncached normalizer.
Synthetic PDFs only; no private samples.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import fitz
except Exception:
    print("SKIP: PyMuPDF(fitz) is unavailable")
    raise SystemExit(2)

from app import pdf_source_page_memo as memo  # noqa: E402
from app import pdf_layout_writer as writer  # noqa: E402


def _make_pdf() -> bytes:
    # Base-14 fonts cannot draw Hangul, so the synthetic text is ASCII.
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 60), "2026 mock exam paper (synthetic)", fontsize=12)
    page.draw_line((40, 90), (555, 90), width=0.8)
    page.insert_text((72, 140), "1. Which statement is true?", fontsize=11)
    page.insert_text((90, 170), "(a) first    (b) second    (c) third", fontsize=10)
    # one tiny embedded bitmap (restore_bitmap_characters looks at these)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 6, 8), 0)
    pix.clear_with(0)
    page.insert_image(fitz.Rect(300, 160, 306, 168), pixmap=pix)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((72, 140), "2. Second question", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _plain(value):
    if isinstance(value, fitz.Rect):
        return ["Rect", *value]
    if isinstance(value, fitz.Point):
        return ["Point", *value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, bytes):
        return ["bytes", len(value)]
    return value


def _same(a, b) -> bool:
    return json.dumps(_plain(a), sort_keys=True) == json.dumps(_plain(b), sort_keys=True)


def main() -> int:
    failures: list[str] = []
    memo.clear()
    with tempfile.TemporaryDirectory(prefix="hwp_make_page_memo_", ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        data = _make_pdf()
        path_a = root / "upload.pdf"
        path_b = root / "run_copy.pdf"
        path_a.write_bytes(data)
        path_b.write_bytes(data)

        with fitz.open(path_a) as doc:
            page = doc[0]
            uncached = writer._iter_text_lines_uncached(page)
            first = writer._iter_text_lines(page)
            second = writer._iter_text_lines(doc[0])
            if not _same(uncached, first) or not _same(first, second):
                failures.append("memoized text lines differ from the uncached extraction")
            if not first or first is second or first[0]["spans"][0] is second[0]["spans"][0]:
                failures.append("memo must hand out fresh line/span objects")
            # Callers mutate their copy; the memo must not see it.
            second[0]["spans"][0]["text"] = "MUTATED"
            second[0]["spans"][0]["chars"][0]["c"] = "Z"
            second[0]["bbox"].x0 = -1
            third = writer._iter_text_lines(doc[0])
            if third[0]["spans"][0]["text"] == "MUTATED" or third[0]["spans"][0]["chars"][0]["c"] == "Z" or third[0]["bbox"].x0 == -1:
                failures.append("mutation of one caller's copy leaked into the memo")
            if not isinstance(third[0]["bbox"], fitz.Rect):
                failures.append("line bbox must stay a fitz.Rect after copying")

            body_uncached = writer._page_body_top_uncached(page)
            if writer._page_body_top(page) != body_uncached or writer._page_body_top(doc[0]) != body_uncached:
                failures.append("memoized body top differs from the uncached value")

            raw_dict = page.get_text("dict")
            memo_dict = memo.source_text_dict(page)
            again = memo.source_text_dict(doc[0])
            if not _same(raw_dict, memo_dict) or not _same(memo_dict, again):
                failures.append("memoized text dict differs from page.get_text('dict')")
            images = [b for b in memo_dict["blocks"] if b.get("type") == 1]
            if not images:
                failures.append("synthetic page lost its embedded image block")
            elif images[0]["image"] is not [b for b in again["blocks"] if b.get("type") == 1][0]["image"]:
                failures.append("image bytes should be shared between copies (immutable)")
            memo_dict["blocks"][0]["lines"][0]["spans"][0]["text"] = "MUTATED"
            if memo.source_text_dict(doc[0])["blocks"][0]["lines"][0]["spans"][0]["text"] == "MUTATED":
                failures.append("text dict copy leaked a mutation into the memo")
            raw_rawdict = page.get_text("rawdict")
            if not _same(raw_rawdict, memo.source_text_dict(page, "rawdict")):
                failures.append("memoized rawdict differs from page.get_text('rawdict')")

        # The run-directory copy of the same bytes shares the memo (content keyed).
        before = memo.stats()["pages"]
        with fitz.open(path_b) as doc_b:
            lines_b = writer._iter_text_lines(doc_b[0])
        if memo.stats()["pages"] != before:
            failures.append("a second path with identical bytes must hit the same memo entries")
        if not _same(lines_b, uncached):
            failures.append("content-keyed hit returned different lines")
        if len({memo.document_digest(fitz.open(p)) for p in (path_a, path_b)}) != 1:
            failures.append("identical files must share one digest")

        # Different content at the same path (rewritten file) must not reuse the entry.
        other = fitz.open()
        other.new_page(width=595, height=842).insert_text((72, 140), "9. other document", fontsize=11)
        path_a.write_bytes(other.tobytes())
        other.close()
        with fitz.open(path_a) as doc_c:
            if "other document" not in writer._line_text(writer._iter_text_lines(doc_c[0])[0]):
                failures.append("rewritten file content must invalidate the memo")

        # Memory-opened documents are never memoized.
        with fitz.open(stream=data, filetype="pdf") as mem_doc:
            if memo.document_digest(mem_doc) is not None:
                failures.append("stream documents must not get a digest")
            count = memo.stats()["pages"]
            writer._iter_text_lines(mem_doc[0])
            if memo.stats()["pages"] != count:
                failures.append("stream documents must not add memo entries")

        # Bounded: entries evict once past MAX_PAGES / byte caps; oversized pages are skipped.
        old_pages, old_total, old_entry = memo.MAX_PAGES, memo.MAX_TOTAL_BYTES, memo.MAX_ENTRY_BYTES
        try:
            memo.clear()
            memo.MAX_PAGES = 2
            with fitz.open(path_b) as doc_b:
                for kind in ("a", "b", "c"):
                    memo.page_memo(doc_b[0], kind, lambda: {"kind": kind})
            if memo.stats()["pages"] > 2:
                failures.append("MAX_PAGES bound is not enforced")
            memo.clear()
            memo.MAX_PAGES = old_pages
            memo.MAX_ENTRY_BYTES = 10
            with fitz.open(path_b) as doc_b:
                memo.page_memo(doc_b[0], "heavy", lambda: {"x": 1}, weight=lambda value: 100)
            if memo.stats()["pages"] != 0:
                failures.append("an entry above MAX_ENTRY_BYTES must not be kept")
            memo.MAX_ENTRY_BYTES = old_entry
            memo.MAX_TOTAL_BYTES = 150
            with fitz.open(path_b) as doc_b:
                for kind in ("h1", "h2", "h3"):
                    memo.page_memo(doc_b[0], kind, lambda: {"k": kind}, weight=lambda value: 100)
            if memo.stats()["image_bytes"] > 150:
                failures.append("MAX_TOTAL_BYTES bound is not enforced")
        finally:
            memo.MAX_PAGES, memo.MAX_TOTAL_BYTES, memo.MAX_ENTRY_BYTES = old_pages, old_total, old_entry
            memo.clear()

    # A long document is never memoized (memory ceiling), and forget_file releases
    # every entry that belongs to one source file, including a same-bytes copy.
    with tempfile.TemporaryDirectory(prefix="hwp_make_page_memo_big_", ignore_cleanup_errors=True) as temp:
        big = fitz.open()
        for index in range(memo.MAX_MEMO_DOCUMENT_PAGES + 1):
            big.new_page(width=595, height=842).insert_text((72, 100), f"{index + 1}. page", fontsize=11)
        big_path = Path(temp) / "big.pdf"
        big_path.write_bytes(big.tobytes())
        big.close()
        memo.clear()
        with fitz.open(big_path) as doc_big:
            writer._iter_text_lines(doc_big[0])
            memo.source_text_dict(doc_big[0])
        if memo.stats()["pages"] != 0:
            failures.append("documents longer than MAX_MEMO_DOCUMENT_PAGES must not be memoized")
        small_a = Path(temp) / "small_a.pdf"
        small_b = Path(temp) / "small_b.pdf"
        small_a.write_bytes(data)
        small_b.write_bytes(data)
        with fitz.open(small_a) as doc_a, fitz.open(small_b) as doc_b:
            writer._iter_text_lines(doc_a[0])
            memo.source_text_dict(doc_b[1])
        if memo.stats()["pages"] < 2 or memo.stats()["documents"] != 2:
            failures.append(f"unexpected memo population before release: {memo.stats()}")
        memo.forget_file(small_b)
        if memo.stats()["pages"] != 0 or memo.stats()["documents"] != 0:
            failures.append(f"forget_file must release every path sharing the bytes: {memo.stats()}")
        memo.forget_file(Path(temp) / "missing.pdf")  # must not raise

    # _pdf_output_text cache == uncached normalizer, including None/empty inputs.
    samples = ["", None, "x^2 + y^2", "√2  □ □", "15세기 국어 ‘코ᇰ’의 ‘’은", "a_{n}}", "①$63"]
    for text in samples:
        expected = "".join(
            ch for ch in writer.math_text.normalize_recognized_math_layout_text(str(text or ""))
            if ch not in writer._MATH_VISUAL_PLACEHOLDER_CHARS and not (0xE000 <= ord(ch) <= 0xF8FF)
        )
        if writer._pdf_output_text(text) != expected or writer._pdf_output_text(text) != expected:
            failures.append(f"_pdf_output_text cache changed the result for {text!r}")

    if failures:
        for failure in failures:
            print("FAIL:", failure)
        return 1
    print("PDF source page memo OK: identical structures, isolated copies, content-keyed sharing, stream bypass, bounds, long-document gate, release, output-text cache")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
