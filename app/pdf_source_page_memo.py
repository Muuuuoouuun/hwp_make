"""Per-page memo for pure PDF text-layer extraction shared within a conversion.

One PDF conversion opens the same source file many times (the writer, the
editability check, paragraph-flow and question inspections) and extracts the
same page text layer about twenty times per page.  The extraction is a pure
function of the page content, so the result is computed once per
(file content, page number) and every caller receives its own structural copy.
Callers keep mutating their copy freely, exactly as they mutated the fresh
PyMuPDF result before.

Only documents opened from a file path are memoized.  The key is the SHA-256 of
the file bytes, so the upload copy and the run-directory copy of the same PDF
share one memo.  Documents opened from memory are computed every time.

Memory: a memoized page costs about 3.7 MB across the four kinds (measured on
a 40-page Korean exam), so documents longer than ``MAX_MEMO_DOCUMENT_PAGES``
are not memoized at all (no LRU thrash, no extra memory on the 200-page case),
entries are bounded by count and, for extractions that carry embedded image
bytes, by total bytes, an oversized page (scans) is never kept, and a
conversion releases its own entries when it finishes (``forget_file``).
"""
from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from typing import Any, Callable

import fitz

_LOCK = threading.Lock()
# (realpath, size, mtime_ns) -> sha256 hex digest of the file bytes
_DIGESTS: "OrderedDict[tuple[str, int, int], str]" = OrderedDict()
# (digest, page_number, kind) -> (value, weight_bytes)
_PAGES: "OrderedDict[tuple[str, int, str], tuple[Any, int]]" = OrderedDict()
_TOTAL_WEIGHT = 0
MAX_DIGESTS = 64
# A longer document is served uncached: 64 pages x 3.7 MB is the ceiling one
# conversion may add, and a sequential multi-pass writer would only thrash an
# LRU that is smaller than the document.
MAX_MEMO_DOCUMENT_PAGES = 64
# Entry bound (4 kinds per page): two 64-page documents side by side.
MAX_PAGES = 512
# Embedded image bytes inside text dicts: skip one huge page, cap the total.
MAX_ENTRY_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 192 * 1024 * 1024


