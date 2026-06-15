"""웹 페이지에서 문제 자료를 수집한다.

URL을 받아 본문 텍스트와 이미지를 추출해 로컬 DB에 문제로 등록한다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from lxml import html as lxml_html

from . import importers


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HWPMake/0.2 (local collection tool)"
SKIP_TAGS = {"script", "style", "noscript", "header", "footer", "nav", "aside", "form", "iframe", "svg"}
BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "pre", "blockquote", "section", "article"}
MAX_IMAGES = 12
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _validate_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("http/https URL만 수집할 수 있습니다.")
    return url


def _client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=20,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ko, en;q=0.8"},
    )


def _extract_paragraphs(tree: Any, base_url: str) -> list[tuple[str, list[str]]]:
    """문서 순서대로 (텍스트, 이미지 URL 목록) 문단을 추출한다."""
    for tag in SKIP_TAGS:
        for node in tree.findall(f".//{tag}"):
            node.drop_tree()

    body = tree.find(".//body")
    if body is None:
        body = tree
    # article/main이 있으면 본문으로 우선 사용
    for selector in (".//article", ".//main"):
        main = body.find(selector)
        if main is not None and len(main.text_content().strip()) > 200:
            body = main
            break

    paragraphs: list[tuple[str, list[str]]] = []
    seen_images: set[str] = set()
    for node in body.iter():
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower()
        if tag == "img":
            src = node.get("src") or node.get("data-src") or ""
            if not src or src.startswith("data:"):
                continue
            absolute = urljoin(base_url, src)
            if absolute in seen_images:
                continue
            seen_images.add(absolute)
            paragraphs.append(("", [absolute]))
        elif tag in BLOCK_TAGS:
            # 자식 블록이 또 있으면 자식 쪽에서 처리되도록 직접 텍스트만 본다
            own_text = (node.text or "").strip()
            has_block_child = any(
                isinstance(child.tag, str) and child.tag.lower() in BLOCK_TAGS for child in node
            )
            text = own_text if has_block_child else re.sub(r"\s+", " ", node.text_content()).strip()
            if text:
                paragraphs.append((text, []))
    # 인접 중복 제거 (중첩 div에서 같은 문장이 두 번 잡히는 경우)
    deduped: list[tuple[str, list[str]]] = []
    for text, images in paragraphs:
        if deduped and text and deduped[-1][0] == text and not images:
            continue
        deduped.append((text, images))
    return deduped


def _download_images(client: httpx.Client, urls: list[str], notices: list[str]) -> dict[str, str]:
    saved: dict[str, str] = {}
    for url in urls[:MAX_IMAGES]:
        try:
            response = client.get(url)
            response.raise_for_status()
            if len(response.content) > MAX_IMAGE_BYTES:
                notices.append(f"이미지가 너무 커서 건너뜀: {url}")
                continue
            name = Path(urlparse(url).path).name or "image"
            rel_path = importers._save_image_bytes(name, response.content)
            if rel_path:
                saved[url] = rel_path
        except Exception:
            notices.append(f"이미지 다운로드 실패: {url}")
    skipped = len(urls) - len(urls[:MAX_IMAGES])
    if skipped > 0:
        notices.append(f"이미지가 많아 {skipped}개는 건너뛰었습니다.")
    return saved


def collect_url(url: str, metadata: dict[str, Any]) -> dict[str, Any]:
    url = _validate_url(url)
    notices: list[str] = []
    with _client() as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        # HTML이 아니면 파일 임포터로 넘긴다 (PDF 링크 등)
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return importers.import_pdf(Path(urlparse(url).path).name or "download.pdf", response.content, metadata)
        if content_type.startswith("image/"):
            return importers.import_image(Path(urlparse(url).path).name or "image", response.content, metadata)

        tree = lxml_html.fromstring(response.content)
        title_node = tree.find(".//title")
        page_title = (title_node.text or "").strip() if title_node is not None else ""
        paragraphs = _extract_paragraphs(tree, str(response.url))

        image_urls = [img for _, images in paragraphs for img in images]
        saved = _download_images(client, image_urls, notices)
        resolved = [
            (text, [saved[img] for img in images if img in saved])
            for text, images in paragraphs
        ]

    chunks = importers._paragraphs_to_chunks(resolved)
    if not chunks:
        return {"created": [], "notices": ["페이지에서 가져올 내용을 찾지 못했습니다.", *notices]}

    sink = importers._Sink()
    has_numbers = len(chunks) > 1
    base_title = page_title or urlparse(url).netloc
    for sequence, chunk in enumerate(chunks, start=1):
        number = importers._extract_number(chunk["text"], sequence) if has_numbers else ""
        sink.add(
            {
                **metadata,
                "source_type": "web",
                "source_name": url,
                "number": number,
                "title": f"{base_title} #{number}" if number else base_title,
                "stem": chunk["text"],
                "image_paths": chunk["images"],
            }
        )
    notices.extend(importers._dedup_notices(sink))
    notices.insert(0, f"'{base_title}'에서 {len(sink.created)}개 문항을 수집했습니다.")
    return {"created": sink.created, "notices": notices}
