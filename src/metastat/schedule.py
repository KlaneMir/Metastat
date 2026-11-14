"""Tasks in Windows Task Scheduler: a daily sync and an hourly one for fresh posts.

The tasks have "run as soon as possible after a missed start" turned on, so if the computer was off
at 6:00, the sync starts right after it is turned on.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

from metastat.config import Settings
from metastat.paths import ensure_dir

TASKS = [
    {"name": r"Metastat\Daily sync", "args": ["sync"], "start": "06:00", "repeat": None,
     "desc": "Daily sync of FB and IG statistics for all Meta connections (pages, accounts, posts from 90 days, images)."},
    {"name": r"Metastat\Fresh posts sync", "args": ["sync", "--fresh"], "start": "08:00", "repeat": ("PT1H", "PT14H"),
     "desc": "Hourly from 8:00 to 22:00: readings of posts younger than 7 days (a view curve like in Business Suite)."},
]
SCHTASKS = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "schtasks.exe")  # full path

XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{desc}</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T{start}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>{repetition}
    </CalendarTrigger>
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{args}</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def write_xml(s: Settings) -> list[tuple[str, Path]]:
    from metastat import paths
    folder = (s.home or s.data_dir) / "tasks"
    ensure_dir(folder)
    cmd = paths.launcher()  # Metastat.exe or pythonw -m metastat (no console window)
    out = []
    for i, t in enumerate(TASKS, 1):
        rep = ""
        if t["repeat"]:
            rep = f"\n      <Repetition><Interval>{t['repeat'][0]}</Interval><Duration>{t['repeat'][1]}</Duration></Repetition>"
        xml = XML.format(desc=escape(t["desc"]), start=t["start"], repetition=rep,
                         command=escape(cmd[0]), args=escape(subprocess.list2cmdline(cmd[1:] + t["args"])),
                         workdir=escape(str(s.root)))
        path = folder / f"task{i}.xml"
        path.write_text(xml, encoding="utf-16")
        out.append((t["name"], path))
    return out


def commands(s: Settings, remove: bool = False) -> list[list[str]]:
    if remove:
        return [[SCHTASKS, "/Delete", "/F", "/TN", t["name"]] for t in TASKS]
    return [[SCHTASKS, "/Create", "/F", "/TN", name, "/XML", str(path)] for name, path in write_xml(s)]


def state() -> dict:
    """{task name: True/False/None}: whether the task exists (None = cannot be checked)."""
    out = {}
    for t in TASKS:
        try:
            r = subprocess.run([SCHTASKS, "/Query", "/TN", t["name"]], capture_output=True, timeout=5,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out[t["name"]] = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            out[t["name"]] = None
    return out


def run(s: Settings, *, install: bool, remove: bool, out=print) -> int:
    cmds = commands(s, remove=remove)
    if not (install or remove):
        out("These commands create the Task Scheduler tasks (run: metastat schedule --install):")
        for c in cmds:
            out("  " + subprocess.list2cmdline(c))
        return 0
    code = 0
    for c in cmds:
        # schtasks writes in the console code page (OEM), not UTF-8
        r = subprocess.run(c, capture_output=True, encoding="oem", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out((r.stdout or r.stderr).strip())
        code = code or r.returncode
    return code
