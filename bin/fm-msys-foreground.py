#!/usr/bin/env python3
"""Read one MSYS/Cygwin tty's foreground group, preserving process identity.

Usage: fm-msys-foreground.py /dev/ptyN
Print pid, pgrp, foreground-pgrp and comm in the existing tmux probe format.
Only that tty's foreground group qualifies; background children never do.
A failed tty/kernel read exits nonzero, rather than claiming an empty group.
"""
from __future__ import annotations
import os
from pathlib import Path
import sys


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith("/dev/"):
        return 2
    try:
        fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            foreground = os.tcgetpgrp(fd)
        finally:
            os.close(fd)
        if foreground <= 0:
            return 1
        rows = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                record = (entry / "stat").read_text()
                opening, closing = record.index("("), record.rindex(")")
                fields = record[closing + 1:].split()
                # stat's fields after pid/comm are state, ppid, pgrp, session,
                # tty_nr, tpgid, ... . Kernel process-group identity is global.
                group = int(fields[2])
                if group != foreground:
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
    except (OSError, ValueError, AttributeError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
