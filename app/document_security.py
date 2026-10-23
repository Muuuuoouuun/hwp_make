"""Shared limits for untrusted DOCX/HWPX packages in local and web imports."""

from __future__ import annotations

import stat
import zipfile
from pathlib import PurePosixPath

from lxml import etree

MAX_ARCHIVE_ENTRIES = 5000
MAX_ARCHIVE_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1000


class DocumentSecurityError(ValueError):
    def __init__(self, message: str, *, too_large: bool = False):
        self.too_large = too_large
        super().__init__(message)


def validate_archive(archive: zipfile.ZipFile) -> None:
    """Check metadata before any parser expands members or follows references."""
    entries = archive.infolist()
    if (len(entries) > MAX_ARCHIVE_ENTRIES
            or sum(item.file_size for item in entries) > MAX_ARCHIVE_EXPANDED_BYTES):
        raise DocumentSecurityError("문서 압축 해제 크기가 허용 범위를 초과합니다.", too_large=True)
    seen: set[str] = set()
    for item in entries:
        name = item.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if (not name or "\x00" in item.orig_filename or path.is_absolute()
                or ".." in path.parts or (path.parts and ":" in path.parts[0])
                or path.as_posix() in seen or stat.S_ISLNK(item.external_attr >> 16)):
            raise DocumentSecurityError("문서에 안전하지 않거나 중복된 내부 경로가 있습니다.")
        seen.add(path.as_posix())
        if item.flag_bits & 1:
            raise DocumentSecurityError("암호화된 문서는 암호를 해제한 뒤 가져와 주세요.")
        if item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise DocumentSecurityError("지원하지 않는 문서 압축 방식입니다.")
        if (item.file_size > MAX_MEMBER_BYTES
                or (item.file_size and (item.compress_size <= 0
                    or item.file_size > MAX_COMPRESSION_RATIO * item.compress_size))):
            raise DocumentSecurityError("문서 내부 파일의 압축 해제 크기가 너무 큽니다.", too_large=True)


def parse_document_xml(payload: bytes):
    """Never expand entities or access files/network while parsing source XML."""
    if len(payload) > MAX_MEMBER_BYTES:
        raise DocumentSecurityError("문서 XML 크기가 허용 범위를 초과합니다.", too_large=True)
    root = etree.fromstring(payload, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False,
    ))
    if root.getroottree().docinfo.doctype:
        raise DocumentSecurityError("문서 XML의 외부 정의·엔터티는 지원하지 않습니다.")
    return root
