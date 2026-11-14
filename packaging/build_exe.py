"""Builds Metastat.exe (PyInstaller, a folder with the program) into portable\\ in the project.

Run from the project folder:  .venv\\Scripts\\python packaging\\build_exe.py [--out FOLDER]

The result is a folder: Metastat.exe + _internal\\ (libraries, templates, test photos). The program data
(data\\: connections, databases, images, reports) is created next to Metastat.exe on the first start
and is not touched by later builds. Report PDFs use the installed Microsoft Edge.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent


def make_icon(path: Path) -> None:
    """Program icon: a blue circle with four bars (the same mark as in the program window)."""
    size = 256
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 0, size - 1, size - 1), fill=(8, 102, 255, 255))
    w = 21
    for x, top in ((76, 132), (112, 96), (148, 120), (184, 80)):
        d.rounded_rectangle((x - w // 2, top, x + w // 2, 172), radius=w // 2, fill="white")
    im.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


WORK = PROJECT / "build"
ICON = WORK / "metastat.ico"


def version() -> str:
    text = (PROJECT / "src" / "metastat" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([\d.]+)"', text).group(1)


def version_file(path: Path, ver: str) -> None:
    """Version and description shown in the Properties of Metastat.exe (Windows)."""
    nums = tuple(int(x) for x in (ver.split(".") + ["0", "0", "0"])[:4])
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', 'Metastat - Facebook and Instagram statistics'),
    StringStruct('ProductName', 'Metastat'),
    StringStruct('FileVersion', '{ver}'),
    StringStruct('ProductVersion', '{ver}'),
    StringStruct('OriginalFilename', 'Metastat.exe'),
    StringStruct('InternalName', 'Metastat')])]),
    VarFileInfo([VarStruct('Translation', [0x0409, 1200])])])
""", encoding="utf-8")


def build() -> Path:
    """Builds build\\dist\\Metastat (Metastat.exe + _internal) and returns that folder."""
    WORK.mkdir(exist_ok=True)
    make_icon(ICON)
    version_file(WORK / "version_info.txt", version())

    import PyInstaller.__main__
    PyInstaller.__main__.run([
        str(HERE / "metastat_exe.py"),
        "--name", "Metastat",
        "--windowed",            # no console window; errors go to data\logs\program-errors.log
        "--onedir",              # a folder instead of a single file: faster start, no unpacking to %TEMP%
        "--noconfirm", "--clean",
        "--icon", str(ICON),
        "--version-file", str(WORK / "version_info.txt"),
        "--paths", str(PROJECT / "src"),
        "--collect-data", "metastat",          # templates, CSS, schema.sql, report templates, test photos
        "--collect-submodules", "metastat",
        "--collect-submodules", "uvicorn",     # uvicorn loads loops and protocols by name
        "--collect-data", "tzdata",
        "--collect-all", "playwright",         # Playwright driver for the PDF and post cards (browser: Edge)
        "--exclude-module", "tkinter",
        "--exclude-module", "pytest",
        "--distpath", str(WORK / "dist"),
        "--workpath", str(WORK / "pyi"),
        "--specpath", str(WORK),
    ])
    return WORK / "dist" / "Metastat"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(PROJECT / "portable"),
                    help="output folder of the portable version (default: portable\\ in the project)")
    args = ap.parse_args()
    target = Path(args.out).resolve()
    built = build()
    target.mkdir(parents=True, exist_ok=True)
    (target / "data").mkdir(exist_ok=True)  # a "data" folder next to the EXE = portable version (data here, not in AppData)
    for item in ("Metastat.exe", "_internal"):  # data\ next to the program stays untouched
        dst = target / item
        if dst.is_dir():
            shutil.rmtree(dst)
        elif dst.exists():
            dst.unlink()
        src = built / item
        shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
    print(f"Done: {target / 'Metastat.exe'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
