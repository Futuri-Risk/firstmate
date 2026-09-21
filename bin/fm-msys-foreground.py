#!/usr/bin/env python3
"""Read one MSYS/Cygwin pane's inferred foreground process group.

Usage: fm-msys-foreground.py /dev/ptyN <pane-pid> <tmux-current-command>
Print pid, pgid, inferred-foreground-pgid and comm in the tmux probe format.

MSYS2 exposes each process's controlling tty and process group through /proc,
but its stat tpgid is -1 and opening /dev/ptyN externally cannot answer
tcgetpgrp(). tmux already resolves the pane's foreground command internally.
Bind that command back to the processes on the exact pane tty using comm and
argv[0], require one unique matching process group, then emit only that group.
If the command cannot identify one group and more than one group exists, fail
closed rather than accidentally promoting a background job to foreground.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys


def basename(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def main() -> int:
    if len(sys.argv) != 4 or not sys.argv[1].startswith("/dev/"):
        return 2
    target_tty = sys.argv[1].rstrip("/")
    pane_pid = sys.argv[2]
    current = basename(sys.argv[3])
    if not pane_pid.isdecimal() or not current:
        return 2

    records: list[tuple[str, int, str, str]] = []
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                if (entry / "ctty").read_text().strip() != target_tty:
                    continue
                record = (entry / "stat").read_text()
                opening, closing = record.index("("), record.rindex(")")
                fields = record[closing + 1 :].split()
                group = int(fields[2])
                if group <= 0:
                    continue
                comm = record[opening + 1 : closing].replace("\n", " ").replace("\r", " ")
                raw = (entry / "cmdline").read_bytes()
                argv0 = raw.split(b"\0", 1)[0].decode(errors="replace") if raw else ""
                records.append((entry.name, group, comm, argv0))
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            except (OSError, ValueError, IndexError):
                return 1
    except OSError:
        return 1

    if not records:
        return 1

    candidate_groups = {
        group
        for _pid, group, comm, argv0 in records
        if current in {basename(comm), basename(argv0)}
    }
    if len(candidate_groups) == 1:
        foreground = next(iter(candidate_groups))
    elif len(candidate_groups) == 0:
        all_groups = {group for _pid, group, _comm, _argv0 in records}
        if len(all_groups) != 1:
            return 1
        foreground = next(iter(all_groups))
    else:
        return 1

    rows = [
        f"{pid}\t{group}\t{foreground}\t{comm}"
        for pid, group, comm, _argv0 in records
        if group == foreground
    ]
    if not rows:
        return 1
    print("\n".join(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
