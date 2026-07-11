from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "app" / "_vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
OPF = "http://www.idpf.org/2007/opf/"
HV = "http://www.hancom.co.kr/hwpml/2011/version"

REQUIRED_FONT_FACES = {
    "HYSinMyeongJo-Medium",
    "HYMyeongJo-Extra",
    "HYGraphic-Medium",
    "HYGothic-Medium",
    "HYGothic-Extra",
    "HYHeadLine-Medium",
    "Times New Roman",
    "GulimChe",
    "HCR Batang",
}

PAGE_ORIENTATIONS = {"PORTRAIT", "WIDELY"}
KICE_STANDARD_PAGES_MM = (
    ("A4", 210.0, 297.0),
    ("B4", 257.0, 364.0),
    ("B4_114", 257.0 * 1.14, 364.0 * 1.14),
    ("A3", 297.0, 420.0),
)
PAGE_STANDARD_TOLERANCE_MM = 0.75


def _local_names(element: etree._Element) -> list[str]:
    return [etree.QName(child).localname for child in list(element)]


def _section_names(archive: zipfile.ZipFile) -> list[str]:
    return sorted(
        name
        for name in archive.namelist()
        if name.startswith("Contents/") and Path(name).name.startswith("section") and name.endswith(".xml")
    )


def _section_page_setup(section: etree._Element, ns: dict[str, str]) -> tuple[int, int, str | None] | None:
    page_pr = section.find(".//hp:pagePr", ns)
    if page_pr is not None:
        return (
            int(page_pr.get("width") or 0),
            int(page_pr.get("height") or 0),
            page_pr.get("landscape"),
        )

    page_pr = section.find(".//hs:pagePr", ns)
    page_size = section.find(".//hs:pagePr/hs:pageSz", ns)
    if page_size is not None:
        return (
            int(page_size.get("width") or 0),
            int(page_size.get("height") or 0),
            page_pr.get("landscape") if page_pr is not None else None,
        )
    return None


def _hwp_to_mm(value: int) -> float:
    return float(value) * 25.4 / 7200.0


def _standard_page_name(width: int, height: int) -> str | None:
    width_mm = _hwp_to_mm(width)
    height_mm = _hwp_to_mm(height)
    for name, standard_width_mm, standard_height_mm in KICE_STANDARD_PAGES_MM:
        if (
            abs(width_mm - standard_width_mm) <= PAGE_STANDARD_TOLERANCE_MM
            and abs(height_mm - standard_height_mm) <= PAGE_STANDARD_TOLERANCE_MM
        ):
            return name
        if (
            abs(width_mm - standard_height_mm) <= PAGE_STANDARD_TOLERANCE_MM
            and abs(height_mm - standard_width_mm) <= PAGE_STANDARD_TOLERANCE_MM
        ):
            return name
    return None


def _verify_page_setup(path: Path) -> list[str]:
    issues: list[str] = []
    ns = {"hp": HP, "hs": HS}
    with zipfile.ZipFile(path) as archive:
        for section_name in _section_names(archive):
            section = etree.fromstring(archive.read(section_name))
            setup = _section_page_setup(section, ns)
            if setup is None:
                issues.append(f"{section_name}: missing pagePr/page size")
                continue
            width, height, orientation = setup
            if width <= 0 or height <= 0:
                issues.append(f"{section_name}: invalid page size width={width} height={height}")
            if orientation not in PAGE_ORIENTATIONS:
                issues.append(f"{section_name}: unsupported page orientation {orientation!r}")
            expected_orientation = "WIDELY" if width <= height else "PORTRAIT"
            if orientation != expected_orientation:
                issues.append(
                    f"{section_name}: Hancom orientation mismatch "
                    f"orientation={orientation} expected={expected_orientation} width={width} height={height}"
                )
            if _standard_page_name(width, height) is None:
                issues.append(
                    f"{section_name}: page size is not an exam standard A4/B4/B4_114/A3 "
                    f"(width_mm={_hwp_to_mm(width):.3f} height_mm={_hwp_to_mm(height):.3f})"
                )
    return issues


