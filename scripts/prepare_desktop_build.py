"""Create build-time icon and notices, never copy user data or installed fonts."""
from pathlib import Path
import importlib.metadata as metadata
import shutil
import sys
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parent.parent
licenses = root / "tmp" / "desktop-build" / "licenses"
licenses.mkdir(parents=True, exist_ok=True)
notes = ["HWP Make Basic - bundled third-party components", ""]
for dist in sorted(metadata.distributions(), key=lambda x: x.metadata["Name"].lower()):
    name = dist.metadata["Name"]
    notes.append(f"{name} {dist.version}")
    for entry in dist.files or []:
        if any(token in str(entry).lower() for token in ("license", "copying", "notice")):
            path = Path(dist.locate_file(entry))
            if path.is_file() and path.suffix.lower() not in {".py", ".pyc", ".pyd"}:
                target = licenses / name / str(entry).replace("..", "_")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
for path in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
    if path.is_file():
        shutil.copyfile(path, licenses / "Python-LICENSE.txt")
shutil.copytree(root / "app" / "_vendor" / "hwpx" / "_VENDOR_LICENSES", licenses / "python-hwpx", dirs_exist_ok=True)
(licenses / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(notes), encoding="utf-8")
icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(icon)
draw.rounded_rectangle((8, 8, 248, 248), radius=48, fill="#505ac9")
draw.rectangle((66, 57, 93, 199), fill="white")
draw.rectangle((163, 57, 190, 199), fill="white")
draw.rectangle((90, 113, 167, 140), fill="white")
icon.save(root / "packaging" / "app.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
