# -*- coding: utf-8 -*-
"""Download the pinned rhwp command line tool into packaging/rhwp-cli/.

The CLI (MIT, https://github.com/edwardkim/rhwp) adds HWP export and
distribution-HWP unlocking (app/rhwp_cli.py). It is not committed; this script
fetches the release for the current platform and checks its SHA-256.
Hashes are those of the official v0.8.7 release assets (the same pins Filee
uses in src/Filee.Engines/Infrastructure/engines.json).

  python scripts/fetch_rhwp_cli.py            # current platform
  python scripts/fetch_rhwp_cli.py --platform windows-x86_64
"""
from __future__ import annotations

import argparse
import hashlib
import io
import platform
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "packaging" / "rhwp-cli"
VERSION = "0.8.7"
BASE = f"https://github.com/edwardkim/rhwp/releases/download/v{VERSION}/rhwp-v{VERSION}-"
RELEASES = {
    "windows-x86_64": ("windows-x86_64.zip", "F7AC326E98F595AE8FECD8DA7A614EE9A37DB77BDF938782A8E07C9DA473EC6F"),
    "linux-x86_64": ("linux-x86_64.tar.gz", "F1E541A25CFE76B6BC1DAF18BF9C1F9A5AC5E03E2C01B188DAAF54107214F631"),
    "linux-aarch64": ("linux-aarch64.tar.gz", "C4A70F5ED11B99586EE89D1AC9069145D58A0831D00E87858BB01626E2EBF313"),
    "macos-x86_64": ("macos-x86_64.tar.gz", "07B1A5EA570E410D1B52B4D848A94F00C64674E84004883C62EFAD7DAAB61DA4"),
    "macos-aarch64": ("macos-aarch64.tar.gz", "6ED46AA63F6D10C447842999F73ABC59CF9586C5645FEFC5E763BD6A6D43662D"),
}


def current_platform() -> str:
    machine = platform.machine().lower()
    arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    if sys.platform == "win32":
        return "windows-x86_64"
    return f"{'macos' if sys.platform == 'darwin' else 'linux'}-{arch}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--platform", choices=sorted(RELEASES), default=current_platform())
    args = parser.parse_args()
    suffix, expected = RELEASES[args.platform]
    url = BASE + suffix
    print(f"download {url}")
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - pinned https URL
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest().upper()
    if digest != expected:
        print(f"SHA-256 mismatch: {digest} != {expected}", file=sys.stderr)
        return 1
    executable = "rhwp.exe" if args.platform.startswith("windows") else "rhwp"
    if suffix.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = [name for name in archive.namelist() if Path(name).name in {executable, "LICENSE"}]
            files = {Path(name).name: archive.read(name) for name in members}
    else:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            files = {}
            for member in archive.getmembers():
                name = Path(member.name).name
                if member.isfile() and name in {executable, "LICENSE"}:
                    files[name] = archive.extractfile(member).read()
    if executable not in files:
        print(f"{executable} not found in the archive", file=sys.stderr)
        return 1
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)
    (TARGET / executable).write_bytes(files[executable])
    (TARGET / executable).chmod(0o755)
    if "LICENSE" in files:
        (TARGET / "LICENSE").write_bytes(files["LICENSE"])
    print(f"rhwp {VERSION} -> {TARGET / executable}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