def _verify_shape_text(path: Path) -> list[str]:
    issues: list[str] = []
    ns = {"hp": HP, "hc": HC}
    with zipfile.ZipFile(path) as archive:
        section_names = _section_names(archive)
        if not section_names:
            return ["missing Contents/section*.xml"]
        for section_name in section_names:
            section = etree.fromstring(archive.read(section_name))
            for rect_index, rect in enumerate(section.findall(".//hp:rect", ns), start=1):
                for attr in ("textWrap", "textFlow", "reverse"):
                    if rect.get(attr) is None:
                        issues.append(f"{section_name}: rect #{rect_index} missing {attr}")
                for point_name in ("pt0", "pt1", "pt2", "pt3"):
                    if rect.find(f"hp:{point_name}", ns) is not None:
                        issues.append(f"{section_name}: rect #{rect_index} uses hp:{point_name}; expected hc:{point_name}")
                    if rect.find(f"hc:{point_name}", ns) is None:
                        issues.append(f"{section_name}: rect #{rect_index} missing hc:{point_name}")
                fill_brush = next(
                    (child for child in rect if etree.QName(child).localname == "fillBrush"),
                    None,
                )
                if fill_brush is not None and etree.QName(fill_brush).namespace != HC:
                    issues.append(f"{section_name}: rect #{rect_index} fillBrush is not in hc namespace")
                if rect.find("hp:shapeComment", ns) is None:
                    issues.append(f"{section_name}: rect #{rect_index} missing shapeComment")
                draw = rect.find("hp:drawText", ns)
                if draw is None:
                    continue
                names = _local_names(rect)
                if "shadow" in names and names.index("drawText") > names.index("shadow"):
                    issues.append(f"{section_name}: rect #{rect_index} has drawText after shadow")
                if "sz" in names and names.index("drawText") > names.index("sz"):
                    issues.append(f"{section_name}: rect #{rect_index} has drawText after shape base")
                line_shape = rect.find("hp:lineShape", ns)
                if line_shape is None:
                    issues.append(f"{section_name}: rect #{rect_index} drawText missing lineShape")
                elif line_shape.get("width") in {None, "", "0"}:
                    issues.append(f"{section_name}: rect #{rect_index} drawText has zero-width lineShape")
                sub = draw.find("hp:subList", ns)
                if sub is None:
                    issues.append(f"{section_name}: rect #{rect_index} drawText missing subList")
                    continue
                if "metaTag" in sub.attrib:
                    issues.append(f"{section_name}: rect #{rect_index} subList uses non-model metaTag attr")
                for attr in ("hasTextRef", "hasNumRef"):
                    if sub.get(attr) not in {"0", "1"}:
                        issues.append(f"{section_name}: rect #{rect_index} subList missing {attr}")
                for attr in ("textWidth", "textHeight"):
                    try:
                        value = int(sub.get(attr) or "0")
                    except ValueError:
                        value = 0
                    if value <= 0:
                        issues.append(f"{section_name}: rect #{rect_index} subList has invalid {attr}")
                for para_index, para in enumerate(sub.findall("hp:p", ns), start=1):
                    if not para.get("id"):
                        issues.append(f"{section_name}: rect #{rect_index} subList p #{para_index} missing id")
                    if para.find("hp:linesegarray/hp:lineseg", ns) is None:
                        issues.append(f"{section_name}: rect #{rect_index} subList p #{para_index} missing lineseg")
            for line_index, line in enumerate(section.findall(".//hp:line", ns), start=1):
                for point_name in ("startPt", "endPt"):
                    if line.find(f"hp:{point_name}", ns) is not None:
                        issues.append(f"{section_name}: line #{line_index} uses hp:{point_name}; expected hc:{point_name}")
                    if line.find(f"hc:{point_name}", ns) is None:
                        issues.append(f"{section_name}: line #{line_index} missing hc:{point_name}")
    return issues


