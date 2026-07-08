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


def _local_names(element: etree._Element) -> list[str]:
    return [etree.QName(child).localname for child in list(element)]


def _section_names(archive: zipfile.ZipFile) -> list[str]:
    return sorted(
        name
        for name in archive.namelist()
        if name.startswith("Contents/") and Path(name).name.startswith("section") and name.endswith(".xml")
    )


def _verify_shape_text(path: Path) -> list[str]:
    issues: list[str] = []
    ns = {"hp": HP}
    with zipfile.ZipFile(path) as archive:
        section_names = _section_names(archive)
        if not section_names:
            return ["missing Contents/section*.xml"]
        for section_name in section_names:
            section = etree.fromstring(archive.read(section_name))
            for rect_index, rect in enumerate(section.findall(".//hp:rect", ns), start=1):
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
    return issues


def _verify_hancom_compatibility(path: Path) -> list[str]:
    issues: list[str] = []
    ns = {"hh": HH, "opf": OPF, "hv": HV}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "Contents/header.xml" not in names:
            return ["missing Contents/header.xml"]
        header = etree.fromstring(archive.read("Contents/header.xml"))
        if header.get("version") != "1.4":
            issues.append(f"Contents/header.xml: hh:head version is {header.get('version')!r}, expected '1.4'")
        compatible = header.find(".//hh:compatibleDocument", ns)
        if compatible is None:
            issues.append("Contents/header.xml: missing hh:compatibleDocument")
        elif compatible.get("targetProgram") != "HWP2018":
            issues.append(
                "Contents/header.xml: hh:compatibleDocument targetProgram is "
                f"{compatible.get('targetProgram')!r}, expected 'HWP2018'"
            )

        faces = {font.get("face") for font in header.findall(".//hh:font", ns) if font.get("face")}
        missing_faces = sorted(REQUIRED_FONT_FACES - faces)
        if missing_faces:
            issues.append("Contents/header.xml: missing PDF font faces: " + ", ".join(missing_faces))

        if "Contents/content.hpf" not in names:
            issues.append("missing Contents/content.hpf")
        else:
            package = etree.fromstring(archive.read("Contents/content.hpf"))
            version_items = [
                item
                for item in package.findall(".//opf:item", ns)
                if "version" in " ".join(
                    str(item.get(attr) or "").lower()
                    for attr in ("id", "href", "media-type", "properties")
                )
            ]
            if not version_items:
                issues.append("Contents/content.hpf: manifest does not reference version.xml")

        if "version.xml" not in names:
            issues.append("missing version.xml")
        else:
            version = etree.fromstring(archive.read("version.xml"))
            if version.tag == f"{{{HV}}}HCFVersion" and version.get("xmlVersion") != "1.4":
                issues.append(f"version.xml: xmlVersion is {version.get('xmlVersion')!r}, expected '1.4'")
    return issues


def _verify_no_page_images(path: Path) -> list[str]:
    issues: list[str] = []
    ns = {"hp": HP, "hs": HS}
    with zipfile.ZipFile(path) as archive:
        for section_name in _section_names(archive):
            section = etree.fromstring(archive.read(section_name))
            page_size = section.find(".//hs:pagePr/hs:pageSz", ns)
            if page_size is None:
                continue
            page_area = int(page_size.get("width") or 0) * int(page_size.get("height") or 0)
            if page_area <= 0:
                continue
            for pic_index, pic in enumerate(section.findall(".//hp:pic", ns), start=1):
                size = pic.find("hp:sz", ns)
                if size is None:
                    continue
                area = int(size.get("width") or 0) * int(size.get("height") or 0)
                if area > page_area * 0.5:
                    issues.append(f"{section_name}: pic #{pic_index} looks like a full-page raster fallback")
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


def verify(path: Path, *, render: bool) -> list[str]:
    issues = []
    issues.extend(_package_issues(path))
    issues.extend(_verify_hancom_compatibility(path))
    issues.extend(_verify_shape_text(path))
    issues.extend(_verify_no_page_images(path))
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
    args = parser.parse_args()

    failed = False
    for path in args.paths:
        issues = verify(path, render=args.render)
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
