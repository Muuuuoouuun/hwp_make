from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SECTION_RE = re.compile(r"Contents/section(?P<number>\d+)\.xml$")
MATH_NAME_RE = re.compile(r"(?:math|수학)", re.IGNORECASE)
PROBLEM_RE = re.compile(r"^\s*(?:문제\s*)?\d{1,3}\s*[.)]")
CHOICE_RE = re.compile(r"[①②③④⑤]")

MIN_EQUATION_HEIGHT = 1300
MAX_EQUATION_HEIGHT = 6200


@dataclass(frozen=True)
class HeightIssue:
    kind: str
    section: str
    paragraph_id: str
    cell_index: int | None
    cell_kind: str | None
    required_height: int
    available_height: int
    script: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _direct_children(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(node) if _local_name(child.tag) == name]


def _int_attr(node: ET.Element | None, name: str) -> int:
    if node is None:
        return 0
    try:
        return max(0, int(node.get(name) or "0"))
    except (TypeError, ValueError):
        return 0


def required_equation_height(script: str) -> int:
    """Return the frozen minimum line height for a Hancom EQN script.

    This deliberately does not import either HWPX writer. It is an independent
    regression oracle for the script features that make equations taller.
    """

    text = str(script or "")
    height = MIN_EQUATION_HEIGHT
    if " over " in text or "sqrt" in text or "choose" in text:
        height = 2100
    if any(token in text for token in ("int", "dint", "tint", "oint", "sum", "prod", "lim")):
        height = max(height, 2300)
    if any(
        token in text
        for token in ("int_", "dint_", "tint_", "oint_", "sum_", "prod_", "lim_")
    ) or ("^{" in text and "_" in text):
        height = max(height, 2700)
    if len(text) > 90:
        height = max(height, 1900)
    if any(token in text for token in ("matrix{", "pmatrix{", "bmatrix{", "cases{", "eqalign{")):
        row_count = max(2, text.count("#") + 1)
        height = max(height, 1500 + row_count * 1050)
    return min(height, MAX_EQUATION_HEIGHT)


def _direct_equations(paragraph: ET.Element) -> list[tuple[ET.Element, str]]:
    equations: list[tuple[ET.Element, str]] = []
    for run in _direct_children(paragraph, "run"):
        for equation in _direct_children(run, "equation"):
            scripts = _direct_children(equation, "script")
            script = "".join(node.text or "" for node in scripts).strip()
            equations.append((equation, script))
    return equations


def _paragraph_lineseg_height(paragraph: ET.Element) -> int:
    heights: list[int] = []
    for array in _direct_children(paragraph, "linesegarray"):
        for lineseg in _direct_children(array, "lineseg"):
            heights.append(max(_int_attr(lineseg, "textheight"), _int_attr(lineseg, "vertsize")))
    return max(heights, default=0)


def _first_direct_child(node: ET.Element, name: str) -> ET.Element | None:
    return next(iter(_direct_children(node, name)), None)


def _table_height(table: ET.Element) -> int:
    return _int_attr(_first_direct_child(table, "sz"), "height")


def _outer_tables(
    paragraph: ET.Element,
    parents: dict[ET.Element, ET.Element],
) -> list[ET.Element]:
    tables: list[ET.Element] = []
    for table in (node for node in paragraph.iter() if _local_name(node.tag) == "tbl"):
        current = parents.get(table)
        nested = False
        while current is not None and current is not paragraph:
            if _local_name(current.tag) == "tbl":
                nested = True
                break
            current = parents.get(current)
        if not nested:
            tables.append(table)
    return tables


def _paragraph_flow_height(
    paragraph: ET.Element,
    parents: dict[ET.Element, ET.Element],
) -> int:
    tables = _outer_tables(paragraph, parents)
    if tables:
        return sum(_table_height(table) for table in tables)
    line_height = _paragraph_lineseg_height(paragraph)
    inline_picture_height = max(
        (
            _picture_height(picture)
            for picture in paragraph.iter()
            if _local_name(picture.tag) == "pic" and _picture_is_safe_inline(picture)
        ),
        default=0,
    )
    return max(line_height, inline_picture_height)