def _verify_hancom_compatibility(path: Path, *, require_pdf_font_faces: bool = True) -> list[str]:
    issues: list[str] = []
    ns = {"hh": HH, "opf": OPF, "hv": HV}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "Contents/header.xml" not in names:
            return ["missing Contents/header.xml"]
        header = etree.fromstring(archive.read("Contents/header.xml"))
        if header.get("version") != "1.5":
            issues.append(f"Contents/header.xml: hh:head version is {header.get('version')!r}, expected '1.5'")
        section_count = len(_section_names(archive))
        if header.get("secCnt") != str(section_count):
            issues.append(
                "Contents/header.xml: hh:head secCnt is "
                f"{header.get('secCnt')!r}, expected {section_count!r}"
            )
        expected_order = ["beginNum", "refList", "compatibleDocument", "docOption", "metaTag", "trackchageConfig"]
        actual_order = _local_names(header)[: len(expected_order)]
        if actual_order != expected_order:
            issues.append(
                "Contents/header.xml: top-level order is "
                f"{actual_order!r}, expected prefix {expected_order!r}"
            )
        compatible = header.find(".//hh:compatibleDocument", ns)
        if compatible is None:
            issues.append("Contents/header.xml: missing hh:compatibleDocument")
        elif compatible.get("targetProgram") != "HWP201X":
            issues.append(
                "Contents/header.xml: hh:compatibleDocument targetProgram is "
                f"{compatible.get('targetProgram')!r}, expected HWP201X"
            )
        elif compatible.find("hh:layoutCompatibility", ns) is None:
            issues.append("Contents/header.xml: missing hh:layoutCompatibility")

        faces = {font.get("face") for font in header.findall(".//hh:font", ns) if font.get("face")}
        missing_faces = sorted(REQUIRED_FONT_FACES - faces)
        if require_pdf_font_faces and missing_faces:
            issues.append("Contents/header.xml: missing PDF font faces: " + ", ".join(missing_faces))

        if "Contents/content.hpf" not in names:
            issues.append("missing Contents/content.hpf")
        else:
            package = etree.fromstring(archive.read("Contents/content.hpf"))
            manifest_items = package.findall(".//opf:item", ns)
            item_hrefs = {str(item.get("href") or "") for item in manifest_items}
            if not any(
                "version" in " ".join(
                    str(item.get(attr) or "").lower()
                    for attr in ("id", "href", "media-type", "properties")
                )
                for item in manifest_items
            ):
                issues.append("Contents/content.hpf: manifest does not reference version.xml")
            if "settings.xml" not in item_hrefs:
                issues.append("Contents/content.hpf: manifest does not reference settings.xml")
            spine_refs = package.findall(".//opf:spine/opf:itemref", ns)
            if not spine_refs:
                issues.append("Contents/content.hpf: missing spine itemrefs")
            elif spine_refs[0].get("idref") != "header" or spine_refs[0].get("linear") != "yes":
                issues.append("Contents/content.hpf: first spine itemref must be header linear=yes")

        if "version.xml" not in names:
            issues.append("missing version.xml")
        else:
            version = etree.fromstring(archive.read("version.xml"))
            if version.tag == f"{{{HV}}}HCFVersion" and version.get("xmlVersion") != "1.5":
                issues.append(f"version.xml: xmlVersion is {version.get('xmlVersion')!r}, expected '1.5'")

        if "Preview/PrvText.txt" not in names:
            issues.append("missing Preview/PrvText.txt")
        elif not archive.read("Preview/PrvText.txt").strip():
            issues.append("Preview/PrvText.txt is empty")
        for required in ("settings.xml", "META-INF/manifest.xml", "META-INF/container.rdf", "Preview/PrvImage.png"):
            if required not in names:
                issues.append(f"missing {required}")
        if "Preview/PrvImage.png" in names and not archive.read("Preview/PrvImage.png").startswith(b"\x89PNG\r\n\x1a\n"):
            issues.append("Preview/PrvImage.png is not a PNG")

        section_required_children = {
            "grid",
            "startNum",
            "visibility",
            "lineNumberShape",
            "pagePr",
            "footNotePr",
            "endNotePr",
            "pageBorderFill",
        }
        for section_name in _section_names(archive):
            section = etree.fromstring(archive.read(section_name))
            sec_pr = section.find(".//hp:secPr", {"hp": HP})
            if sec_pr is None:
                issues.append(f"{section_name}: missing hp:secPr")
                continue
            for attr in (
                "textDirection",
                "spaceColumns",
                "tabStop",
                "tabStopVal",
                "tabStopUnit",
                "outlineShapeIDRef",
                "memoShapeIDRef",
                "textVerticalWidthHead",
                "masterPageCnt",
            ):
                if sec_pr.get(attr) is None:
                    issues.append(f"{section_name}: hp:secPr missing {attr}")
            children = set(_local_names(sec_pr))
            missing_children = sorted(section_required_children - children)
            if missing_children:
                issues.append(f"{section_name}: hp:secPr missing children: {', '.join(missing_children)}")
            first_run = section.find("hp:p/hp:run", {"hp": HP})
            if first_run is None:
                issues.append(f"{section_name}: first paragraph missing first hp:run")
            else:
                first_run_children = _local_names(first_run)
                if not first_run_children or first_run_children[0] != "secPr":
                    issues.append(f"{section_name}: first run must start with hp:secPr")
                if first_run.find("hp:ctrl/hp:colPr", {"hp": HP}) is None:
                    issues.append(f"{section_name}: first run missing hp:ctrl/hp:colPr")
    return issues


