from __future__ import annotations

import html
import mimetypes
import re
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from .exam_templates import ExamTemplate, get_template, resolve_export_title
from . import storage


SECTION_NS = "http://www.hancom.co.kr/hwpml/2011/section"
PARA_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HEAD_NS = "http://www.hancom.co.kr/hwpml/2011/head"
CORE_NS = "http://www.hancom.co.kr/hwpml/2011/core"


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _paragraph(text: str, pid: int, char_pr: int = 0, para_pr: int = 0) -> str:
    text = _esc(text)
    if not text:
        text = " "
    return f"""  <hp:p id="{pid}" paraPrIDRef="{para_pr}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="{char_pr}"><hp:t xml:space="preserve">{text}</hp:t></hp:run>
    <hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000" textheight="1000" baseline="850" spacing="600" horzpos="0" horzsize="42520" flags="393216"/></hp:linesegarray>
  </hp:p>"""


# 본문 폭: 용지 59528 - 좌우 여백 8504*2 (HWPUNIT, 1/7200인치)
MAX_IMAGE_WIDTH = 42520
COLUMN_GAP = 1200
PX_TO_HWPUNIT = 75  # 96dpi 기준: px / 96 * 7200
CIRCLED_NUMBERS = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")
QUESTION_PREFIX_RE = re.compile(r"^\s*(?:문제\s*)?(\d{1,3})\s*[\.\)]\s*")
CHOICE_PREFIX_RE = re.compile(r"^\s*(?:[①②③④⑤⑥⑦⑧⑨]|\d+\s*[\.\)])\s*")


def _pic_paragraph(pid: int, item: dict[str, Any], instance: int) -> str:
    """실제 한컴 출력(hwpxlib SimplePicture.hwpx)과 동일한 구조의 인라인 이미지 문단."""
    width, height = item["width"], item["height"]
    return f"""  <hp:p id="{pid}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="0">
      <hp:pic id="{1000000000 + instance}" zOrder="{instance}" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{2000000000 + instance}" reverse="0">
        <hp:offset x="0" y="0"/>
        <hp:orgSz width="{width}" height="{height}"/>
        <hp:curSz width="{width}" height="{height}"/>
        <hp:flip horizontal="0" vertical="0"/>
        <hp:rotationInfo angle="0" centerX="{width // 2}" centerY="{height // 2}" rotateimage="1"/>
        <hp:renderingInfo>
          <hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>
          <hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>
          <hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>
        </hp:renderingInfo>
        <hp:imgRect>
          <hc:pt0 x="0" y="0"/>
          <hc:pt1 x="{width}" y="0"/>
          <hc:pt2 x="{width}" y="{height}"/>
          <hc:pt3 x="0" y="{height}"/>
        </hp:imgRect>
        <hp:imgClip left="0" right="{width}" top="0" bottom="{height}"/>
        <hp:inMargin left="0" right="0" top="0" bottom="0"/>
        <hp:imgDim dimwidth="{width}" dimheight="{height}"/>
        <hc:img binaryItemIDRef="{item['id']}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>
        <hp:effects/>
        <hp:sz width="{width}" widthRelTo="ABSOLUTE" height="{height}" heightRelTo="ABSOLUTE" protect="0"/>
        <hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>
        <hp:outMargin left="0" right="0" top="0" bottom="0"/>
        <hp:shapeComment/>
      </hp:pic>
      <hp:t/>
    </hp:run>
    <hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="{height}" textheight="{height}" baseline="{int(height * 0.85)}" spacing="600" horzpos="0" horzsize="42520" flags="393216"/></hp:linesegarray>
  </hp:p>"""


def _strip_question_prefix(text: str, label: str) -> str:
    match = QUESTION_PREFIX_RE.match(text)
    if match and match.group(1) == str(label):
        return text[match.end() :].lstrip()
    return text


def _choice_label(index: int, template: ExamTemplate) -> str:
    if template.circled_choices and index <= len(CIRCLED_NUMBERS):
        return CIRCLED_NUMBERS[index - 1]
    return f"{index})"


def _format_choice(index: int, choice: str, template: ExamTemplate) -> str:
    clean = CHOICE_PREFIX_RE.sub("", choice or "").strip()
    return f"{_choice_label(index, template)} {clean}".rstrip()


