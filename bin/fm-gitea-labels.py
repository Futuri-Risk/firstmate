#!/usr/bin/env python3
"""Apply living semantic labels without replacing an issue's manual labels.

Usage: FM_HOME=/home fm-gitea-labels.py --project NAME --issue N --label topic:NAME
       [--label skill:NAME ...] [--alias topic:OLD=topic:NAME]
       fm-gitea-labels.py --project NAME --backfill
Backfill normalizes configured aliases on open issues only. New semantic
classification is supplied by FirstMate as labels, never guessed by this tool.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import quote
from fm_forge import (ForgeError, Gitea, atomic_json, lock, project_binding,
                      read_json, require_home, safe_child)


def semantic(value):
    value = unicodedata.normalize("NFKC", value).strip().casefold()
    if ":" not in value:
        raise ForgeError("semantic labels require a topic: or skill: namespace")
    namespace, term = value.split(":", 1)
    term = re.sub(r"[\s_-]+", "-", term).strip("-")
    if namespace not in ("topic", "skill") or not re.fullmatch(r"[\w][\w.-]{0,59}", term):
        raise ForgeError("invalid semantic label")
    return namespace + ":" + term


def target(value, aliases):
    visited = set()
    while value in aliases:
        if value in visited:
            raise ForgeError("semantic alias cycle")
        visited.add(value)
        value = aliases[value]
    return value


def apply(api, issue, requested, aliases):
    current = api.request("GET", f"/issues/{issue}/labels")
    if not isinstance(current, list):
        raise ForgeError("issue labels were not an array")
    repository = list(api.pages("/labels"))
    index = {}
    for label in repository:
        try:
            key = semantic(label["name"])
        except ForgeError:
            continue
        if key in index and index[key]["id"] != label["id"]:
            raise ForgeError("repository contains ambiguous canonical labels; resolve duplicates before applying")
        index[key] = label
    desired = {target(semantic(value), aliases) for value in requested}
    obsolete = []
    for label in current:
        try:
            old = semantic(label["name"])
        except ForgeError:
            continue
        canonical = target(old, aliases)
        if canonical != old:
            desired.add(canonical)
            obsolete.append(label)
    additions = []
    for canonical in sorted(desired):
        if canonical not in index:
            try:
                created = api.request("POST", "/labels", {"name": canonical, "color": "4B70DD",
                    "description": "FirstMate semantic navigation"})
            except ForgeError:
                # A concurrent home may have created it. Only accept exact identity.
                matches = [row for row in api.pages("/labels") if row.get("name") == canonical]
                if len(matches) != 1:
                    raise
                created = matches[0]
            index[canonical] = created
        label_id = int(index[canonical]["id"])
        if label_id not in {int(row["id"]) for row in current}:
            additions.append(label_id)
    if additions:
        api.request("POST", f"/issues/{issue}/labels", {"labels": additions})
    # Add before removing aliases; never PUT-replace the entire set.
    for old in obsolete:
        if target(semantic(old["name"]), aliases) in desired:
            api.request("DELETE", f"/issues/{issue}/labels/{int(old['id'])}")
    return {"issue": issue, "added": additions, "normalized": [x["name"] for x in obsolete]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--issue", type=int)
    group.add_argument("--backfill", action="store_true")
    parser.add_argument("--label", action="append", default=[])
    parser.add_argument("--alias", action="append", default=[])
    try:
        args = parser.parse_args()
        home = require_home()
        binding = project_binding(home, args.project)
        api = Gitea(binding["url"])
        path = safe_child(home, f"config/semantic-labels/{args.project}.json")
        with lock(safe_child(home, f"state/.semantic-labels-{args.project}.lock")):
            registry = read_json(path, {"schema": "fm-semantic-labels.v1", "aliases": {}})
            aliases = dict(registry["aliases"])
            for pair in args.alias:
                old, separator, new = pair.partition("=")
                if not separator:
                    raise ForgeError("alias must use OLD=CANONICAL")
                old, new = semantic(old), semantic(new)
                if old != new:
                    aliases[old] = new
            for key in aliases:
                target(key, aliases)
            issues = [int(row["number"]) for row in api.open_issues()] if args.backfill else [args.issue]
            if any(number <= 0 for number in issues):
                raise ForgeError("issue number must be positive")
            if args.backfill and args.label:
                raise ForgeError("backfill normalizes aliases; it must not blanket-classify every issue")
            registry["aliases"] = aliases
            atomic_json(path, registry)
            print(json.dumps([apply(api, number, args.label, aliases) for number in issues]))
        return 0
    except (ForgeError, OSError, ValueError, KeyError) as exc:
        print(f"FirstMate labels: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