def _picture_height(picture: ET.Element) -> int:
    return _int_attr(_first_direct_child(picture, "sz"), "height")


def _picture_is_safe_inline(picture: ET.Element) -> bool:
    position = _first_direct_child(picture, "pos")
    return bool(
        position is not None
        and position.get("treatAsChar") == "1"
        and position.get("allowOverlap") == "0"
    )


def _next_empty_table(
    paragraph: ET.Element,
    parents: dict[ET.Element, ET.Element],
) -> tuple[int, bool]:
    sub_list = parents.get(paragraph)
    if sub_list is None or _local_name(sub_list.tag) != "subList":
        return 0, False
    siblings = list(sub_list)
    try:
        next_index = siblings.index(paragraph) + 1
        next_paragraph = siblings[next_index]
    except (ValueError, IndexError):
        return 0, False
    if _local_name(next_paragraph.tag) != "p":
        return 0, False
    tables = _outer_tables(next_paragraph, parents)
    if len(tables) != 1 or _cell_text(tables[0]):
        return 0, False
    has_following_content = any(
        (
            _cell_text(node)
            or any(
                _local_name(descendant.tag) in {"equation", "pic"}
                for descendant in node.iter()
            )
        )
        for node in siblings[next_index + 1 :]
        if _local_name(node.tag) == "p"
    )
    return _table_height(tables[0]), bool(has_following_content)


def _problem_cell_flow(
    cell: ET.Element,
    parents: dict[ET.Element, ET.Element],
) -> tuple[int, int]:
    sub_list = _first_direct_child(cell, "subList")
    if sub_list is None:
        return 0, 0
    paragraphs = _direct_children(sub_list, "p")
    flow_height = sum(_paragraph_flow_height(paragraph, parents) for paragraph in paragraphs)
    picture_heights = [
        _picture_height(picture)
        for paragraph in paragraphs
        for picture in paragraph.iter()
        if _local_name(picture.tag) == "pic"
    ]
    return flow_height, max(picture_heights, default=0)


def _nearest_ancestor(
    node: ET.Element,
    parents: dict[ET.Element, ET.Element],
    name: str,
) -> ET.Element | None:
    current = parents.get(node)
    while current is not None:
        if _local_name(current.tag) == name:
            return current
        current = parents.get(current)
    return None


def _cell_available_height(cell: ET.Element) -> tuple[int, int, int]:
    sizes = _direct_children(cell, "cellSz")
    margins = _direct_children(cell, "cellMargin")
    cell_height = _int_attr(sizes[0] if sizes else None, "height")
    margin = margins[0] if margins else None
    vertical_margin = _int_attr(margin, "top") + _int_attr(margin, "bottom")
    return cell_height, vertical_margin, max(0, cell_height - vertical_margin)


def _cell_text(cell: ET.Element) -> str:
    return "".join(node.text or "" for node in cell.iter() if _local_name(node.tag) == "t").strip()


