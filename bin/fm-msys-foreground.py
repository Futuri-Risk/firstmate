#!/usr/bin/env python3
"""Read one MSYS/Cygwin tty's foreground group, preserving process identity.

Usage: fm-msys-foreground.py /dev/ptyN
Print pid, pgrp, foreground-pgrp and comm in the existing tmux probe format.
Only processes attached to that exact controlling tty whose pgrp equals the
tty's recorded tpgid qualify, so background children never do.
A failed proc/kernel read exits nonzero, rather than claiming an empty group.
"""
from __future__ import annotations

from pathlib import Path
import sys


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith("/dev/"):
        return 2
    target_tty = sys.argv[1].rstrip("/")
    rows = []
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                ctty = (entry / "ctty").read_text().strip()
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            except OSError:
                return 1
            if ctty != target_tty:
                continue
            try:
                record = (entry / "stat").read_text()
                opening, closing = record.index("("), record.rindex(")")
                fields = record[closing + 1:].split()
                # Fields after pid/comm are state, ppid, pgrp, session, tty_nr,
                # tpgid, ... . Cygwin exposes both process group and the
                # controlling tty's foreground process group in this record.
                group = int(fields[2])
                foreground = int(fields[5])
                if foreground <= 0 or group != foreground:
                    continue
                comm = record[opening + 1:closing].replace("\n", " ").replace("\r", " ")
                rows.append(f"{entry.name}\t{group}\t{foreground}\t{comm}")
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            except (OSError, ValueError, IndexError):
                return 1
        if not rows:
            return 1
        print("\n".join(rows))
        return 0
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
