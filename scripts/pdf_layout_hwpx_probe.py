from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pdf_layout_writer import write_pdf_flow_hwpx, write_pdf_layout_hwpx, write_pdf_raster_hwpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Create layout-preserving editable HWPX from a PDF.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--no-images", action="store_true")
    parser.add_argument("--no-lines", action="store_true")
    parser.add_argument("--raster", action="store_true")
    parser.add_argument("--flow", action="store_true")
    parser.add_argument("--no-boxes", action="store_true")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--text-mode", choices=("line", "span"), default="line")
    parser.add_argument("--math-ai", action="store_true", help="Use Gemini math crop recognition when available.")
    parser.add_argument("--math-ai-model", default=None, help="Gemini model id for math crop recognition.")
    args = parser.parse_args()

    if args.raster:
        stats = write_pdf_raster_hwpx(args.pdf, args.output, max_pages=args.max_pages, dpi=args.dpi)
    elif args.flow:
        stats = write_pdf_flow_hwpx(args.pdf, args.output, max_pages=args.max_pages, boxed_passages=not args.no_boxes)
    else:
        stats = write_pdf_layout_hwpx(
            args.pdf,
            args.output,
            max_pages=args.max_pages,
            include_images=not args.no_images,
            include_lines=not args.no_lines,
            text_mode=args.text_mode,
            math_ai_recognition=True if args.math_ai else None,
            math_ai_model=args.math_ai_model,
        )
    print(json.dumps({"output": str(args.output), **stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