def document_digest(document: Any) -> str | None:
    """Return the content digest of a file-backed document, or None."""
    name = str(getattr(document, "name", "") or "")
    if not name:
        return None
    try:
        stat = os.stat(name)
        key = (os.path.realpath(name), int(stat.st_size), int(stat.st_mtime_ns))
    except OSError:
        return None
    with _LOCK:
        digest = _DIGESTS.get(key)
        if digest is not None:
            _DIGESTS.move_to_end(key)
            return digest
    hasher = hashlib.sha256()
    try:
        with open(name, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(chunk)
    except OSError:
        return None
    digest = hasher.hexdigest()
    with _LOCK:
        _DIGESTS[key] = digest
        while len(_DIGESTS) > MAX_DIGESTS:
            _DIGESTS.popitem(last=False)
    return digest


def _evict_locked() -> None:
    global _TOTAL_WEIGHT
    while _PAGES and (len(_PAGES) > MAX_PAGES or _TOTAL_WEIGHT > MAX_TOTAL_BYTES):
        _, (_, weight) = _PAGES.popitem(last=False)
        _TOTAL_WEIGHT -= weight


def page_memo(page: fitz.Page, kind: str, compute: Callable[[], Any],
              copy: Callable[[Any], Any] = lambda value: value,
              weight: Callable[[Any], int] | None = None) -> Any:
    """Return ``compute()`` for ``page``, memoized per file content and page."""
    global _TOTAL_WEIGHT
    document = getattr(page, "parent", None)
    try:
        if document is None or len(document) > MAX_MEMO_DOCUMENT_PAGES:
            return compute()
    except (TypeError, ValueError, RuntimeError):
        return compute()
    digest = document_digest(document)
    if digest is None:
        return compute()
    key = (digest, int(page.number), kind)
    with _LOCK:
        hit = _PAGES.get(key)
        if hit is not None:
            _PAGES.move_to_end(key)
    if hit is not None:
        return copy(hit[0])  # copy outside the lock; the stored value is never mutated
    value = compute()
    size = int(weight(value)) if weight is not None else 0
    if size <= MAX_ENTRY_BYTES:
        with _LOCK:
            if key not in _PAGES:
                _PAGES[key] = (value, size)
                _TOTAL_WEIGHT += size
                _evict_locked()
    return copy(value)


def _copy_span(span: dict[str, Any]) -> dict[str, Any]:
    chars = span.get("chars")
    if chars is None:
        return {key: (_copy_value(item) if isinstance(item, (dict, list, fitz.Rect, fitz.Point)) else item)
                for key, item in span.items()}
    copied = dict(span)
    copied["chars"] = [dict(char) for char in chars]
    return copied


def _copy_line(line: dict[str, Any]) -> dict[str, Any]:
    copied = {}
    for key, item in line.items():
        if key == "spans":
            copied[key] = [_copy_span(span) for span in item]
        elif isinstance(item, (dict, list, fitz.Rect, fitz.Point)):
            copied[key] = _copy_value(item)
        else:
            copied[key] = item
    return copied


def copy_text_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deep-copy the ``_iter_text_lines`` structure without ``copy.deepcopy``.

    Lines hold spans, spans hold chars; scalars, tuples and bytes are immutable
    and shared, every dict/list/Rect is duplicated.
    """
    return [_copy_line(line) for line in lines]


def copy_text_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Structural copy of a ``page.get_text("dict"/"rawdict")`` result."""
    blocks = []
    for block in data.get("blocks", []):
        if block.get("type") == 0:
            copied = dict(block)
            copied["lines"] = [_copy_line(line) for line in block.get("lines", [])]
            blocks.append(copied)
        else:
            blocks.append(dict(block))  # image bytes are immutable and shared
    result = dict(data)
    result["blocks"] = blocks
    return result


def _text_dict_weight(data: dict[str, Any]) -> int:
    total = 0
    for block in data.get("blocks", []):
        if block.get("type") == 1:
            total += len(block.get("image") or b"") + len(block.get("mask") or b"")
    return total


def source_text_dict(page: fitz.Page, kind: str = "dict") -> dict[str, Any]:
    """Memoized ``page.get_text(kind)`` with default flags; callers get a copy.

    ``kind`` is "dict" or "rawdict".  Every known caller only reads the blocks,
    but the copy keeps the old fresh-result semantics for free.
    """
    return page_memo(page, f"text_{kind}", lambda: page.get_text(kind), copy_text_dict, _text_dict_weight)


def _copy_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    if isinstance(value, fitz.Rect):
        return fitz.Rect(value)
    if isinstance(value, fitz.Point):
        return fitz.Point(value)
    return value


def forget_file(path: Any) -> None:
    """Release the memo of one conversion's source file (all paths sharing its bytes)."""
    global _TOTAL_WEIGHT
    try:
        stat = os.stat(path)
        key = (os.path.realpath(path), int(stat.st_size), int(stat.st_mtime_ns))
    except (OSError, TypeError, ValueError):
        return
    with _LOCK:
        digest = _DIGESTS.pop(key, None)
        if digest is None:
            return
        for other in [k for k, d in _DIGESTS.items() if d == digest]:
            _DIGESTS.pop(other, None)
        for page_key in [k for k in _PAGES if k[0] == digest]:
            _, weight = _PAGES.pop(page_key)
            _TOTAL_WEIGHT -= weight


def clear() -> None:
    """Drop every memoized page (tests and long-running processes)."""
    global _TOTAL_WEIGHT
    with _LOCK:
        _PAGES.clear()
        _DIGESTS.clear()
        _TOTAL_WEIGHT = 0


def stats() -> dict[str, int]:
    with _LOCK:
        return {"pages": len(_PAGES), "documents": len(_DIGESTS), "image_bytes": _TOTAL_WEIGHT}
