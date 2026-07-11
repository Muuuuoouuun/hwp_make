# SPDX-License-Identifier: Apache-2.0
"""Embedded templates and sample payloads for HWPX documents."""

from __future__ import annotations

import io
import zipfile
from functools import lru_cache
from importlib import resources
from pathlib import Path


_COMPAT_NAMESPACES = {
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hhs": "http://www.hancom.co.kr/hwpml/2011/history",
    "hm": "http://www.hancom.co.kr/hwpml/2011/master-page",
    "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "opf": "http://www.idpf.org/2007/opf/",
    "ooxmlchart": "http://www.hancom.co.kr/hwpml/2016/ooxmlchart",
    "hwpunitchar": "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar",
    "epub": "http://www.idpf.org/2007/ops",
    "config": "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
}


def _xml_declaration(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body
    ).encode("utf-8")


def _generated_fontfaces() -> str:
    faces = []
    for lang in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER"):
        faces.append(
            f"""
      <hh:fontface lang="{lang}" fontCnt="4">
        <hh:font id="0" face="HYSinMyeongJo-Medium" type="TTF" isEmbedded="0"><hh:typeInfo familyType="FCAT_MYEONGJO" weight="4" proportion="4" contrast="0" strokeVariation="1" armStyle="1" letterform="1" midline="1" xHeight="1"/></hh:font>
        <hh:font id="1" face="Times New Roman" type="TTF" isEmbedded="0"><hh:typeInfo familyType="FCAT_ROMAN" weight="4" proportion="4" contrast="0" strokeVariation="1" armStyle="1" letterform="1" midline="1" xHeight="1"/></hh:font>
        <hh:font id="2" face="HYGothic-Medium" type="TTF" isEmbedded="0"><hh:typeInfo familyType="FCAT_GOTHIC" weight="6" proportion="4" contrast="0" strokeVariation="1" armStyle="1" letterform="1" midline="1" xHeight="1"/></hh:font>
        <hh:font id="3" face="HancomEQN" type="TTF" isEmbedded="0"><hh:typeInfo familyType="FCAT_GOTHIC" weight="4" proportion="4" contrast="0" strokeVariation="1" armStyle="1" letterform="1" midline="1" xHeight="1"/></hh:font>
      </hh:fontface>""".strip()
        )
    return "\n".join(faces)


def _generated_header_xml() -> bytes:
    ns_attrs = " ".join(f'xmlns:{key}="{value}"' for key, value in _COMPAT_NAMESPACES.items())
    metrics = (
        'hangul="100" latin="100" hanja="100" japanese="100" '
        'other="100" symbol="100" user="100"'
    )
    zero_metrics = (
        'hangul="0" latin="0" hanja="0" japanese="0" '
        'other="0" symbol="0" user="0"'
    )
    body = f"""
<hh:head {ns_attrs} version="1.5" secCnt="1">
  <hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>
  <hh:refList>
    <hh:fontfaces itemCnt="7">
{_generated_fontfaces()}
    </hh:fontfaces>
    <hh:borderFills itemCnt="1">
      <hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">
        <hh:slash type="NONE" Crooked="0" isCounter="0"/>
        <hh:backSlash type="NONE" Crooked="0" isCounter="0"/>
        <hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>
        <hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>
      </hh:borderFill>
    </hh:borderFills>
    <hh:charProperties itemCnt="1">
      <hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio {metrics}/>
        <hh:spacing {zero_metrics}/>
        <hh:relSz {metrics}/>
        <hh:offset {zero_metrics}/>
        <hh:underline type="NONE" shape="SOLID" color="#000000"/>
      </hh:charPr>
    </hh:charProperties>
    <hh:tabProperties itemCnt="0"/>
    <hh:numberings itemCnt="0"/>
    <hh:bullets itemCnt="0"/>
    <hh:paraProperties itemCnt="1">
      <hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="LEFT" vertical="BASELINE"/>
        <hh:margin>
          <hh:intent value="0" unit="HWPUNIT"/>
          <hh:left value="0" unit="HWPUNIT"/>
          <hh:right value="0" unit="HWPUNIT"/>
          <hh:prev value="0" unit="HWPUNIT"/>
          <hh:next value="0" unit="HWPUNIT"/>
        </hh:margin>
        <hh:lineSpacing type="PERCENT" value="160" unit="PERCENT"/>
        <hh:border borderFillIDRef="0" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
      </hh:paraPr>
    </hh:paraProperties>
    <hh:styles itemCnt="1">
      <hh:style id="0" type="PARA" name="Normal" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/>
    </hh:styles>
    <hh:memoProperties itemCnt="0"/>
    <hh:trackChanges itemCnt="0"/>
    <hh:trackChangeAuthors itemCnt="0"/>
    <hh:forbiddenWordList itemCnt="0"/>
    <hh:binDataList itemCnt="0"/>
  </hh:refList>
  <hh:compatibleDocument targetProgram="HWP2018">
    <hh:layoutCompatibility/>
  </hh:compatibleDocument>
  <hh:docOption><hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/></hh:docOption>
  <hh:metaTag>{{"name":""}}</hh:metaTag>
  <hh:trackchageConfig flags="56"/>
</hh:head>""".strip()
    return _xml_declaration(body)


