#!/usr/bin/env python3
"""Send one existing captain hold through the native FirstMate mail plane.

Usage: FM_HOME=/home fm-captain-email.py TASK --to EMAIL
Only active native captain holds qualify. Repeated invocation is deduplicated
by the hold lifecycle identity. SMTP ambiguity retains an uncertain receipt;
--retry-uncertain explicitly retries it without resolving the underlying hold.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from fm_forge import (ForgeError, atomic_json, identifier, lock, now, read_json,
                      require_home, run, safe_child)

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task")
    parser.add_argument("--to", required=True)
    parser.add_argument("--retry-uncertain", action="store_true")
    try:
        args = parser.parse_args()
        home = require_home()
        if (home / ".fm-secondmate-parent").exists():
            raise ForgeError("Secondmate outcomes must use the native parent channel; send captain mail from the parent home")
        task = identifier(args.task, "task ID")
        if any(c in args.to for c in "\r\n") or "@" not in args.to:
            raise ForgeError("invalid email recipient")
        # Upstream owns whether this is an active captain hold and its identity.
        identity = run(str(ROOT / "fm-captain-hold.sh"), "open", task, "--identity").strip()
        if not identity:
            raise ForgeError("task is not an active captain hold")
        key = hashlib.sha256((task + "\0" + identity + "\0" + args.to).encode()).hexdigest()
        receipt = safe_child(home, f"state/captain-email/{key}.json")
        with lock(safe_child(home, f"state/captain-email/.{key}.lock")):
            previous = read_json(receipt, {})
            if previous.get("state") == "sent":
                print(json.dumps({"task": task, "state": "already-sent"}))
                return 0
            if previous.get("state") in ("sending", "uncertain") and not args.retry_uncertain:
                raise ForgeError("previous SMTP outcome is uncertain; inspect it before explicitly retrying")
            body = run("tasks-axi", "show", task, cwd=home)
            atomic_json(receipt, {"task": task, "state": "sending", "identity": identity, "at": now()})
            try:
                run(str(ROOT / "fm-mail.sh"), "send", args.to,
                    "FirstMate needs a decision: " + task, "-", input=body)
            except ForgeError:
                atomic_json(receipt, {"task": task, "state": "uncertain", "identity": identity, "at": now()})
                raise
            atomic_json(receipt, {"task": task, "state": "sent", "identity": identity, "at": now()})
        print(json.dumps({"task": task, "state": "sent"}))
        return 0
    except (ForgeError, OSError, ValueError) as exc:
        print(f"FirstMate email: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
