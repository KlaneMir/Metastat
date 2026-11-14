"""Demo mode (DEMO=true): the program runs without a connection to Meta, on made-up data.

Turn it on with the DEMO=true environment variable or a DEMO=true line in the .env file next to the program.
Demo data has its own folder (data-demo or %LOCALAPPDATA%\\Metastat-demo), so it never mixes with real data.

On the first start the program adds two accounts of the built-in Meta Graph API simulator (made-up Facebook pages,
Instagram accounts and posts with dates, views, followers, likes, shares and comments)
and builds their history for the last few months. Post images are placeholders with a "DEMO" label.
"Sync" then works as usual, only it talks to the simulator.
"""
from __future__ import annotations

from pathlib import Path

from metastat import paths

ACCOUNTS = ((1, "Demo: North Agency"), (2, "Demo: South Agency"))  # (simulator account, name)
CAMPAIGNS = 6   # campaigns per account, including deliberate traps (IG account invisible to the API, broken history)
DAYS = 120      # days of history


def enabled() -> bool:
    return paths.demo()


def setup(st) -> list[dict]:
    """Empty demo folder: adds the demo accounts and returns them (build_history builds the history). Otherwise does nothing."""
    if st.connections():
        return []
    from metastat.fakeapi import tools
    added = [tools.add_connection(st, n, limit=CAMPAIGNS, name=name) for n, name in ACCOUNTS]
    st.set_active(added[0]["id"])
    return added


def build_history(home: Path, conns: list[dict], out=print, days: int = DAYS) -> int:
    from metastat import config
    from metastat.fakeapi import tools
    code = 0
    for c in conns:
        out(f"Preparing demo data: {c['name']}")
        s = config.load_store(c["id"], home=home)
        code = max(code, tools.history(s, days=days, step=7, out=out))
    out("Demo data ready.")
    return code