def _add_masthead(add_text, title: str, template: ExamTemplate) -> None:
    if template.key == "basic":
        add_text(title, 1, 1)
        add_text("")
        return

    add_text(template.masthead_title or title, 1, 1)
    meta = "   ".join(
        part for part in (template.area, template.period, template.variant) if part
    )
    if meta:
        add_text(meta, 3, 1)
    if template.show_student_fields:
        add_text("성명 ____________     수험 번호 ____________     " + template.selection, 4, 1)
    elif template.selection:
        add_text(template.selection, 4, 1)
    for direction in template.directions:
        add_text(direction, 4, 0)
    add_text("")


def _build_body(
    title: str,
    problems: list[dict[str, Any]],
    image_items: dict[str, dict[str, Any]],
    template: ExamTemplate,
) -> str:
    paragraphs: list[str] = []
    pid = 0
    instance = 0

    def add_text(text: str, char_pr: int = 0, para_pr: int = 0) -> None:
        nonlocal pid
        pid += 1
        paragraphs.append(_paragraph(text, pid, char_pr, para_pr))

    def add_image(image_path: str) -> None:
        nonlocal pid, instance
        item = image_items.get(image_path)
        if item is None:
            add_text(f"[첨부 이미지: {Path(image_path).name}]")
            return
        pid += 1
        instance += 1
        paragraphs.append(_pic_paragraph(pid, item, instance))

    _add_masthead(add_text, title, template)
    for index, problem in enumerate(problems, start=1):
        label = problem.get("number") or str(index)
        subject = problem.get("subject") or ""
        unit = problem.get("unit") or ""
        meta = " / ".join(part for part in [subject, unit] if part)

        stem_lines = (problem.get("stem") or "").splitlines()
        if template.merge_question_number:
            first_line = _strip_question_prefix(stem_lines[0], label) if stem_lines else ""
            heading = f"{label}. {first_line or problem.get('title') or '문제'}"
            add_text(heading, 2, 3 if template.compact else 0)
            for line in stem_lines[1:]:
                add_text(line, 0, 3 if template.compact else 0)
            if meta:
                add_text(f"[{meta}]", 4, 3 if template.compact else 0)
        else:
            heading = f"{label}. {problem.get('title') or '문제'}"
            if meta:
                heading += f" [{meta}]"
            add_text(heading, 2, 0)
            for line in stem_lines or [""]:
                add_text(line)

        for image_path in problem.get("image_paths") or []:
            add_image(image_path)

        choices = [
            _format_choice(choice_index, choice, template)
            for choice_index, choice in enumerate(problem.get("choices") or [], start=1)
        ]
        if choices and template.inline_short_choices and sum(len(choice) for choice in choices) <= 90:
            add_text("    ".join(choices), 0, 3 if template.compact else 0)
        else:
            for choice in choices:
                add_text(choice, 0, 3 if template.compact else 0)

        if template.include_answers and problem.get("answer"):
            add_text(f"정답: {problem['answer']}")
        if template.include_explanations and problem.get("explanation"):
            add_text(f"해설: {problem['explanation']}")
        add_text("")
    return "\n".join(paragraphs)


