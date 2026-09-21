"""Run the public PDF export gates on complete subject papers, retaining evidence.

Failed writer artifacts are diagnostic only. Only accepted files enter release/.
Timings include all public engine gates, exclude HTTP/upload and app startup.
"""
# ruff: noqa: E402 -- configure isolated storage before importing the application.
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('sources', type=Path, nargs='+')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ['HWP_MAKE_DATA_DIR'] = str(out / 'engine')
    os.environ['HWP_MAKE_SETTINGS_DIR'] = str(out / 'settings')
    sys.stdout.reconfigure(encoding='utf-8')
    from app import main as api, storage
    import fitz

    def dump(path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    current = None
    writer_seconds = 0
    original = api.pdf_layout_writer.write_pdf_structured_hwpx

    def writer(*a, **kw):
        nonlocal writer_seconds
        start = time.perf_counter()
        try:
            stats = original(*a, **kw)
            shutil.copyfile(a[1], current / 'writer_output.hwpx')
            dump(current / 'writer_stats.json', stats)
            return stats
        finally:
            writer_seconds = time.perf_counter() - start

    api.pdf_layout_writer.write_pdf_structured_hwpx = writer
    rows = []
    for source in args.sources:
        source = source.resolve()
        current = out / source.stem
        current.mkdir(exist_ok=True)
        data = source.read_bytes()
        with fitz.open(source) as pdf:
            pages = len(pdf)
        row = {'source': str(source), 'source_pages': pages,
               'source_sha256': hashlib.sha256(data).hexdigest()}
        writer_seconds = 0
        start = time.perf_counter()
        try:
            result = api.export_pdf_layout(api.PdfLayoutExportPayload(
                filename=source.name, data_base64=base64.b64encode(data).decode(),
                layout_mode='structured', math_ai_recognition=False, variant_policy='all'))
            row['engine_seconds'] = time.perf_counter() - start
            dump(current / 'result.json', result)
            release = out / 'release'
            release.mkdir(exist_ok=True)
            destination = release / (source.stem + '.hwpx')
            shutil.copyfile(storage.EXPORT_DIR / result['export']['name'], destination)
            editability = result['quality']['editability']
            row.update(ok=True, output=str(destination),
                       output_pages=result['fidelity']['hwpx_page_count'],
                       question_boxes=editability['draw_text_boxes'],
                       source_questions=editability['question_units']['source_question_count'],
                       images=editability['images'],
                       objective_score=result['quality']['objective_score'],
                       objective_target=result['quality']['objective_score_target'])
            row['page_count_matches'] = row['output_pages'] == pages
            row['objective_target_met'] = row['objective_score'] >= row['objective_target']
            row['harsh_layout_score'] = result['fidelity'].get('overall_harsh_layout_score')
            row['fidelity_target_met'] = result['fidelity'].get('meets_target')
            row['native_source_text_coverage'] = editability.get('native_source_text_coverage')
            row['rasterized_prose'] = editability.get('rasterized_prose')
            row['visible_native_content_verified'] = editability.get('rendering', {}).get('ok')
        except Exception as exc:
            row['engine_seconds'] = time.perf_counter() - start
            detail = getattr(exc, 'detail', str(exc))
            dump(current / 'error.json', {'type': type(exc).__name__, 'detail': detail})
            row.update(ok=False, status=getattr(exc, 'status_code', None),
                       issues=detail.get('editability', {}).get('issues', [])
                       if isinstance(detail, dict) else [str(detail)],
                       message=detail.get('message') if isinstance(detail, dict) else str(detail))
            if isinstance(detail, dict) and detail.get('rendering', {}).get('ok') is False:
                row['issues'].append('native_rendering_failed')
        row['writer_seconds'] = writer_seconds
        if args.render and (current / 'writer_output.hwpx').exists():
            try:
                import rhwp
                native = rhwp.parse(str(current / 'writer_output.hwpx'))
                images = current / 'rendered'
                images.mkdir(exist_ok=True)
                for index in range(native.page_count):
                    (images / f'page{index + 1:02}.png').write_bytes(bytes(native.render_png(index)))
                row['diagnostic_render_pages'] = native.page_count
            except Exception as exc:
                row['diagnostic_render_error'] = str(exc)
        rows.append(row)
        dump(out / 'summary.json', rows)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    return 0 if all(r['ok'] and not r.get('diagnostic_render_error') for r in rows) else 2


if __name__ == '__main__':
    raise SystemExit(main())