def _generated_section_xml() -> bytes:
    ns_attrs = " ".join(f'xmlns:{key}="{value}"' for key, value in _COMPAT_NAMESPACES.items())
    body = f"""
<hs:sec {ns_attrs}>
  <hp:p id="1" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="0">
      <hp:t></hp:t>
      <hp:secPr>
        <hp:pagePr landscape="PORTRAIT" width="59528" height="84188" gutterType="LEFT_ONLY">
          <hp:margin left="8504" right="8504" top="5669" bottom="4252" header="0" footer="0" gutter="0"/>
        </hp:pagePr>
        <hp:startNum pageStartsOn="BOTH" page="1" pic="1" tbl="1" equation="1"/>
      </hp:secPr>
    </hp:run>
    <hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000" textheight="1000" baseline="850" spacing="150" horzpos="0" horzsize="42520" flags="393216"/></hp:linesegarray>
  </hp:p>
</hs:sec>""".strip()
    return _xml_declaration(body)


def _generated_blank_document_bytes() -> bytes:
    """Create a minimal editor-open-safe HWPX package.

    The upstream package normally ships ``Skeleton.hwpx`` as binary data. Some
    local/vendor installs omit that asset, so keep a deterministic generated
    fallback that the public writer APIs can extend.
    """

    container = _xml_declaration(
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
        '<rootfiles><rootfile full-path="Contents/content.hpf" '
        'media-type="application/hwpml-package+xml"/></rootfiles></container>'
    )
    version = _xml_declaration(
        '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" '
        'tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="1" '
        'buildNumber="0" xmlVersion="1.5"/>'
    )
    content = _xml_declaration(
        '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" '
        'version="2.0" unique-identifier="uid">'
        '<opf:metadata><dc:identifier xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'id="uid">blank</dc:identifier></opf:metadata>'
        '<opf:manifest>'
        '<opf:item id="version" href="version.xml" media-type="application/xml" properties="version"/>'
        '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
        '</opf:manifest>'
        '<opf:spine><opf:itemref idref="header" linear="no"/>'
        '<opf:itemref idref="section0" linear="yes"/></opf:spine>'
        '</opf:package>'
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        archive.writestr(mimetype, "application/hwp+zip")
        for name, payload in (
            ("META-INF/container.xml", container),
            ("version.xml", version),
            ("Contents/content.hpf", content),
            ("Contents/header.xml", _generated_header_xml()),
            ("Contents/section0.xml", _generated_section_xml()),
        ):
            archive.writestr(name, payload, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


@lru_cache(maxsize=None)
def blank_document_bytes() -> bytes:
    """Return the binary payload for a minimal blank HWPX document."""

    # Prefer a packaged asset when available.
    try:
        data_pkg = resources.files("hwpx.data")
    except (ModuleNotFoundError, AttributeError):  # pragma: no cover - optional dependency
        data_pkg = None
    if data_pkg is not None:
        skeleton = data_pkg / "Skeleton.hwpx"
        if skeleton.is_file():  # type: ignore[call-arg]
            with skeleton.open("rb") as stream:  # type: ignore[call-arg]
                return stream.read()

    # Fall back to the repository examples folder during development.
    root = Path(__file__).resolve().parent.parent.parent
    fallback = root / "examples" / "Skeleton.hwpx"
    if fallback.is_file():
        return fallback.read_bytes()

    return _generated_blank_document_bytes()