def _header_xml(title: str) -> str:
    # 실제 한컴 출력 기준으로 이미지(BinData)는 content.hpf 매니페스트에만 등록한다.
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hh:head xmlns:hh="{HEAD_NS}" xmlns:hc="{CORE_NS}" version="1.0">
  <hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>
  <hh:refList>
    <hh:fontfaces itemCnt="7">
      <hh:fontface lang="KO" fontCnt="1"><hh:font id="0" face="맑은 고딕" type="TTF"/></hh:fontface>
      <hh:fontface lang="EN" fontCnt="1"><hh:font id="0" face="Arial" type="TTF"/></hh:fontface>
      <hh:fontface lang="CN" fontCnt="1"><hh:font id="0" face="SimSun" type="TTF"/></hh:fontface>
      <hh:fontface lang="JP" fontCnt="1"><hh:font id="0" face="Yu Gothic" type="TTF"/></hh:fontface>
      <hh:fontface lang="OTHER" fontCnt="1"><hh:font id="0" face="Arial" type="TTF"/></hh:fontface>
      <hh:fontface lang="SYMBOL" fontCnt="1"><hh:font id="0" face="Symbol" type="TTF"/></hh:fontface>
      <hh:fontface lang="USER" fontCnt="1"><hh:font id="0" face="Arial" type="TTF"/></hh:fontface>
    </hh:fontfaces>
    <hh:borderFills itemCnt="1">
      <hh:borderFill id="0" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">
        <hh:slash type="NONE" Crooked="0" isCounter="0"/>
        <hh:backSlash type="NONE" Crooked="0" isCounter="0"/>
        <hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:topBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/>
        <hh:diagonal type="NONE" width="0.1 mm" color="#000000"/>
        <hh:fillBrush><hc:winBrush faceColor="#FFFFFF" hatchColor="#000000" alpha="0"/></hh:fillBrush>
      </hh:borderFill>
    </hh:borderFills>
    <hh:charProperties itemCnt="5">
      <hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
      <hh:charPr id="1" height="1600" textColor="#111111" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
      <hh:charPr id="2" height="1150" textColor="#111111" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
      <hh:charPr id="3" height="1250" textColor="#111111" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
      <hh:charPr id="4" height="900" textColor="#333333" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
      </hh:charPr>
    </hh:charProperties>
    <hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="1" autoTabRight="1"/></hh:tabProperties>
    <hh:numberings itemCnt="1"><hh:numbering id="1" start="1"/></hh:numberings>
    <hh:paraProperties itemCnt="4">
      <hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="LEFT" vertical="BASELINE"/>
        <hh:heading type="NONE" idRef="0" level="0"/>
        <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>
        <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
        <hh:border borderFillIDRef="0" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
        <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>
        <hh:margin><hc:intent value="0"/><hc:left value="0"/><hc:right value="0"/><hc:prev value="0"/><hc:next value="0"/></hh:margin>
      </hh:paraPr>
      <hh:paraPr id="1" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="CENTER" vertical="BASELINE"/>
        <hh:heading type="NONE" idRef="0" level="0"/>
        <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>
        <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
        <hh:border borderFillIDRef="0" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
        <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>
        <hh:margin><hc:intent value="0"/><hc:left value="0"/><hc:right value="0"/><hc:prev value="0"/><hc:next value="0"/></hh:margin>
      </hh:paraPr>
      <hh:paraPr id="2" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="RIGHT" vertical="BASELINE"/>
        <hh:heading type="NONE" idRef="0" level="0"/>
        <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>
        <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
        <hh:border borderFillIDRef="0" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
        <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>
        <hh:margin><hc:intent value="0"/><hc:left value="0"/><hc:right value="0"/><hc:prev value="0"/><hc:next value="0"/></hh:margin>
      </hh:paraPr>
      <hh:paraPr id="3" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="LEFT" vertical="BASELINE"/>
        <hh:heading type="NONE" idRef="0" level="0"/>
        <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>
        <hh:lineSpacing type="PERCENT" value="125" unit="HWPUNIT"/>
        <hh:border borderFillIDRef="0" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
        <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>
        <hh:margin><hc:intent value="0"/><hc:left value="0"/><hc:right value="0"/><hc:prev value="0"/><hc:next value="0"/></hh:margin>
      </hh:paraPr>
    </hh:paraProperties>
    <hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles>
  </hh:refList>
  <hh:docOption><hh:linkinfo path=""/></hh:docOption>
  <hh:trackchagesConfig flags="0"/>
</hh:head>"""


def _section_xml(
    title: str,
    problems: list[dict[str, Any]],
    image_items: dict[str, dict[str, Any]],
    template: ExamTemplate,
) -> str:
    body = _build_body(title, problems, image_items, template)
    columns = max(1, min(template.columns, 2))
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hs:sec xmlns:hs="{SECTION_NS}" xmlns:hp="{PARA_NS}" xmlns:hc="{CORE_NS}" xmlns:hh="{HEAD_NS}">
  <hp:secPr id="0" textDirection="HORIZONTAL" spaceColumns="{columns - 1}" tabStop="8000" tabStopVal="80">
    <hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>
    <hp:startNum pageStartsOn="BOTH" page="1" pic="1" tbl="1" equation="1"/>
    <hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>
    <hp:pagePr landscape="0" width="59528" height="84188" gutterType="LEFT_ONLY">
      <hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/>
    </hp:pagePr>
    <hp:colPr type="NEWSPAPER" layout="LEFT" colCount="{columns}" sameSz="1" sameGap="1200"/>
  </hp:secPr>
{body}
</hs:sec>"""