def _verify_no_draw_text_equations(path: Path) -> list[str]:
    issues: list[str] = []
    ns = {"hp": HP}
    with zipfile.ZipFile(path) as archive:
        for section_name in _section_names(archive):
            section = etree.fromstring(archive.read(section_name))
            for draw_index, draw in enumerate(section.findall(".//hp:drawText", ns), start=1):
                equations = draw.findall(".//hp:equation", ns)
                if equations:
                    issues.append(
                        f"{section_name}: drawText #{draw_index} contains hp:equation; "
                        "PDF layout export must keep equations out of drawText"
                    )
    return issues


def _verify_image_manifest_refs(path: Path) -> list[str]:
    issues: list[str] = []
    ns = {"hc": HC, "opf": OPF}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "Contents/content.hpf" not in names:
            return ["missing Contents/content.hpf"]

        package = etree.fromstring(archive.read("Contents/content.hpf"))
        manifest_items = package.findall(".//opf:item", ns)
        manifest_by_id = {
            str(item.get("id") or ""): str(item.get("href") or "")
            for item in manifest_items
            if item.get("id")
        }
        bindata_hrefs = {
            str(item.get("href") or "")
            for item in manifest_items
            if str(item.get("href") or "").startswith("BinData/")
        }
        embedded_hrefs = {
            str(item.get("href") or "")
            for item in manifest_items
            if str(item.get("href") or "").startswith("BinData/") and item.get("isEmbeded") == "1"
        }
        package_bindata = {name for name in names if name.startswith("BinData/")}

        for href in sorted(package_bindata - bindata_hrefs):
            issues.append(f"Contents/content.hpf: missing manifest item for {href}")
        for href in sorted(bindata_hrefs - names):
            issues.append(f"Contents/content.hpf: manifest image href missing from package: {href}")
        for href in sorted(bindata_hrefs - embedded_hrefs):
            issues.append(f"Contents/content.hpf: image manifest item missing isEmbeded=1 for {href}")

        for section_name in _section_names(archive):
            section = etree.fromstring(archive.read(section_name))
            for image in section.findall(".//hc:img", ns):
                ref = str(image.get("binaryItemIDRef") or "").strip()
                if not ref:
                    issues.append(f"{section_name}: hc:img missing binaryItemIDRef")
                    continue
                href = manifest_by_id.get(ref)
                if href is None:
                    issues.append(f"{section_name}: hc:img references {ref!r}, missing from content.hpf manifest")
                elif href not in names:
                    issues.append(f"{section_name}: hc:img references {ref!r}, but {href} is missing from package")
    return issues


def _verify_bindata_inventory(path: Path) -> list[str]:
    issues: list[str] = []
    ns = {"hh": HH, "hc": HC, "opf": OPF}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "Contents/header.xml" not in names or "Contents/content.hpf" not in names:
            return issues

        header = etree.fromstring(archive.read("Contents/header.xml"))
        package = etree.fromstring(archive.read("Contents/content.hpf"))
        package_bindata = {name for name in names if name.startswith("BinData/")}
        manifest_bindata = {
            str(item.get("href") or "")
            for item in package.findall(".//opf:item", ns)
            if str(item.get("href") or "").startswith("BinData/")
        }

        header_bindata: set[str] = set()
        header_ref_ids: set[str] = set()
        for item in header.findall(".//hh:binItem", ns):
            bindata = str(item.get("BinData") or "").strip()
            if not bindata:
                issues.append("Contents/header.xml: hh:binItem missing BinData")
                continue
            href = f"BinData/{Path(bindata).name}"
            if href in header_bindata:
                issues.append(f"Contents/header.xml: duplicate hh:binItem BinData {href}")
            header_bindata.add(href)
            header_ref_ids.add(Path(bindata).stem)
            if item.get("Type") != "Embedding":
                issues.append(f"Contents/header.xml: {bindata} Type is {item.get('Type')!r}, expected Embedding")
            expected_format = Path(bindata).suffix.lstrip(".").lower()
            actual_format = str(item.get("Format") or "").lower()
            if expected_format and actual_format and expected_format != actual_format:
                issues.append(
                    f"Contents/header.xml: {bindata} Format is {actual_format!r}, expected {expected_format!r}"
                )
            if href not in names:
                issues.append(f"Contents/header.xml: hh:binItem references missing package file {href}")

        for href in sorted(package_bindata - header_bindata):
            issues.append(f"Contents/header.xml: missing hh:binItem for package file {href}")
        for href in sorted(header_bindata - package_bindata):
            issues.append(f"Contents/header.xml: hh:binItem {href} is missing from package")
        for href in sorted(manifest_bindata - header_bindata):
            issues.append(f"Contents/header.xml: missing hh:binItem for manifest href {href}")

        for section_name in _section_names(archive):
            section = etree.fromstring(archive.read(section_name))
            for image in section.findall(".//hc:img", ns):
                ref = str(image.get("binaryItemIDRef") or "").strip()
                if ref and ref not in header_ref_ids:
                    issues.append(f"{section_name}: hc:img references {ref!r}, missing from header binItem inventory")
    return issues


