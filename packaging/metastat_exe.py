"""Entry point of Metastat.exe: without arguments it opens the program; `Metastat.exe sync` is the Task Scheduler job."""
import sys

from metastat.cli import main

if __name__ == "__main__":
    sys.exit(main())
