# Build only in the dedicated environment created by build_desktop.ps1.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

root = Path(SPECPATH).parent
vendor = root / "app" / "_vendor"
sys.path.insert(0, str(vendor))
datas = [(str(root / "packaging" / "basic-static"), "static"),
         (str(root / "app" / "data"), "app/data"),
         (str(root / "packaging" / "app.ico"), "."),
         (str(root / "packaging" / "BASIC-README.txt"), "."),
         (str(root / "tmp" / "desktop-build" / "licenses"), "licenses")]
for package in ("hwpx", "docx", "rhwp", "pymupdf", "reportlab"):
    datas += collect_data_files(package)
hidden = collect_submodules("hwpx") + collect_submodules("rhwp")
hidden += ["app.desktop_selftest", "PIL._tkinter_finder", "pymupdf", "fitz"]
a = Analysis([str(root / "run_desktop.py")], pathex=[str(root), str(vendor)],
    binaries=collect_dynamic_libs("rhwp"), datas=datas, hiddenimports=hidden,
    excludes=["app.web_main", "app.web_worker", "app.web_store", "app.web_convert", "pytest"],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="HWP-Make-Basic",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, icon=str(root / "packaging" / "app.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="HWP-Make-Basic")
