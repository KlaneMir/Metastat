"""Where the program keeps its data: next to the program (portable version).

- EXE: the folder with Metastat.exe → data in <folder>\\data
- from source: the project folder → data in <project>\\data
METASTAT_DATA overrides the data folder (tests).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]  # src/metastat/paths.py → project


def home() -> Path:
    """The data folder.

    - METASTAT_DATA: the given folder (tests);
    - from source, or the portable version (a "data" folder already sits next to Metastat.exe): <program>\\data;
    - installed program: %LOCALAPPDATA%\\Metastat, separately for each Windows account. Tokens are encrypted
      per account anyway (DPAPI), and the program folder (e.g. Program Files) may be read-only.
    """
    env = os.environ.get("METASTAT_DATA")
    if env:
        return Path(env).resolve()
    suffix = "-demo" if demo() else ""  # demo mode has its own folder: made-up data never mixes with real data
    portable = app_dir() / f"data{suffix}"
    if not frozen() or (app_dir() / "data").is_dir():
        return portable
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / f"Metastat{suffix}"


def demo() -> bool:
    """Demo mode: the DEMO=true environment variable or a DEMO=true line in the .env file next to the program."""
    value = os.environ.get("DEMO")
    if value is None:
        env = app_dir() / ".env"
        if env.is_file():
            from dotenv import dotenv_values
            value = dotenv_values(env).get("DEMO")
    return str(value or "").strip().lower() in ("1", "true", "tak", "yes", "on")


def ensure_dir(path: Path) -> Path:
    """Creates the folder (with its parents) when it is missing.

    Does not use Path.mkdir(exist_ok=True): after Windows answers "already exists", that one also asks "is it a
    folder?", and the second question can briefly give a false "no" while an antivirus scans a freshly created
    folder (e.g. two program starts at once). "Already exists" is enough: if a file had that name, the first
    write into the folder would report a clear error anyway.
    """
    try:
        os.mkdir(path)
    except FileExistsError:
        pass
    except FileNotFoundError:
        if path.parent == path:
            raise
        ensure_dir(path.parent)
        try:
            os.mkdir(path)
        except FileExistsError:
            pass
    return path


def launcher() -> list[str]:
    """The command that starts the program without a console window (for Task Scheduler)."""
    if frozen():
        return [sys.executable]
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    return [str(windowless if windowless.exists() else exe), "-m", "metastat"]
