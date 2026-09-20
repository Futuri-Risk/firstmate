#!/usr/bin/env python3
"""One-time, non-destructive Forge-to-FirstMate migration.

Usage: FM_HOME=/home fm-forge-cutover.py plan|apply --manifest /private/file.json
       apply requires --quiesced; --start starts every provisioned Secondmate.
       fm-forge-cutover.py restore --manifest FILE --destination /new/empty/path
Manifest schema fm-forge-cutover.v1: id, backup_root, legacy_roots (absolute
paths), projects ({project,url,source}). Source projects must be standalone
Git checkouts, not linked worktrees. Legacy paths are never deleted or edited.
The operator must stop the old orchestrator before --quiesced; this command
never guesses which unrelated sessions or services it may kill.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from fm_forge import (ForgeError, atomic_json, identifier, lock, now, read_json,
                      require_home, run, safe_child)

ROOT = Path(__file__).resolve().parent


def inventory(root):
    entries = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            relative = str(path.relative_to(root))
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                entries[relative] = {"type": "link", "target": os.readlink(path)}
            elif stat.S_ISDIR(mode):
                entries[relative] = {"type": "directory"}
            elif stat.S_ISREG(mode):
                digest = hashlib.sha256()
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                entries[relative] = {"type": "file", "sha256": digest.hexdigest(), "size": path.stat().st_size}
            else:
                raise ForgeError("source contains a live socket/device or other unsupported filesystem object; quiesce it first")
    return entries


def disjoint(a, b):
    return a != b and not a.is_relative_to(b) and not b.is_relative_to(a)


def plan(home, path):
    manifest = read_json(path)
    if not isinstance(manifest, dict) or manifest.get("schema") != "fm-forge-cutover.v1":
        raise ForgeError("invalid cutover manifest schema")
    identifier(manifest.get("id"), "cutover ID")
    backup = Path(manifest["backup_root"])
    if not backup.is_absolute() or backup.is_symlink():
        raise ForgeError("backup_root must be an absolute non-symlink path")
    backup = backup.resolve()
    if not disjoint(home, backup):
        raise ForgeError("rollback material must be outside the FirstMate home")
    projects = manifest.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ForgeError("cutover requires at least one project")
    seen = set()
    for project in projects:
        name = identifier(project["project"], "project")
        if name in seen:
            raise ForgeError("duplicate project in cutover manifest")
        seen.add(name)
        source = Path(project["source"])
        if not source.is_absolute() or source.is_symlink():
            raise ForgeError("project source must be an absolute physical checkout")
        source = source.resolve()
        if not source.is_dir() or not (source / ".git").is_dir() or (source / ".git").is_symlink():
            raise ForgeError("source must be a standalone Git checkout; preserve linked worktrees separately before migration")
        if Path(run("git", "rev-parse", "--show-toplevel", cwd=source).strip()).resolve() != source:
            raise ForgeError("source is not the project root")
        if not disjoint(source, backup) or not disjoint(source, home):
            raise ForgeError("source, destination home and backup must not overlap")
        if (source / ".git/index.lock").exists():
            raise ForgeError("source Git index is locked; do not copy an active Git operation")
        project["source"] = str(source)
    roots = manifest.get("legacy_roots", [])
    if not isinstance(roots, list):
        raise ForgeError("legacy_roots must be a list")
    for value in roots:
        source = Path(value)
        if not source.is_absolute() or source.is_symlink() or not source.is_dir():
            raise ForgeError("legacy roots must be existing absolute physical directories")
        if not disjoint(source.resolve(), backup) or not disjoint(source.resolve(), home):
            raise ForgeError("legacy root overlaps the new system or rollback destination")
    manifest["backup_root"] = str(backup)
    return manifest


def private_tree(root):
    for directory, dirs, files in os.walk(root, followlinks=False):
        os.chmod(directory, 0o700)
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                executable = path.stat().st_mode & 0o111
                os.chmod(path, 0o700 if executable else 0o600)


def copied_exact(source, destination):
    before = inventory(source)
    shutil.copytree(source, destination, symlinks=True)
    if inventory(source) != before or inventory(destination) != before:
        raise ForgeError("source changed during copying or copied bytes differ; retain both copies and retry after quiescing")
    return before


def apply(home, manifest, start):
    key = manifest["id"]
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    receipt_path = safe_child(home, f"state/cutovers/{key}.json")
    backup = Path(manifest["backup_root"])
    with lock(safe_child(home, f"state/cutovers/.{key}.lock")):
        receipt = read_json(receipt_path, {})
        if receipt and receipt.get("manifest_digest") != digest:
            raise ForgeError("cutover ID is already bound to another manifest")
        if receipt.get("state") in ("source-prepared", "fleet-started") and not start:
            return receipt
        if not receipt:
            for project in manifest["projects"]:
                if safe_child(home, f"projects/{project['project']}").exists():
                    raise ForgeError("destination already contains a project; do not overwrite it during cutover")
            if backup.exists() and any(backup.iterdir()):
                raise ForgeError("backup destination is nonempty; use a new rollback directory")
            backup.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(backup, 0o700)
            receipt = {"schema": "fm-forge-cutover-result.v1", "manifest_digest": digest,
                       "state": "copying", "created_at": now(), "projects": [], "copied_projects": [],
                       "rollback_manifest": str(backup / "manifest.json")}
            atomic_json(receipt_path, receipt)
        rollback = read_json(backup / "manifest.json", {"schema": "fm-forge-rollback.v1", "entries": []})
        sources = [(f"legacy-{index}", Path(source)) for index, source in enumerate(manifest["legacy_roots"])]
        sources += [("project-" + row["project"], Path(row["source"])) for row in manifest["projects"]]
        for name, source in sources:
            saved = next((row for row in rollback["entries"] if row["name"] == name), None)
            destination = backup / name
            if saved:
                if inventory(destination) != saved["inventory"]:
                    raise ForgeError("rollback copy has changed; refusing to proceed")
                continue
            if destination.exists():
                raise ForgeError("unfinished rollback copy exists; inspect it rather than overwriting")
            entries = copied_exact(source, destination)
            private_tree(destination)
            rollback["entries"].append({"name": name, "original": str(source), "inventory": entries})
            atomic_json(backup / "manifest.json", rollback)
        for project in manifest["projects"]:
            name = project["project"]
            destination = safe_child(home, "projects/" + name)
            if name not in receipt["copied_projects"]:
                if destination.exists():
                    raise ForgeError("unrecorded destination project exists; preserving it for reconciliation")
                destination.parent.mkdir(parents=True, exist_ok=True)
                staged = Path(tempfile.mkdtemp(prefix=".cutover-", dir=destination.parent))
                staged.rmdir()
                copied_exact(Path(project["source"]), staged)
                os.replace(staged, destination)
                receipt["copied_projects"].append(name)
                atomic_json(receipt_path, receipt)
            command = [sys.executable, str(ROOT / "fm-project-onboard.py"), "--project", name, "--url", project["url"]]
            if start:
                command.append("--start")
            result = json.loads(run(*command, timeout=180))
            receipt["projects"] = [row for row in receipt["projects"] if row["project"] != name] + [result]
            atomic_json(receipt_path, receipt)
        receipt.update(state="fleet-started" if start else "source-prepared", completed_at=now(),
                       legacy_policy="preserved; operator affirmed old orchestrator quiesced; no old session identities imported")
        atomic_json(receipt_path, receipt)
        return receipt


def restore(manifest, destination):
    target = Path(destination)
    if not target.is_absolute() or target.exists() or target.is_symlink():
        raise ForgeError("restore destination must be a new absolute directory")
    backup = Path(manifest["backup_root"])
    if not disjoint(target.resolve(), backup):
        raise ForgeError("restore destination must not overlap rollback material")
    rollback = read_json(backup / "manifest.json")
    if not rollback or rollback.get("schema") != "fm-forge-rollback.v1":
        raise ForgeError("rollback manifest is unavailable")
    for row in rollback["entries"]:
        identifier(row["name"], "rollback entry")
        source = backup / row["name"]
        if source.is_symlink() or inventory(source) != row["inventory"]:
            raise ForgeError("rollback evidence differs; refusing to restore altered bytes")
    target.mkdir(mode=0o700, parents=True)
    for row in rollback["entries"]:
        shutil.copytree(backup / row["name"], target / row["name"], symlinks=True)
    return {"state": "restored-to-new-directory", "destination": str(target)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("plan", "apply", "restore"))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--quiesced", action="store_true")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--destination")
    try:
        args = parser.parse_args()
        home = require_home()
        manifest = plan(home, args.manifest)
        if args.command == "plan":
            result = {"state": "planned", "projects": [row["project"] for row in manifest["projects"]],
                      "backup_root": manifest["backup_root"], "mutations": False}
        elif args.command == "restore":
            if not args.destination:
                raise ForgeError("restore requires --destination")
            result = restore(manifest, args.destination)
        else:
            if not args.quiesced:
                raise ForgeError("stop the old orchestrator before explicitly passing --quiesced")
            result = apply(home, manifest, args.start)
        print(json.dumps(result))
        return 0
    except (ForgeError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FirstMate cutover: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
