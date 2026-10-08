"""Collect real-host Basic runtime evidence without changing user settings.

Run this on the host being assessed. Platform simulations are not Mac evidence.
Each probe runs in an isolated subprocess with disposable data/settings paths.
Import/render/TAB checks do not establish whole-paper conversion quality,
desktop app packaging, or editing in Hancom/Word.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'HWP_BASIC_RUNTIME_JSON='
IMPORTS = {'pymupdf': ('fitz', 'PyMuPDF'), 'pillow': ('PIL.Image', 'pillow'),
           'lxml': ('lxml.etree', 'lxml'), 'numpy': ('numpy', 'numpy'),
           'docx': ('docx', 'python-docx'), 'olefile': ('olefile', 'olefile'),
           'fastapi': ('fastapi', 'fastapi'), 'httpx': ('httpx', 'httpx'),
           'renderer': ('rhwp', 'rhwp-python')}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def probe(name, hwpx, check_tk_window):
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT/'app/_vendor'))
    if name in IMPORTS:
        module_name, distribution = IMPORTS[name]
        module = importlib.import_module(module_name)
        result = {'ok': True, 'module': module_name,
                  'module_path': getattr(module, '__file__', None),
                  'version': metadata.version(distribution)}
        if name == 'renderer':
            native = importlib.import_module('rhwp._rhwp')
            path = Path(native.__file__)
            result['native_library'] = {'path': str(path), 'sha256': digest(path),
                                        'file_magic_hex': path.read_bytes()[:8].hex()}
            result['binding_version_attribute'] = str(getattr(module, '__version__', 'unavailable'))
        return result
    if name == 'tk':
        import tkinter as tk
        result = {'ok': True, 'tk_version': tk.TkVersion, 'tcl_version': tk.TclVersion,
                  'window_creation_requested': check_tk_window, 'window_created': False}
        if check_tk_window:
            window = tk.Tk()
            try:
                window.withdraw()
                window.update_idletasks()
                result['window_created'] = True
                result['actual_tcl_patchlevel'] = str(window.tk.call('info', 'patchlevel'))
            finally:
                window.destroy()
        return result
    if name == 'desktop_import':
        import run_desktop
        return {'ok': True, 'launcher_ui_font': run_desktop.UI_FONT,
                'launcher_data_dir': str(run_desktop.default_data_dir()),
                'gui_started': False, 'worker_started': False}
    if name == 'data_paths':
        path = Path(os.environ['HWP_MAKE_DATA_DIR'])
        path.mkdir(parents=True, exist_ok=True)
        target = path/'한글 공백 쓰기 확인.txt'
        target.write_text('HWP Make runtime', encoding='utf-8')
        require(target.read_text(encoding='utf-8') == 'HWP Make runtime', 'Isolated Unicode-path read/write failed')
        target.unlink()
        return {'ok': True, 'isolated_unicode_path_read_write': True,
                'real_user_data_dir_tested': False}
    if name == 'calibration_fonts':
        from app.pdf_layout_writer import _CALIB_FONT_FILES, _calib_font
        faces = []
        for face in _CALIB_FONT_FILES:
            font = _calib_font(face)
            faces.append({'requested_face': face, 'available': font is not None,
                          'actual_family_style': list(font.getname()) if font is not None else None})
        return {'ok': True, 'faces': faces,
                'configured_search_root': str(Path(os.environ.get('SystemRoot', r'C:\Windows'))/'Fonts'),
                'font_equivalence_verified': False}
    if name == 'native_document':
        import rhwp
        from hwpx import HwpxDocument
        from hwpx.tools import native_line_metrics
        from app.pdf_question_rendering import _visible_svg_text
        if hwpx is not None:
            source = Path(hwpx).resolve()
            before = digest(source)
            data = source.read_bytes()
            document = HwpxDocument.open(source)
        else:
            source = None
            document = HwpxDocument.new()
            text = 'HWP Make runtime 테스트 123'
            document.add_paragraph(text)
            document.package.set_part('Preview/PrvText.txt', text.encode('utf-8'))
            data = document.to_bytes()
            before = hashlib.sha256(data).hexdigest()
        native = rhwp.Document.from_bytes(data)
        require(native.page_count > 0, 'Native document has no pages')
        pages = []
        for index in range(native.page_count):
            svg = native.render_svg(index)
            visible, hidden, unknown = _visible_svg_text(svg)
            require(bool(svg) and bool(visible.strip()), 'Native page has no visible text')
            pages.append({'page': index+1, 'svg_sha256': hashlib.sha256(svg.encode('utf-8')).hexdigest(),
                          'visible_characters': len(visible), 'hidden_characters': hidden,
                          'unknown_characters': unknown})
        pdf = bytes(native.render_pdf())
        require(pdf.startswith(b'%PDF-'), 'Native PDF rendering failed')
        header = document.headers[0].element
        hp = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
        paragraphs = [p for section in document.sections for p in section.element.iter(hp+'p')]
        candidates = [p for p in paragraphs if p.findall(hp+'run/'+hp+'tab')]
        # A short ordinary paragraph can seed the same actual four-page native
        # TAB capability probe even when a supplied file has no existing TABs.
        if not candidates:
            candidates = [p for p in paragraphs if p.findall(hp+'run/'+hp+'t')]
        capability = None
        supported = False
        attempted = 0
        for paragraph in candidates[:8]:
            attempted += 1
            context = native_line_metrics.optional_native_context(header, native=rhwp)
            provider = context.for_paragraph(paragraph) if context is not None else None
            if context is not None and context.capability_evidence is not None:
                capability = context.capability_evidence
            if provider is not None:
                supported = True
                break
        if source is not None:
            require(digest(source) == before, 'Supplied HWPX changed during read-only probe')
        return {'ok': True, 'input': str(source) if source else 'generated minimal HWPX',
                'input_sha256': before, 'input_unchanged': True, 'page_count': native.page_count,
                'pages': pages, 'pdf_sha256': hashlib.sha256(pdf).hexdigest(),
                'actual_fractional_tab_supported': supported, 'actual_tab_capability': capability,
                'actual_tab_capability_tested': capability is not None,
                'actual_tab_capability_status': ('supported' if supported else
                                                 'unsupported' if capability is not None else
                                                 'not_exercised_by_candidate_paragraphs'),
                'candidate_paragraphs_attempted': attempted, 'public_edit_tested': False,
                'whole_paper_quality_tested': False}
    raise ValueError('Unknown probe: '+name)


def run_probe(name, args, folder):
    command = [sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()), '--_probe', name]
    if args.hwpx is not None:
        command += ['--hwpx', str(args.hwpx.resolve())]
    if args.check_tk_window:
        command.append('--check-tk-window')
    env = dict(os.environ)
    # These probes never need provider credentials or the user's settings.
    for key in tuple(env):
        if key.startswith(('OPENAI_', 'GEMINI_', 'GOOGLE_')):
            env.pop(key)
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
               HWP_MAKE_DATA_DIR=str(folder/name/'data'),
               HWP_MAKE_SETTINGS_DIR=str(folder/name/'settings'))
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, text=True, encoding='utf-8',
                                errors='replace', capture_output=True, timeout=args.timeout)
        records = [line[len(MARKER):] for line in result.stdout.splitlines() if line.startswith(MARKER)]
        if len(records) != 1:
            return {'ok': False, 'probe': name, 'exit_code': result.returncode,
                    'error': 'Probe exited without exactly one structured result'}
        value = json.loads(records[0])
        value.update(probe=name, exit_code=result.returncode)
        value['ok'] = value.get('ok') is True and result.returncode == 0
        return value
    except subprocess.TimeoutExpired:
        return {'ok': False, 'probe': name, 'timed_out': True, 'timeout_seconds': args.timeout}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Save the JSON evidence report')
    parser.add_argument('--hwpx', type=Path, help='Optional real output; read/render without editing')
    parser.add_argument('--expect-platform', choices=('darwin', 'win32', 'linux'))
    parser.add_argument('--check-tk-window', action='store_true', help='Create and withdraw a real Tk window')
    parser.add_argument('--timeout', type=float, default=45, help='Seconds per isolated probe')
    parser.add_argument('--_probe', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._probe is not None:
        try:
            result = probe(args._probe, args.hwpx, args.check_tk_window)
        except Exception as error:
            result = {'ok': False, 'error_type': type(error).__name__, 'error': str(error)}
        print(MARKER+json.dumps(result, ensure_ascii=False), flush=True)
        return 0 if result['ok'] else 1
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if args.hwpx is not None and not args.hwpx.is_file():
        parser.error('--hwpx must be an existing file')
    names = [*IMPORTS, 'tk', 'desktop_import', 'data_paths', 'calibration_fonts', 'native_document']
    with tempfile.TemporaryDirectory(prefix='hwp-basic-runtime-', ignore_cleanup_errors=True) as folder:
        probes = [run_probe(name, args, Path(folder)) for name in names]
    failures = [p['probe'] for p in probes if not p['ok']]
    if args.expect_platform is not None and args.expect_platform != sys.platform:
        failures.append('expected_platform_mismatch')
    manifest_path = ROOT/'packaging/renderer/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    renderer = next(p for p in probes if p['probe'] == 'renderer')
    version_matches = renderer.get('version') == manifest['version']
    if renderer.get('ok') is True and not version_matches:
        failures.append('renderer_repository_version_mismatch')
    document = next(p for p in probes if p['probe'] == 'native_document')
    if (document.get('actual_tab_capability_tested') is True
            and document.get('actual_fractional_tab_supported') is False):
        failures.append('actual_fractional_tab_unsupported')
    custom_wheels = [str(p.relative_to(ROOT)) for p in (ROOT/'packaging/renderer/wheels').glob('*.whl')
                     if 'macosx' in p.name]
    report = {'scope': 'Real-host Basic prerequisites and bounded rendering diagnostics',
              'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'host': {'platform': sys.platform, 'system': platform.system(),
                       'machine': platform.machine(), 'python': sys.version,
                       'python_executable': sys.executable},
              'expected_platform': args.expect_platform,
              'runtime_prerequisites_ok': not failures, 'failures': failures, 'probes': probes,
              'renderer_repository_target': manifest['target'],
              'renderer_repository_version': manifest['version'],
              'renderer_loaded_version_matches_manifest': version_matches,
              'repository_custom_macos_wheels': custom_wheels,
              'mac_runtime_tested': sys.platform == 'darwin',
              'whole_paper_quality_verified': False, 'desktop_bundle_verified': False,
              'hancom_word_editing_verified': False, 'source_file_edited': False,
              'user_settings_read': False, 'script_sha256': digest(Path(__file__)),
              'renderer_manifest_sha256': digest(manifest_path)}
    text = json.dumps(report, ensure_ascii=False, indent=2)+'\n'
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
