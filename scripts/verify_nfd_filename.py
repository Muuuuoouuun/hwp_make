# -*- coding: utf-8 -*-
"""macOS 자모 분해형(NFD) 한글 파일명 보존 회귀 핀 (2026-10-07).

macOS 는 한글 파일명을 NFD 로 보내 '가-힣' 허용 목록에서 전부 '_' 로 깨졌다.
업로드 payload 와 파일명 정리 함수 세 곳이 NFC 로 합치는지 확인한다.
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import importers, main  # noqa: E402

nfd = unicodedata.normalize("NFD", "국어 시험.pdf")
assert nfd != "국어 시험.pdf"

assert importers.safe_filename(nfd) == "국어 시험.pdf", importers.safe_filename(nfd)
assert main._safe_path_name(nfd) == "국어 시험.pdf", main._safe_path_name(nfd)
assert main._safe_export_name(nfd, "hwpx").endswith("_국어 시험.pdf.hwpx")
assert main.ImportPayload(kind="pdf", filename=nfd, data_base64="AA==").filename == "국어 시험.pdf"
print("NFD_FILENAME_OK")