def _cell_kind(cell: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    text = _cell_text(cell)
    if CHOICE_RE.match(text):
        return "choice"
    if PROBLEM_RE.match(text) or len(CHOICE_RE.findall(text)) >= 3:
        return "problem"

    table = _nearest_ancestor(cell, parents, "tbl")
    if table is not None:
        row_count = _int_attr(table, "rowCnt")
        column_count = _int_attr(table, "colCnt")
        if row_count == 1 and 4 <= column_count <= 6:
            return "choice"
    return "cell"


def _section_names(archive: zipfile.ZipFile) -> list[str]:
    names = [name for name in archive.namelist() if SECTION_RE.fullmatch(name)]
    return sorted(names, key=lambda name: int(SECTION_RE.fullmatch(name).group("number")))


def inspect_hwpx(path: Path) -> dict[str, object]:
    issues: list[HeightIssue] = []
    direct_equation_count = 0
    direct_script_count = 0
    missing_script_count = 0
    paragraph_check_count = 0
    cell_check_count = 0
    picture_check_count = 0
    problem_balance_check_count = 0
    logical_page_table_check_count = 0
    section_count = 0

    with zipfile.ZipFile(path) as archive:
        section_names = _section_names(archive)
        section_count = len(section_names)
        if not section_names:
            raise ValueError("HWPX contains no Contents/sectionN.xml parts")

        for section_name in section_names:
            root = ET.fromstring(archive.read(section_name))
            parents = {child: parent for parent in root.iter() for child in list(parent)}
            cells = [node for node in root.iter() if _local_name(node.tag) == "tc"]
            cell_indexes = {cell: index for index, cell in enumerate(cells, start=1)}
            cell_requirements: dict[ET.Element, dict[str, object]] = {}

            paragraphs = [node for node in root.iter() if _local_name(node.tag) == "p"]
            for paragraph_index, paragraph in enumerate(paragraphs, start=1):
                equations = _direct_equations(paragraph)
                if not equations:
                    continue

                paragraph_check_count += 1
                direct_equation_count += len(equations)
                scripts = [script for _equation, script in equations if script]
                direct_script_count += len(scripts)
                missing_script_count += len(equations) - len(scripts)
                paragraph_id = str(paragraph.get("id") or paragraph_index)
                required_height = max(
                    (required_equation_height(script) for script in scripts),
                    default=0,
                )
                available_height = _paragraph_lineseg_height(paragraph)
                sample_script = max(scripts, key=required_equation_height, default="")

                cell = _nearest_ancestor(paragraph, parents, "tc")
                cell_index = cell_indexes.get(cell) if cell is not None else None
                cell_kind = _cell_kind(cell, parents) if cell is not None else None
                if required_height and available_height < required_height:
                    issues.append(
                        HeightIssue(
                            kind="paragraph_lineseg",
                            section=section_name,
                            paragraph_id=paragraph_id,
                            cell_index=cell_index,
                            cell_kind=cell_kind,
                            required_height=required_height,
                            available_height=available_height,
                            script=sample_script[:180],
                        )
                    )

                if cell is not None and required_height:
                    record = cell_requirements.setdefault(
                        cell,
                        {
                            "required_height": 0,
                            "paragraph_id": paragraph_id,
                            "script": sample_script,
                        },
                    )
                    if required_height > int(record["required_height"]):
                        record["required_height"] = required_height
                        record["paragraph_id"] = paragraph_id
                        record["script"] = sample_script

            for cell, record in cell_requirements.items():
                cell_check_count += 1
                _cell_height, _vertical_margin, available_height = _cell_available_height(cell)
                required_height = int(record["required_height"])
                if available_height < required_height:
                    issues.append(
                        HeightIssue(
                            kind="enclosing_cell",
                            section=section_name,
                            paragraph_id=str(record["paragraph_id"]),
                            cell_index=cell_indexes[cell],
                            cell_kind=_cell_kind(cell, parents),
                            required_height=required_height,
                            available_height=available_height,
                            script=str(record["script"])[:180],
                        )
                    )

            pictures = [node for node in root.iter() if _local_name(node.tag) == "pic"]
            for picture in pictures:
                picture_height = _picture_height(picture)
                if picture_height <= 1000:
                    continue
                paragraph = _nearest_ancestor(picture, parents, "p")
                if paragraph is None:
                    continue
                picture_check_count += 1
                cell = _nearest_ancestor(paragraph, parents, "tc")
                if not _picture_is_safe_inline(picture):
                    issues.append(
                        HeightIssue(
                            kind="figure_not_safe_inline",
                            section=section_name,
                            paragraph_id=str(paragraph.get("id") or ""),
                            cell_index=cell_indexes.get(cell) if cell is not None else None,
                            cell_kind=_cell_kind(cell, parents) if cell is not None else None,
                            required_height=1,
                            available_height=0,
                            script=f"picture_height={picture_height}",
                        )
                    )
                duplicate_spacer, has_following_content = _next_empty_table(
                    paragraph,
                    parents,
                )
                maximum_trailing_gap = max(1500, int(picture_height * 0.30))
                if has_following_content and duplicate_spacer > maximum_trailing_gap:
                    issues.append(
                        HeightIssue(
                            kind="figure_duplicate_spacer",
                            section=section_name,
                            paragraph_id=str(paragraph.get("id") or ""),
                            cell_index=cell_indexes.get(cell) if cell is not None else None,
                            cell_kind=_cell_kind(cell, parents) if cell is not None else None,
                            required_height=maximum_trailing_gap,
                            available_height=duplicate_spacer,
                            script=f"picture_height={picture_height}",
                        )
                    )

            for cell in cells:
                table = _nearest_ancestor(cell, parents, "tbl")
                if (
                    table is None
                    or _int_attr(table, "rowCnt") != 1
                    or _int_attr(table, "colCnt") != 1
                    or _cell_kind(cell, parents) != "problem"
                ):
                    continue
                problem_balance_check_count += 1
                _cell_height, _vertical_margin, available_height = _cell_available_height(cell)
                flow_height, picture_height = _problem_cell_flow(cell, parents)
                if flow_height > available_height:
                    issues.append(
                        HeightIssue(
                            kind="problem_content_overflow",
                            section=section_name,
                            paragraph_id="",
                            cell_index=cell_indexes[cell],
                            cell_kind="problem",
                            required_height=flow_height,
                            available_height=available_height,
                            script=_cell_text(cell)[:180],
                        )
                    )
                    continue
                allowed_slack = 1500 + int(max(0, picture_height - 1000) * 0.15)
                if available_height - flow_height > allowed_slack:
                    issues.append(
                        HeightIssue(
                            kind="problem_vertical_balance",
                            section=section_name,
                            paragraph_id="",
                            cell_index=cell_indexes[cell],
                            cell_kind="problem",
                            required_height=max(0, available_height - allowed_slack),
                            available_height=flow_height,
                            script=_cell_text(cell)[:180],
                        )
                    )

            tables = [node for node in root.iter() if _local_name(node.tag) == "tbl"]
            for table in tables:
                if (
                    _nearest_ancestor(table, parents, "tbl") is not None
                    or _int_attr(table, "rowCnt") != 1
                    or _int_attr(table, "colCnt") != 2
                    or _table_height(table) <= 40000
                ):
                    continue
                page_cells = [
                    node
                    for node in table.iter()
                    if _local_name(node.tag) == "tc"
                    and _nearest_ancestor(node, parents, "tbl") is table
                ]
                for cell in page_cells:
                    logical_page_table_check_count += 1
                    _cell_height, _vertical_margin, available_height = _cell_available_height(cell)
                    available_height = min(available_height, _table_height(table))
                    sub_list = _first_direct_child(cell, "subList")
                    required_height = sum(
                        _paragraph_flow_height(paragraph, parents)
                        for paragraph in _direct_children(sub_list, "p")
                    ) if sub_list is not None else 0
                    if required_height > available_height:
                        issues.append(
                            HeightIssue(
                                kind="logical_page_table_overflow",
                                section=section_name,
                                paragraph_id="",
                                cell_index=cell_indexes.get(cell),
                                cell_kind="page_column",
                                required_height=required_height,
                                available_height=available_height,
                                script="",
                            )
                        )

    paragraph_issues = [issue for issue in issues if issue.kind == "paragraph_lineseg"]
    cell_issues = [issue for issue in issues if issue.kind == "enclosing_cell"]
    figure_issues = [issue for issue in issues if issue.kind.startswith("figure_")]
    balance_issues = [issue for issue in issues if issue.kind == "problem_vertical_balance"]
    content_overflow_issues = [issue for issue in issues if issue.kind == "problem_content_overflow"]
    page_overflow_issues = [issue for issue in issues if issue.kind == "logical_page_table_overflow"]
    shortage_count = len(issues)
    return {
        "path": str(path),
        "section_count": section_count,
        "direct_equation_count": direct_equation_count,
        "direct_script_count": direct_script_count,
        "missing_script_count": missing_script_count,
        "paragraph_check_count": paragraph_check_count,
        "cell_check_count": cell_check_count,
        "picture_check_count": picture_check_count,
        "problem_balance_check_count": problem_balance_check_count,
        "logical_page_table_check_count": logical_page_table_check_count,
        "paragraph_shortage_count": len(paragraph_issues),
        "cell_shortage_count": len(cell_issues),
        "figure_layout_issue_count": len(figure_issues),
        "problem_balance_shortage_count": len(balance_issues),
        "problem_content_overflow_count": len(content_overflow_issues),
        "logical_page_table_overflow_count": len(page_overflow_issues),
        "shortage_count": shortage_count,
        "required_shortage_count": 0,
        "ok": direct_script_count > 0 and missing_script_count == 0 and shortage_count == 0,
        "issues": [asdict(issue) for issue in issues],
    }


def _looks_like_math(path: Path) -> bool:
    return bool(MATH_NAME_RE.search(str(path)))


def _not_control(path: Path) -> bool:
    lowered = path.name.casefold()
    return "blank_equation" not in lowered and "blank-equation" not in lowered


def _latest_by_name(paths: Iterable[Path]) -> list[Path]:
    latest: dict[str, Path] = {}
    for path in paths:
        current = latest.get(path.name)
        if current is None or path.stat().st_mtime > current.stat().st_mtime:
            latest[path.name] = path
    return list(latest.values())


def _auto_paths() -> list[Path]:
    paths: list[Path] = []
    pdf_layout = ROOT / "data" / "exports" / "pdf_layout"
    if pdf_layout.is_dir():
        structured = [
            path
            for path in pdf_layout.rglob("*_structured_native.hwpx")
            if path.is_file() and _looks_like_math(path) and _not_control(path)
        ]
        paths.extend(_latest_by_name(structured))

    for final_dir in (ROOT / "data" / "exports").glob("final_results_*"):
        if final_dir.is_dir():
            paths.extend(
                path
                for path in final_dir.rglob("*.hwpx")
                if path.is_file() and _looks_like_math(path) and _not_control(path)
            )

    fixture_patterns = (
        "tests/fixtures/**/*math*.hwpx",
        "tests/fixtures/**/*수학*.hwpx",
        "scripts/fixtures/**/*math*.hwpx",
        "scripts/fixtures/**/*수학*.hwpx",
        "data/fixtures/**/*math*.hwpx",
        "data/fixtures/**/*수학*.hwpx",
        "data/pdf_math_qa/exports/synthetic_pdf_math*_native.hwpx",
        "data/native_math_qa/native_math_corpus.hwpx",
        "data/kice_typography/kice_math_typography.hwpx",
    )
    for pattern in fixture_patterns:
        paths.extend(path for path in ROOT.glob(pattern) if path.is_file() and _not_control(path))

    unique: dict[Path, Path] = {}
    for path in paths:
        unique[path.resolve()] = path.resolve()
    return sorted(unique.values(), key=lambda path: str(path).casefold())


def _requested_paths(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    missing: list[str] = []
    for value in values:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            local = (Path.cwd() / candidate).resolve()
            candidate = local if local.exists() else (ROOT / candidate).resolve()
        if candidate.is_file():
            if candidate.suffix.casefold() != ".hwpx":
                missing.append(f"{value} (not an .hwpx file)")
            else:
                paths.append(candidate)
        elif candidate.is_dir():
            paths.extend(sorted(candidate.rglob("*.hwpx")))
        else:
            missing.append(value)
    if missing:
        raise FileNotFoundError("not found: " + ", ".join(missing))

    unique: dict[Path, Path] = {}
    for path in paths:
        unique[path.resolve()] = path.resolve()
    return sorted(unique.values(), key=lambda path: str(path).casefold())


def _self_check() -> None:
    checks = {
        "x+1": 1300,
        "{1} over {2}": 2100,
        "sum_{k=1}^{n} k": 2700,
        "pmatrix{1 & 0 # 0 & 1}": 3600,
    }
    for script, expected in checks.items():
        actual = required_equation_height(script)
        if actual != expected:
            raise AssertionError(f"height oracle mismatch for {script!r}: {actual} != {expected}")


def _print_result(result: dict[str, object], max_issues: int) -> None:
    status = "PASS" if result["ok"] else "FAIL"
    print(f"[{status}] {result['path']}")
    print(
        "  direct_equations={direct_equation_count} scripts={direct_script_count} "
        "paragraphs={paragraph_check_count} cells={cell_check_count} "
        "pictures={picture_check_count} problem_balances={problem_balance_check_count} "
        "page_columns={logical_page_table_check_count} "
        "paragraph_shortages={paragraph_shortage_count} "
        "cell_shortages={cell_shortage_count} "
        "figure_layout_issues={figure_layout_issue_count} "
        "balance_shortages={problem_balance_shortage_count} "
        "content_overflows={problem_content_overflow_count} "
        "page_overflows={logical_page_table_overflow_count} "
        "shortage_count={shortage_count} "
        "required=0".format(**result)
    )
    if result["missing_script_count"]:
        print(f"  missing direct equation scripts: {result['missing_script_count']}")
    for issue in list(result["issues"])[:max_issues]:
        location = f"{issue['section']} p={issue['paragraph_id']}"
        if issue["cell_index"] is not None:
            location += f" cell={issue['cell_index']}({issue['cell_kind']})"
        print(
            f"  - {issue['kind']}: {location} required={issue['required_height']} "
            f"available={issue['available_height']} script={issue['script']!r}"
        )
    hidden = len(result["issues"]) - max_issues
    if hidden > 0:
        print(f"  ... {hidden} more issue(s)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Require zero native-equation height shortages in paragraph line segments "
            "and enclosing structured-math cells."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="HWPX file or directory. With no arguments, discover current outputs and fixtures.",
    )
    parser.add_argument("--max-issues", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="Print the complete result as JSON.")
    args = parser.parse_args()

    _self_check()
    try:
        paths = _requested_paths(args.paths) if args.paths else _auto_paths()
    except FileNotFoundError as exc:
        parser.error(str(exc))

    if not paths:
        print("No structured native-math HWPX outputs or fixtures were found; skipping.")
        return 2

    results: list[dict[str, object]] = []
    for path in paths:
        try:
            result = inspect_hwpx(path)
        except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile) as exc:
            result = {
                "path": str(path),
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "shortage_count": None,
                "required_shortage_count": 0,
                "issues": [],
            }
        results.append(result)
        if not args.json:
            if "error" in result:
                print(f"[FAIL] {path}\n  {result['error']}")
            else:
                _print_result(result, max(0, args.max_issues))

    ok = all(bool(result.get("ok")) for result in results)
    total_shortages = sum(int(result.get("shortage_count") or 0) for result in results)
    summary = {
        "ok": ok,
        "files_checked": len(results),
        "shortage_count": total_shortages,
        "required_shortage_count": 0,
        "results": results,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"Summary: files={len(results)} shortage_count={total_shortages} "
            f"required=0 status={'PASS' if ok else 'FAIL'}"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