def _verify_no_page_images(path: Path) -> list[str]:
    issues: list[str] = []
    ns = {"hp": HP, "hs": HS}
    with zipfile.ZipFile(path) as archive:
        for section_name in _section_names(archive):
            section = etree.fromstring(archive.read(section_name))
            setup = _section_page_setup(section, ns)
            if setup is None:
                continue
            page_width, page_height, _orientation = setup
            page_area = page_width * page_height
            if page_area <= 0:
                continue
            total_pic_area = 0
            for pic_index, pic in enumerate(section.findall(".//hp:pic", ns), start=1):
                size = pic.find(".//hp:sz", ns)
                if size is None:
                    continue
                area = int(size.get("width") or 0) * int(size.get("height") or 0)
                total_pic_area += area
                if area > page_area * 0.5:
                    ratio = area / page_area
                    issues.append(
                        f"{section_name}: pic #{pic_index} looks like a full-page raster fallback "
                        f"(area_ratio={ratio:.3f})"
                    )
            if total_pic_area > page_area * 0.85:
                ratio = total_pic_area / page_area
                issues.append(
                    f"{section_name}: combined picture area looks like tiled full-page raster fallback "
                    f"(area_ratio={ratio:.3f})"
                )
    return issues


def _verify_no_broken_math_placeholder_text(path: Path) -> list[str]:
    issues: list[str] = []
    ns = {"hp": HP}
    broken_chars = {"□", "▢", "\ufffd", "\ufffc"}
    with zipfile.ZipFile(path) as archive:
        for section_name in _section_names(archive):
            section = etree.fromstring(archive.read(section_name))
            for text_index, text_node in enumerate(section.findall(".//hp:t", ns), start=1):
                value = text_node.text or ""
                if any(char in value for char in broken_chars):
                    issues.append(
                        f"{section_name}: text #{text_index} contains broken math placeholder text {value!r}"
                    )
                for char in value:
                    if 0xE000 <= ord(char) <= 0xF8FF:
                        issues.append(
                            f"{section_name}: text #{text_index} contains unrecovered PUA U+{ord(char):04X}"
                        )
    return issues


def _package_issues(path: Path) -> list[str]:
    try:
        from hwpx.tools.package_validator import validate_package
    except Exception as exc:  # pragma: no cover - optional vendored tool
        return [f"package validator unavailable: {exc}"]
    report = validate_package(path)
    return [str(issue) for issue in report.errors]


def _render_first_page(path: Path) -> str:
    try:
        import rhwp
    except Exception as exc:
        return f"render skipped: rhwp unavailable ({exc})"
    doc = rhwp.parse(str(path))
    rendered = bytes(doc.render_png(0))
    if not rendered:
        raise RuntimeError("rhwp returned an empty first-page render")
    return f"render ok: pages={doc.page_count} first_page_png={len(rendered)} bytes"


def verify(
    path: Path,
    *,
    render: bool,
    allow_draw_text_equations: bool = False,
    require_pdf_font_faces: bool = True,
) -> list[str]:
    issues = []
    issues.extend(_package_issues(path))
    issues.extend(_verify_hancom_compatibility(path, require_pdf_font_faces=require_pdf_font_faces))
    issues.extend(_verify_page_setup(path))
    issues.extend(_verify_shape_text(path))
    if not allow_draw_text_equations:
        issues.extend(_verify_no_draw_text_equations(path))
    issues.extend(_verify_image_manifest_refs(path))
    issues.extend(_verify_bindata_inventory(path))
    issues.extend(_verify_no_page_images(path))
    issues.extend(_verify_no_broken_math_placeholder_text(path))
    if render:
        try:
            print(f"{path}: {_render_first_page(path)}")
        except Exception as exc:
            issues.append(f"render failed: {exc}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify PDF-coordinate editable HWPX structure.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--render", action="store_true", help="also render page 1 with rhwp when available")
    parser.add_argument(
        "--allow-draw-text-equations",
        action="store_true",
        help="allow native equation controls inside drawText for AI-recognized PDF math crops",
    )
    args = parser.parse_args()

    failed = False
    for path in args.paths:
        issues = verify(path, render=args.render, allow_draw_text_equations=args.allow_draw_text_equations)
        if issues:
            failed = True
            print(f"FAIL {path}")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"OK {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
