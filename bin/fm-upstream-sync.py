#!/usr/bin/env python3
"""Maintain a read-only source mirror and enqueue native upstream-update work.

Usage: FM_HOME=/home fm-upstream-sync.py configure --project NAME
       --upstream URL --branch main --mirror /absolute/bare.git [--period 900]
       fm-upstream-sync.py once --project NAME
       fm-upstream-sync.py arm --project NAME
The command never merges, resets or cleans a project. Its immutable target SHA
becomes a normal Secondmate task, which uses Treehouse and no-mistakes under
existing merge authority. The native process-event runner owns recurrence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
from fm_forge import (ForgeError, atomic_json, atomic_text, identifier, lock, now,
                      project_binding, read_json, require_home, run, safe_child)

ROOT = Path(__file__).resolve().parent


def native_env(home):
    env = {key: value for key, value in os.environ.items()
           if not (key.startswith("FM_") and key.endswith("_OVERRIDE"))}
    env["FM_HOME"] = str(home)
    return env


def upstream_url(value):
    if not value or any(c in value for c in "\r\n\0"):
        raise ForgeError("invalid upstream URL")
    parsed = urlsplit(value)
    if parsed.scheme in ("https", "ssh"):
        if not parsed.hostname or parsed.password or parsed.query or parsed.fragment:
            raise ForgeError("upstream must be an explicit credential-free Git URL")
        if parsed.scheme == "https" and parsed.username:
            raise ForgeError("HTTPS credentials belong in the Git credential manager")
    elif parsed.scheme == "file":
        if parsed.netloc not in ("", "localhost") or not Path(parsed.path).is_absolute():
            raise ForgeError("file upstream must name an absolute local repository")
    else:
        raise ForgeError("use https://, ssh://, or an absolute file:// upstream; custom Git helpers are not allowed")
    return value


def git(*args, cwd=None):
    return run("git", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
               "-c", "protocol.ssh.allow=always", "-c", "protocol.file.allow=always", *args, cwd=cwd)


def configure(home, args):
    binding = project_binding(home, args.project)
    upstream = upstream_url(args.upstream)
    branch = run("git", "check-ref-format", "--branch", args.branch).strip()
    mirror = Path(args.mirror)
    if not mirror.is_absolute() or mirror.is_symlink():
        raise ForgeError("mirror must be an absolute non-symlink location")
    mirror = mirror.resolve()
    project_root = safe_child(home, f"projects/{args.project}")
    child = Path(binding["secondmate_home"]).resolve()
    for protected in (home, child, project_root):
        if mirror == protected or mirror.is_relative_to(protected) or protected.is_relative_to(mirror):
            raise ForgeError("source mirror must not overlap a supervisor or working project")
    if not 60 <= args.period <= 86400:
        raise ForgeError("sync period must be between 60 and 86400 seconds")
    value = {"schema": "fm-upstream.v1", "project": args.project, "upstream": upstream,
             "branch": branch, "mirror": str(mirror), "period": args.period}
    path = safe_child(home, f"config/upstreams/{args.project}.json")
    previous = read_json(path)
    if previous and any(previous.get(key) != value[key] for key in ("upstream", "branch", "mirror")):
        raise ForgeError("upstream identity is already configured; review it before rebinding")
    atomic_json(path, value)
    return value


def once(home, project):
    binding = project_binding(home, project)
    configuration = read_json(safe_child(home, f"config/upstreams/{project}.json"))
    if not configuration or configuration.get("project") != project:
        raise ForgeError("configure the upstream first")
    upstream = upstream_url(configuration["upstream"])
    branch = run("git", "check-ref-format", "--branch", configuration["branch"]).strip()
    mirror = Path(configuration["mirror"])
    if not mirror.is_absolute() or mirror.is_symlink():
        raise ForgeError("invalid source mirror path")
    receipt_path = safe_child(home, f"state/upstream/{project}.json")
    with lock(safe_child(home, f"state/upstream/.{project}.lock")):
        receipt = read_json(receipt_path, {})
        try:
            if mirror.exists():
                if git("rev-parse", "--is-bare-repository", cwd=mirror).strip() != "true":
                    raise ForgeError("source cache is not a bare mirror")
                if git("config", "--get", "remote.origin.url", cwd=mirror).strip() != upstream:
                    raise ForgeError("source mirror belongs to another upstream")
                git("fetch", "--prune", "origin", cwd=mirror)
            else:
                mirror.parent.mkdir(parents=True, exist_ok=True)
                git("clone", "--mirror", "--no-hardlinks", "--", upstream, str(mirror))
            target = git("rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", cwd=mirror).strip()
        except ForgeError:
            receipt.update(freshness="stale", checked_at=now())
            atomic_json(receipt_path, receipt)
            raise
        project_root = safe_child(home, f"projects/{project}")
        fork_head = git("rev-parse", "HEAD", cwd=project_root).strip()
        receipt.update(freshness="fresh", checked_at=now(), upstream_head=target,
                       fork_head=fork_head, mirror=str(mirror))
        present = subprocess.run(["git", "merge-base", "--is-ancestor", target, fork_head],
                                 cwd=project_root, capture_output=True, timeout=30).returncode == 0
        if present:
            receipt.update(state="current")
            atomic_json(receipt_path, receipt)
            return receipt
        digest = hashlib.sha256((project + "\0" + upstream + "\0" + target).encode()).hexdigest()[:20]
        task = "upstream-" + project[:24] + "-" + digest
        child = Path(binding["secondmate_home"]).resolve()
        if not child.is_dir() or read_json(safe_child(child, f"config/gitea-projects/{project}.json"), {}).get("url") != binding["url"]:
            raise ForgeError("Secondmate project binding is missing or inconsistent")
        env = native_env(child)
        body_path = safe_child(child, f"data/upstream-intents/{task}.md")
        body = (f"Reconcile upstream changes for {project}.\n\n"
                f"Upstream: {upstream}\nSource mirror: {mirror}\nTarget commit: {target}\n"
                f"Observed fork HEAD: {fork_head}\n\n"
                "Use a native ship crewmate in its own Treehouse worktree. Fetch this exact target, "
                "merge with the current fork base, and repair genuine conflicts without dropping local changes. "
                "Re-check the current base before delivery. Run the project's normal no-mistakes review, test, "
                "document and lint gate. Do not fabricate gate evidence or bypass checks. "
                "Use configured FirstMate merge authority. Escalate only a real unresolved decision or failed repair. "
                "Never reset or clean the user's existing working copies. Preserve ancestry and the upstream relationship.\n")
        try:
            run("tasks-axi", "show", task, cwd=child, env=env)
        except ForgeError as exc:
            if "NOT_FOUND" not in str(exc):
                raise
            atomic_text(body_path, body)
            run("tasks-axi", "add", task, f"Reconcile {project} upstream {target[:12]}",
                "--body-file", str(body_path), "--repo", project, "--kind", "ship", "--json", cwd=child, env=env)
        # A crash after publishing but before the receipt can repeat a wake; the
        # stable native task ID remains the idempotency key, not a second queue.
        announced = receipt.get("announced_task") == task
        if not announced:
            run("bash", "-c", '. "$1/fm-wake-lib.sh"; fm_wake_append check "$2" "$3"', "_", ROOT,
                task, f"Fresh upstream work is queued as {task}; target {target}", cwd=child, env=env)
        receipt.update(state="queued", task=task, announced_task=task, new_work=not announced)
        atomic_json(receipt_path, receipt)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("configure", "once", "arm"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--upstream")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--mirror")
    parser.add_argument("--period", type=int, default=900)
    try:
        args = parser.parse_args()
        args.project = identifier(args.project, "project")
        home = require_home()
        if args.command == "configure":
            if not args.upstream or not args.mirror:
                raise ForgeError("configuration requires --upstream and --mirror")
            result = configure(home, args)
        elif args.command == "once":
            result = once(home, args.project)
        else:
            configuration = read_json(safe_child(home, f"config/upstreams/{args.project}.json"))
            if not configuration:
                raise ForgeError("configure the upstream first")
            source = "upstream-" + hashlib.sha256((str(home) + "\0" + args.project).encode()).hexdigest()[:24]
            run(str(ROOT / "fm-procevent.sh"), "register", "upstream", source, "--", str(ROOT / "fm-procevent-upstream.sh"),
                "poll", args.project, str(configuration["period"]), env=native_env(home))
            result = {"state": "registered", "source": source, "owner": "native FirstMate process-event runner"}
        print(json.dumps(result))
        return 0
    except (ForgeError, OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"FirstMate upstream: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
