"""Match complete native equations to adjacent measured PDF font fragments."""
from collections import defaultdict
import re
from statistics import median


def joined_equation_metrics(lines, targets):
    from .hwpx_writer import _hancom_eqn_script
    from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font

    matches = defaultdict(list)
    if not targets:
        return matches
    longest = max(map(len, targets))
    for line in lines:
        spans = line.get("spans", [])
        for start, first in enumerate(spans):
            if not is_hancom_eq_font(str(first.get("font", ""))):
                continue
            expression, parts = "", []
            for span in spans[start:]:
                box = span.get("bbox") or ()
                size = float(span.get("size") or 0)
                if (not is_hancom_eq_font(str(span.get("font", "")))
                    or len(box) != 4 or size <= 0 or box[2] <= box[0]):
                    break
                if parts and box[0] - max(p[1][2] for p in parts) > max(size, parts[-1][0]) * .9:
                    break
                expression += _pdf_output_text(span.get("text", "")).strip().strip("$")
                parts.append((size, box))
                if len(expression) > longest * 3 + 20:
                    break
                # Single-span matches already have a direct measurement. The
                # extra evidence here is the complete sequence, not a formula
                # selected merely because it is spatially close.
                if len(parts) < 2:
                    continue
                script = _hancom_eqn_script(expression)
                if not script:
                    continue
                canonical = re.sub(r"\s+", "", script)
                if canonical in targets:
                    largest = max(p[0] for p in parts)
                    baseline_size = median(p[0] for p in parts if p[0] > largest * .82)
                    width = max(p[1][2] for p in parts) - min(p[1][0] for p in parts)
                    matches[canonical].append((baseline_size, width))
    return matches