def _content_hpf(title: str, image_items: dict[str, dict[str, Any]]) -> str:
    lines = "\n".join(
        f'    <opf:item id="{item["id"]}" href="BinData/{_esc(item["name"])}" media-type="{_esc(item["media"])}" isEmbeded="1"/>'
        for item in image_items.values()
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version="1.0" unique-identifier="uid">
  <opf:metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{_esc(title or "문항 모음")}</dc:title>
    <dc:creator>HWP Make</dc:creator>
    <dc:language>ko-KR</dc:language>
  </opf:metadata>
  <opf:manifest>
    <opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>
    <opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>
{lines}
  </opf:manifest>
  <opf:spine>
    <opf:itemref idref="section0"/>
  </opf:spine>
</opf:package>"""


def _container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>
  </rootfiles>
</container>"""


def _manifest_xml(image_items: dict[str, dict[str, Any]]) -> str:
    entries = [
        '  <manifest:file-entry manifest:media-type="application/hwp+zip" manifest:full-path="/"/>',
        '  <manifest:file-entry manifest:media-type="application/xml" manifest:full-path="Contents/content.hpf"/>',
        '  <manifest:file-entry manifest:media-type="application/xml" manifest:full-path="Contents/header.xml"/>',
        '  <manifest:file-entry manifest:media-type="application/xml" manifest:full-path="Contents/section0.xml"/>',
    ]
    for item in image_items.values():
        entries.append(
            f'  <manifest:file-entry manifest:media-type="{_esc(item["media"])}" manifest:full-path="BinData/{_esc(item["name"])}"/>'
        )
    return """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest">
""" + "\n".join(entries) + "\n</manifest:manifest>"


def _preview_text(title: str, problems: list[dict[str, Any]]) -> str:
    chunks = [title or "문항 모음", ""]
    for index, problem in enumerate(problems, start=1):
        chunks.append(f"{problem.get('number') or index}. {problem.get('title') or '문제'}")
        chunks.append(problem.get("stem") or "")
        chunks.append("")
    return "\n".join(chunks)


def _collect_image_items(
    problems: list[dict[str, Any]], columns: int = 1
) -> dict[str, dict[str, Any]]:
    """문제들이 참조하는 이미지의 매니페스트 정보(id, 보관 이름, 크기)를 모은다."""
    # 다단 레이아웃에서는 단 폭을 넘으면 안 된다.
    max_width = (MAX_IMAGE_WIDTH - COLUMN_GAP * (columns - 1)) // columns if columns > 1 else MAX_IMAGE_WIDTH
    items: dict[str, dict[str, Any]] = {}
    index = 0
    for problem in problems:
        for image_path in problem.get("image_paths") or []:
            if image_path in items:
                continue
            full_path = storage.DATA_DIR / image_path
            if not full_path.exists():
                continue
            try:
                with Image.open(full_path) as image:
                    px_width, px_height = image.size
            except Exception:
                continue
            width = px_width * PX_TO_HWPUNIT
            height = px_height * PX_TO_HWPUNIT
            if width > max_width:
                height = int(height * max_width / width)
                width = max_width
            index += 1
            extension = full_path.suffix.lower() or ".bin"
            items[image_path] = {
                "id": f"image{index}",
                "name": f"image{index}{extension}",
                "media": mimetypes.guess_type(full_path.name)[0] or "application/octet-stream",
                "width": width,
                "height": height,
            }
    return items


def write_hwpx(
    path: Path,
    title: str,
    problems: list[dict[str, Any]],
    template_key: str = "basic",
) -> None:
    template = get_template(template_key)
    title = resolve_export_title(title, template)
    image_items = _collect_image_items(problems, columns=max(1, min(template.columns, 2)))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", _container_xml())
        archive.writestr("META-INF/manifest.xml", _manifest_xml(image_items))
        archive.writestr("version.xml", '<?xml version="1.0" encoding="UTF-8"?><version app="HWP Make" ver="1.0"/>')
        archive.writestr("Contents/content.hpf", _content_hpf(title, image_items))
        archive.writestr("Contents/header.xml", _header_xml(title))
        archive.writestr("Contents/section0.xml", _section_xml(title, problems, image_items, template))
        archive.writestr("Preview/PrvText.txt", _preview_text(title, problems))
        for image_path, item in image_items.items():
            archive.write(storage.DATA_DIR / image_path, f"BinData/{item['name']}")
