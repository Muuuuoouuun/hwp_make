from __future__ import annotations

import base64
import csv
import io
import re
import shutil
import sqlite3
import struct
import uuid
import zipfile
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any

from lxml import etree
from PIL import Image
from pypdf import PdfReader

from . import storage

try:  # OCR은 선택 사항: pytesseract + tesseract 실행 파일이 있을 때만 사용
    import pytesseract

    pytesseract.get_tesseract_version()
    HAS_OCR = True
except Exception:
    pytesseract = None
    HAS_OCR = False

try:  # rhwp(러스트 HWP 엔진)는 선택 사항: 있으면 HWP 텍스트 추출에 우선 사용
    import rhwp
except Exception:
    rhwp = None


SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z가-힣._ -]+")
QUESTION_START_RE = re.compile(
    r"(?m)(?=^\s*(?:문제\s*)?\d{1,3}\s*[\.\)]|\n\s*(?:문제\s*)?\d{1,3}\s*[\.\)])"
)


def safe_filename(filename: str) -> str:
    name = Path(filename or "upload").name.strip() or "upload"
    name = SAFE_NAME_RE.sub("_", name)
    return name[:120]


def decode_base64(data: str) -> bytes:
    if "," in data and data.split(",", 1)[0].startswith("data:"):
        data = data.split(",", 1)[1]
    return base64.b64decode(data)


def save_upload(filename: str, payload: bytes) -> str:
    storage.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = storage.UPLOAD_DIR / f"{stamp}_{uuid.uuid4().hex[:8]}_{safe_filename(filename)}"
    path.write_bytes(payload)
    return path.relative_to(storage.DATA_DIR).as_posix()


def _clean_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _split_questions(page_text: str) -> list[str]:
    text = _clean_text(page_text)
    if not text:
        return []
    chunks = [chunk.strip() for chunk in QUESTION_START_RE.split(text) if chunk.strip()]
    if len(chunks) <= 1:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        return paragraphs if len(paragraphs) > 1 else [text]
    return chunks


def _extract_number(text: str, fallback: int) -> str:
    match = re.match(r"\s*(?:문제\s*)?(\d{1,3})\s*[\.\)]", text)
    return match.group(1) if match else str(fallback)


