"""Builds the installer: first Metastat.exe (PyInstaller), then Metastat-setup-<version>.exe (Inno Setup).

Run from the project folder:  .venv\\Scripts\\python packaging\\build_installer.py
Result: installer\\Metastat-setup-<version>.exe (in the project folder)
Requires Inno Setup 6 (ISCC.exe), e.g.: winget install --id JRSoftware.InnoSetup -e --scope user
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_exe  # noqa: E402


def iscc() -> str:
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
        for sub in ("Programs\\Inno Setup 6", "Inno Setup 6"):
            p = Path(base) / sub / "ISCC.exe"
            if base and p.is_file():
                return str(p)
    found = shutil.which("ISCC")
    if not found:
        sys.exit("Inno Setup 6 (ISCC.exe) not found. Install it: winget install --id JRSoftware.InnoSetup -e --scope user")
    return found


def main() -> int:
    ver = build_exe.version()
    dist = build_exe.build()
    out = HERE.parent / "installer"
    out.mkdir(exist_ok=True)
    r = subprocess.run([iscc(), f"/DAppVersion={ver}", f"/DDist={dist}", f"/O{out}", "/Qp",  # nosec B603
                        str(HERE / "metastat.iss")])
    if r.returncode:
        return r.returncode
    setup = out / f"Metastat-setup-{ver}.exe"
    print(f"Done: {setup} ({setup.stat().st_size / 1024 / 1024:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
