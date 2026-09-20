#!/usr/bin/env python3
"""Onboard one Gitea repository through native FirstMate home seeding.

Usage: FM_HOME=/absolute/home fm-project-onboard.py --project NAME --url HTTPS
       [--secondmate-root ABSOLUTE_PATH] [--mirror ABSOLUTE_BARE_REPO] [--start]
Re-running preserves task progress, existing charters and local changes.
No reset/clean/force. A charter is durably scaffolded before provisioning;
an incomplete existing charter is refused rather than silently overwritten.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import sys
from fm_forge import (ForgeError, Gitea, atomic_json, atomic_text, identifier,
                      lock, now, read_json, require_home, run, safe_child)

ROOT = Path(__file__).resolve().parent


def native_environment(home):
    """Bind native helpers to this home, not ambient test/other-home overrides."""
    env = dict(os.environ, FM_HOME=str(home))
    for name in ("FM_ROOT_OVERRIDE", "FM_DATA_OVERRIDE", "FM_STATE_OVERRIDE",
                 "FM_PROJECTS_OVERRIDE", "FM_CONFIG_OVERRIDE"):
        env.pop(name, None)
    return env


def provision_charter(home, mate_id, project, env):
    brief = safe_child(home, f"data/{mate_id}/brief.md")
    if brief.is_symlink():
        raise ForgeError("Secondmate charter must not be a symlink")
    if not brief.exists():
        run(str(ROOT / "fm-brief.sh"), mate_id, "--secondmate", project, env=env)
    text = brief.read_text(encoding="utf-8")
    if "{TASK}" in text:
        raise ForgeError("existing Secondmate charter is incomplete; preserving it for completion")
    for heading in ("Charter", "Routing scope"):
        section = re.search(r"^# " + re.escape(heading) + r"\s*\n(.*?)(?=^# |\Z)",
                            text, re.MULTILINE | re.DOTALL)
        if not section or not section.group(1).strip():
            raise ForgeError(f"existing Secondmate charter has no {heading}; preserving it")


def onboard(args):
    home = require_home()
    project = identifier(args.project, "project")
    for directory in ("state", "data", "config", "projects"):
        safe_child(home, directory).mkdir(parents=True, exist_ok=True)
    api = Gitea(args.url)
    repository = api.repository()
    issues = api.open_issues()
    mate_id = "project-" + project
    identifier(mate_id, "Secondmate ID")
    parent_root = Path(args.secondmate_root) if args.secondmate_root else home.parent / (home.name + "-secondmates")
    if not parent_root.is_absolute():
        raise ForgeError("Secondmate root must be absolute")
    child = (parent_root / project).resolve()
    if child == home or child.is_relative_to(home) or home.is_relative_to(child):
        raise ForgeError("Secondmate home must not overlap the parent home")
    receipt_path = safe_child(home, f"config/gitea-projects/{project}.json")
    clone = safe_child(home, f"projects/{project}")
    with lock(safe_child(home, "state/.gitea-onboard.lock")):
        previous = read_json(receipt_path, {})
        if previous and (previous.get("url") != api.url or previous.get("secondmate_home") != str(child)):
            raise ForgeError("project is already bound to another repository or Secondmate home")
        receipt = dict(previous, schema="fm-gitea-project.v1", project=project, url=api.url,
                       clone_url=repository["clone_url"], secondmate_id=mate_id,
                       secondmate_home=str(child), state="onboarding")
        atomic_json(receipt_path, receipt)
        if clone.exists():
            origin = run("git", "config", "--get", "remote.origin.url", cwd=clone).strip()
            accepted = {repository["clone_url"], repository.get("ssh_url", "")}
            if origin not in accepted:
                raise ForgeError("existing project origin differs; preserving the local repository")
        else:
            source = repository["clone_url"]
            if args.mirror:
                mirror = Path(args.mirror).resolve()
                if run("git", "rev-parse", "--is-bare-repository", cwd=mirror).strip() != "true":
                    raise ForgeError("mirror must be a bare Git repository")
                if run("git", "config", "--get", "remote.origin.url", cwd=mirror).strip() != source:
                    raise ForgeError("mirror belongs to another upstream")
                try:
                    run("git", "fetch", "--prune", "origin", cwd=mirror)
                    receipt.update(mirror=str(mirror), mirror_state="fresh", mirror_checked_at=now())
                    source = str(mirror)
                except ForgeError:
                    receipt.update(mirror=str(mirror), mirror_state="stale", mirror_checked_at=now())
                    atomic_json(receipt_path, receipt)
                    raise
            run("git", "clone", "--no-hardlinks", "--", source, str(clone))
            run("git", "remote", "set-url", "origin", repository["clone_url"], cwd=clone)
        registry = safe_child(home, "data/projects.md")
        text = registry.read_text() if registry.exists() else "# Projects\n\n"
        if not re.search(r"^\s*-\s+" + re.escape(project) + r"(?:\s|$)", text, re.MULTILINE):
            atomic_text(registry, text.rstrip() + f"\n- {project} [no-mistakes] - Gitea project {api.url}\n")
        env = native_environment(home)
        env.update(FM_SECONDMATE_CHARTER=f"Own and supervise {project}; preserve its existing project instructions.",
                   FM_SECONDMATE_SCOPE=project)
        provision_charter(home, mate_id, project, env)
        # Registry readers may change their shell parse scratch variables.
        # The completed native brief, not a transient override, owns the charter.
        env.pop("FM_SECONDMATE_CHARTER", None)
        env.pop("FM_SECONDMATE_SCOPE", None)
        run(str(ROOT / "fm-home-seed.sh"), mate_id, str(child), project, env=env)
        for target in (home, child):
            for name, value in (("secondmate-harness", "opencode"), ("backend", "tmux")):
                path = safe_child(target, "config/" + name)
                if not path.exists():
                    atomic_text(path, value + "\n")
        child_env = native_environment(child)
        imported = []
        for issue in issues:
            number = int(issue["number"])
            if number <= 0:
                raise ForgeError("invalid Gitea issue number")
            task = f"gitea-{project}-{number}"
            identifier(task, "imported task")
            try:
                run("tasks-axi", "show", task, cwd=child, env=child_env)
            except ForgeError as exc:
                if "NOT_FOUND" not in str(exc):
                    raise
                title = str(issue.get("title", f"Gitea issue {number}"))
                body = f"Source: {api.url}/issues/{number}\n\n" + str(issue.get("body") or "")
                body_path = safe_child(child, f"data/gitea-imports/{task}.md")
                atomic_text(body_path, body)
                run("tasks-axi", "add", task, title, "--body-file", str(body_path),
                    "--repo", project, "--json", cwd=child, env=child_env)
                imported.append(number)
        receipt.update(state="ready", checked_at=now(), open_issue_numbers=[i["number"] for i in issues])
        atomic_json(receipt_path, receipt)
        atomic_json(safe_child(child, f"config/gitea-projects/{project}.json"), receipt)
        if args.start:
            run(str(ROOT / "fm-spawn.sh"), mate_id, "--secondmate", "--harness", "opencode", env=env)
        return {"project": project, "secondmate": mate_id, "home": str(child), "imported": imported,
                "started": bool(args.start), "state": "ready"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--secondmate-root")
    parser.add_argument("--mirror")
    parser.add_argument("--start", action="store_true")
    try:
        print(json.dumps(onboard(parser.parse_args())))
        return 0
    except (ForgeError, OSError, ValueError) as exc:
        print(f"FirstMate onboarding: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