def import_pdf(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    rel_path = save_upload(filename, payload)
    pdf_path = storage.DATA_DIR / rel_path
    created: list[dict[str, Any]] = []
    notices: list[str] = []
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:  # pragma: no cover - library-specific errors
        problem = storage.create_problem(
            {
                **metadata,
                "source_type": "pdf",
                "source_name": filename,
                "title": Path(filename).stem,
                "stem": f"PDF를 열 수 없습니다: {exc}",
            }
        )
        return {"created": [problem], "notices": ["PDF 분석에 실패해 빈 문제로 등록했습니다."]}

    sequence = 1
    total_pdf_images = 0
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        page_images: list[str] = []
        try:
            for image_file in page.images:
                rel_path = _save_image_bytes(image_file.name or f"p{page_index}.png", image_file.data)
                if rel_path:
                    page_images.append(rel_path)
        except Exception:
            pass
        chunks = _split_questions(page_text)
        if not chunks:
            if page_images:
                created.append(
                    storage.create_problem(
                        {
                            **metadata,
                            "source_type": "pdf",
                            "source_name": filename,
                            "source_page": page_index,
                            "title": f"{Path(filename).stem} {page_index}쪽 이미지",
                            "stem": "",
                            "image_paths": page_images,
                        }
                    )
                )
                total_pdf_images += len(page_images)
            else:
                notices.append(f"{page_index}쪽에서 텍스트를 찾지 못했습니다.")
            continue
        for chunk_index, chunk in enumerate(chunks):
            number = _extract_number(chunk, sequence)
            created.append(
                storage.create_problem(
                    {
                        **metadata,
                        "source_type": "pdf",
                        "source_name": filename,
                        "source_page": page_index,
                        "number": number,
                        "title": f"{Path(filename).stem} #{number}",
                        "stem": chunk,
                        # 페이지 내 위치를 알 수 없어 페이지 첫 문항에 모아 붙인다.
                        "image_paths": page_images if chunk_index == 0 else [],
                    }
                )
            )
            sequence += 1
        total_pdf_images += len(page_images)
    if total_pdf_images:
        notices.append(f"PDF 이미지 {total_pdf_images}개를 페이지별 첫 문항에 첨부했습니다. 필요하면 편집에서 옮기세요.")
    if not created:
        created.append(
            storage.create_problem(
                {
                    **metadata,
                    "source_type": "pdf",
                    "source_name": filename,
                    "title": Path(filename).stem,
                    "stem": "스캔 PDF이거나 텍스트를 추출하지 못했습니다. 이미지로 등록하거나 본문을 직접 입력하세요.",
                }
            )
        )
    return {"created": created, "notices": notices}


def import_image(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    rel_path = save_upload(filename, payload)
    full_path = storage.DATA_DIR / rel_path
    notices: list[str] = []
    width = height = 0
    try:
        with Image.open(full_path) as image:
            width, height = image.size
            image.verify()
    except Exception as exc:
        notices.append(f"이미지 확인 실패: {exc}")

    stem = metadata.get("stem") or ""
    if not stem and HAS_OCR:
        try:
            with Image.open(full_path) as image:
                ocr_text = pytesseract.image_to_string(image, lang="kor+eng")
            stem = _clean_text(ocr_text)
            if stem:
                notices.append("OCR로 본문을 추출했습니다. 내용을 확인하세요.")
        except Exception as exc:
            notices.append(f"OCR 실패: {exc}")
    if not stem:
        stem = "이미지 문항입니다. 본문이 필요하면 오른쪽 편집 영역에서 입력하세요."
    problem = storage.create_problem(
        {
            **metadata,
            "source_type": "image",
            "source_name": filename,
            "title": metadata.get("title") or Path(filename).stem,
            "stem": stem,
            "image_paths": [rel_path],
        }
    )
    if width and height:
        notices.append(f"이미지 크기: {width}x{height}")
    return {"created": [problem], "notices": notices}


FIELD_ALIASES = {
    "number": ["number", "num", "no", "문항", "문항번호", "번호"],
    "subject": ["subject", "과목"],
    "unit": ["unit", "chapter", "단원", "소단원"],
    "tags": ["tags", "tag", "태그"],
    "title": ["title", "제목"],
    "stem": ["stem", "question", "body", "content", "본문", "문제", "문항본문"],
    "answer": ["answer", "정답"],
    "explanation": ["explanation", "solution", "해설", "풀이"],
}


def _first(row: dict[str, Any], key: str) -> str:
    aliases = FIELD_ALIASES.get(key, [key])
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in aliases:
        value = lowered.get(alias.lower())
        if value is not None:
            return str(value).strip()
    return ""


def _choices_from_row(row: dict[str, Any]) -> list[str]:
    choices: list[str] = []
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for index in range(1, 10):
        for key in (f"choice{index}", f"option{index}", f"선지{index}", f"보기{index}"):
            if key.lower() in lowered and str(lowered[key.lower()]).strip():
                choices.append(str(lowered[key.lower()]).strip())
                break
    combined = lowered.get("choices") or lowered.get("options") or lowered.get("선지") or lowered.get("보기")
    if combined and not choices:
        choices = [
            part.strip()
            for part in re.split(r"\s*(?:\||/|;|\n)\s*", str(combined))
            if part.strip()
        ]
    return choices


def _problem_from_row(row: dict[str, Any], source_type: str, source_name: str) -> dict[str, Any] | None:
    stem = _first(row, "stem")
    title = _first(row, "title")
    if not stem and not title:
        return None
    return {
        "source_type": source_type,
        "source_name": source_name,
        "number": _first(row, "number"),
        "subject": _first(row, "subject"),
        "unit": _first(row, "unit"),
        "tags": _first(row, "tags"),
        "title": title or (stem[:40] + ("..." if len(stem) > 40 else "")),
        "stem": stem,
        "choices": _choices_from_row(row),
        "answer": _first(row, "answer"),
        "explanation": _first(row, "explanation"),
    }


def import_csv(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    save_upload(filename, payload)
    text = payload.decode("utf-8-sig", errors="replace")
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample) if "," in sample or "\t" in sample else csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    created: list[dict[str, Any]] = []
    for row in reader:
        problem_data = _problem_from_row(row, "csv", filename)
        if problem_data:
            created.append(storage.create_problem({**metadata, **problem_data}))
    return {"created": created, "notices": [f"{len(created)}개 문항을 가져왔습니다."]}


def _sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [row[0] for row in rows]


def import_sqlite(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    rel_path = save_upload(filename, payload)
    src = storage.DATA_DIR / rel_path
    temp = storage.DATA_DIR / f"tmp_{uuid.uuid4().hex}.sqlite3"
    shutil.copyfile(src, temp)
    created: list[dict[str, Any]] = []
    notices: list[str] = []
    try:
        conn = sqlite3.connect(temp)
        conn.row_factory = sqlite3.Row
        for table in _sqlite_tables(conn):
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            lower_columns = {column.lower() for column in columns}
            has_text = any(alias.lower() in lower_columns for alias in FIELD_ALIASES["stem"])
            has_title = any(alias.lower() in lower_columns for alias in FIELD_ALIASES["title"])
            if not has_text and not has_title:
                continue
            rows = conn.execute(f"SELECT * FROM {table} LIMIT 1000").fetchall()
            for row in rows:
                problem_data = _problem_from_row(dict(row), "sqlite", f"{filename}:{table}")
                if problem_data:
                    created.append(storage.create_problem({**metadata, **problem_data}))
            notices.append(f"{table}: {len(rows)}행 확인")
    finally:
        try:
            conn.close()  # type: ignore[name-defined]
        except Exception:
            pass
        temp.unlink(missing_ok=True)
    if not created:
        notices.append("가져올 수 있는 question/stem/body/title 컬럼을 찾지 못했습니다.")
    return {"created": created, "notices": notices}


QUESTION_LINE_RE = re.compile(r"^\s*(?:문제\s*)?(\d{1,3})\s*[\.\)]")


def _save_image_bytes(name: str, payload: bytes) -> str | None:
    """이미지 바이트를 업로드 폴더에 저장하고 상대 경로를 돌려준다. 유효하지 않으면 None."""
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
    except Exception:
        return None
    return save_upload(name, payload)


def _paragraphs_to_chunks(paragraphs: list[tuple[str, list[str]]]) -> list[dict[str, Any]]:
    """(문단 텍스트, 이미지 경로들) 목록을 문항 번호 기준으로 묶는다."""
    chunks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for text, images in paragraphs:
        if QUESTION_LINE_RE.match(text):
            current = {"text": [text], "images": list(images)}
            chunks.append(current)
            continue
        if current is None:
            current = {"text": [text] if text else [], "images": list(images)}
            chunks.append(current)
            continue
        if text:
            current["text"].append(text)
        current["images"].extend(images)
    result = []
    for chunk in chunks:
        body = _clean_text("\n".join(chunk["text"]))
        if body or chunk["images"]:
            result.append({"text": body, "images": chunk["images"]})
    return result


def _create_from_chunks(
    chunks: list[dict[str, Any]],
    source_type: str,
    filename: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    has_numbers = len(chunks) > 1
    for sequence, chunk in enumerate(chunks, start=1):
        text = chunk["text"]
        number = _extract_number(text, sequence) if has_numbers else ""
        title = f"{Path(filename).stem} #{number}" if number else Path(filename).stem
        created.append(
            storage.create_problem(
                {
                    **metadata,
                    "source_type": source_type,
                    "source_name": filename,
                    "number": number,
                    "title": title,
                    "stem": text,
                    "image_paths": chunk["images"],
                }
            )
        )
    return created


def import_docx(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    from docx import Document as DocxDocument

    save_upload(filename, payload)
    notices: list[str] = []
    try:
        document = DocxDocument(io.BytesIO(payload))
    except Exception as exc:
        return {"created": [], "notices": [f"DOCX를 열 수 없습니다: {exc}"]}

    blip_ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
    embed_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    paragraphs: list[tuple[str, list[str]]] = []
    image_count = 0
    for para in document.paragraphs:
        images: list[str] = []
        for blip in para._p.iter(blip_ns):
            rel_id = blip.get(embed_attr)
            try:
                part = document.part.rels[rel_id].target_part if rel_id in document.part.rels else None
                if part is None:
                    continue
                rel_path = _save_image_bytes(Path(part.partname).name, part.blob)
            except Exception:
                continue
            if rel_path:
                images.append(rel_path)
                image_count += 1
        paragraphs.append((para.text.strip(), images))
    # 표 안의 텍스트도 본문 뒤에 덧붙인다.
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            line = " | ".join(part for part in cells if part)
            if line:
                paragraphs.append((line, []))

    chunks = _paragraphs_to_chunks(paragraphs)
    if not chunks:
        return {"created": [], "notices": ["DOCX에서 내용을 찾지 못했습니다."]}
    created = _create_from_chunks(chunks, "docx", filename, metadata)
    if image_count:
        notices.append(f"이미지 {image_count}개를 함께 가져왔습니다.")
    return {"created": created, "notices": notices}


def _local_name(element: Any) -> str:
    tag = element.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _hwpx_manifest_map(archive: zipfile.ZipFile) -> dict[str, str]:
    """content.hpf의 item id → zip 내 실제 경로 매핑."""
    mapping: dict[str, str] = {}
    names = set(archive.namelist())
    try:
        root = etree.fromstring(archive.read("Contents/content.hpf"))
    except Exception:
        return mapping
    for item in root.iter():
        if _local_name(item) != "item":
            continue
        item_id, href = item.get("id"), item.get("href")
        if not item_id or not href:
            continue
        candidates = [href, f"Contents/{href}", href.removeprefix("../"), f"BinData/{Path(href).name}"]
        for candidate in candidates:
            if candidate in names:
                mapping[item_id] = candidate
                break
    return mapping


def import_hwpx(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    save_upload(filename, payload)
    notices: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except Exception as exc:
        return {"created": [], "notices": [f"HWPX를 열 수 없습니다(zip 아님): {exc}"]}

    with archive:
        names = archive.namelist()
        sections = sorted(name for name in names if re.fullmatch(r"Contents/section\d+\.xml", name))
        if not sections:
            return {"created": [], "notices": ["HWPX 안에서 section XML을 찾지 못했습니다."]}
        bin_map = _hwpx_manifest_map(archive)
        saved_bins: dict[str, str | None] = {}
        paragraphs: list[tuple[str, list[str]]] = []
        image_count = 0
        for section_name in sections:
            try:
                root = etree.fromstring(archive.read(section_name))
            except Exception as exc:
                notices.append(f"{section_name} 분석 실패: {exc}")
                continue
            for para in root.iter():
                if _local_name(para) != "p":
                    continue
                texts: list[str] = []
                images: list[str] = []
                for node in para.iter():
                    name = _local_name(node)
                    if name == "t" and node.text:
                        texts.append(node.text)
                    elif name == "img":
                        ref = node.get("binaryItemIDRef") or node.get("binaryItemIDRef".lower()) or ""
                        if ref not in saved_bins:
                            zip_path = bin_map.get(ref)
                            if zip_path is None:
                                # 매니페스트에 없으면 BinData에서 같은 이름을 추정
                                guess = [n for n in names if n.startswith("BinData/") and Path(n).stem == ref]
                                zip_path = guess[0] if guess else None
                            saved_bins[ref] = (
                                _save_image_bytes(Path(zip_path).name, archive.read(zip_path)) if zip_path else None
                            )
                        if saved_bins[ref]:
                            images.append(saved_bins[ref])
                            image_count += 1
                paragraphs.append((" ".join(texts).strip(), images))

    chunks = _paragraphs_to_chunks(paragraphs)
    if not chunks:
        return {"created": [], "notices": ["HWPX에서 내용을 찾지 못했습니다."]}
    created = _create_from_chunks(chunks, "hwpx", filename, metadata)
    if image_count:
        notices.append(f"이미지 {image_count}개를 함께 가져왔습니다.")
    return {"created": created, "notices": notices}


# --- HWP(5.0 바이너리) 텍스트 추출 -------------------------------------------
# 문단 텍스트(HWPTAG_PARA_TEXT) 레코드의 UTF-16LE 문자열에서 컨트롤 문자를 걸러낸다.
# 코드 1~9, 11~12, 14~23은 8 WCHAR(16바이트)짜리 인라인/확장 컨트롤이다.
_HWP_EXTENDED = {1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
HWPTAG_PARA_TEXT = 67


def _hwp_decode_text(data: bytes) -> str:
    out: list[str] = []
    i = 0
    length = len(data) - 1
    while i < length:
        code = data[i] | (data[i + 1] << 8)
        if code == 9:
            out.append("\t")
            i += 16
        elif code in _HWP_EXTENDED:
            i += 16
        elif code in (10, 13):
            out.append("\n")
            i += 2
        elif code < 32:
            i += 2
        else:
            out.append(chr(code))
            i += 2
    return "".join(out)


def _hwp_iter_records(stream: bytes):
    pos = 0
    size_total = len(stream)
    while pos + 4 <= size_total:
        (header,) = struct.unpack_from("<I", stream, pos)
        tag = header & 0x3FF
        size = (header >> 20) & 0xFFF
        pos += 4
        if size == 0xFFF:
            if pos + 4 > size_total:
                break
            (size,) = struct.unpack_from("<I", stream, pos)
            pos += 4
        if pos + size > size_total:
            break
        yield tag, stream[pos : pos + size]
        pos += size


def import_hwp(filename: str, payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    import olefile

    save_upload(filename, payload)
    notices: list[str] = []
    try:
        ole = olefile.OleFileIO(io.BytesIO(payload))
    except Exception as exc:
        return {"created": [], "notices": [f"HWP 파일이 아닙니다: {exc}"]}

    with ole:
        if not ole.exists("FileHeader"):
            return {"created": [], "notices": ["HWP FileHeader가 없습니다. 한글 5.0 형식이 아닙니다."]}
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0] if len(header) >= 40 else 0
        compressed = bool(flags & 0x1)
        if flags & 0x2:
            return {"created": [], "notices": ["암호가 걸린 HWP는 가져올 수 없습니다."]}

        # 본문 텍스트 1순위: rhwp 엔진 (설치된 경우)
        paragraphs: list[tuple[str, list[str]]] = []
        if rhwp is not None:
            try:
                doc = rhwp.Document.from_bytes(payload)
                for para_text in doc.paragraphs():
                    for line in para_text.splitlines() or [""]:
                        paragraphs.append((line.strip(), []))
            except Exception:
                paragraphs = []

        # 2순위: BodyText/Section* 레코드 직접 파싱
        if not any(text for text, _ in paragraphs):
            paragraphs = []
            section_names = sorted(
                (entry for entry in ole.listdir() if len(entry) == 2 and entry[0] == "BodyText"),
                key=lambda entry: int(re.sub(r"\D", "", entry[1]) or 0),
            )
            for entry in section_names:
                raw = ole.openstream(entry).read()
                if compressed:
                    try:
                        raw = zlib.decompress(raw, -15)
                    except Exception as exc:
                        notices.append(f"{'/'.join(entry)} 압축 해제 실패: {exc}")
                        continue
                for tag, record in _hwp_iter_records(raw):
                    if tag != HWPTAG_PARA_TEXT:
                        continue
                    text = _hwp_decode_text(record)
                    for line in text.split("\n"):
                        paragraphs.append((line.strip(), []))

        # PrvText 보조: 본문 파싱이 실패했을 때 미리보기 텍스트라도 사용
        if not any(text for text, _ in paragraphs) and ole.exists("PrvText"):
            preview = ole.openstream("PrvText").read().decode("utf-16-le", errors="ignore")
            paragraphs = [(line.strip(), []) for line in preview.splitlines()]
            notices.append("본문 레코드 대신 미리보기 텍스트를 사용했습니다.")

        # 첨부 이미지: BinData 스토리지 전체 추출
        images: list[str] = []
        for entry in ole.listdir():
            if len(entry) != 2 or entry[0] != "BinData":
                continue
            blob = ole.openstream(entry).read()
            if compressed:
                try:
                    blob = zlib.decompress(blob, -15)
                except Exception:
                    pass
            rel_path = _save_image_bytes(entry[1], blob)
            if rel_path:
                images.append(rel_path)

    chunks = _paragraphs_to_chunks(paragraphs)
    if not chunks:
        return {"created": [], "notices": ["HWP에서 텍스트를 추출하지 못했습니다.", *notices]}
    if images:
        chunks[0]["images"] = [*images, *chunks[0]["images"]]
        notices.append(f"이미지 {len(images)}개는 위치를 알 수 없어 첫 문항에 첨부했습니다.")
    created = _create_from_chunks(chunks, "hwp", filename, metadata)
    return {"created": created, "notices": notices}

