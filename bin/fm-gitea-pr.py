#!/usr/bin/env python3
"""Internal Gitea provider for native FirstMate PR lifecycle commands.

Usage: FM_HOME=/home fm-gitea-pr.py identity|snapshot|verify --url URL
       [--expected-head SHA]
The merge verb is a provider primitive called ONLY by fm-pr-merge after its
existing captain/hold/away/role/incarnation guards. It is not a new approval
path. PR creation and its review/test/document attestation remain no-mistakes'
responsibility. Only explicitly onboarded repositories can receive a token.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from urllib.parse import urlsplit
from fm_forge import ForgeError, Gitea, read_json, require_home, safe_child


def head(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        raise ForgeError("Gitea returned an invalid commit identity")
    return value


def identify(url):
    home = require_home()
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ForgeError("PR URL must be canonical and credential-free")
    match = re.fullmatch(r"(.+)/pulls/([1-9][0-9]*)", parsed.path)
    if not match:
        raise ForgeError("invalid Gitea pull request URL")
    repo_url = f"{parsed.scheme}://{parsed.netloc}{match[1]}"
    api = Gitea(repo_url)
    if api.url + "/pulls/" + match[2] != url:
        raise ForgeError("noncanonical Gitea pull request URL")
    directory = safe_child(home, "config/gitea-projects")
    bindings = []
    if directory.is_dir():
        for path in directory.glob("*.json"):
            path = safe_child(home, str(path.relative_to(home)))
            binding = read_json(path, {})
            if binding.get("url") == repo_url:
                bindings.append(binding)
    if len(bindings) != 1:
        raise ForgeError("PR must belong to exactly one configured Gitea project")
    return api, {"provider": "gitea", "url": url, "host": parsed.netloc,
                 "path": parsed.path.rsplit("/pulls/", 1)[0].strip("/"),
                 "number": int(match[2]), "owner": api.owner, "repo": api.repo,
                 "project": bindings[0]["project"]}


def snapshot(api, identity, checks=True):
    number = identity["number"]
    pr = api.request("GET", f"/pulls/{number}")
    if not isinstance(pr, dict) or pr.get("number") != number or pr.get("html_url") != identity["url"]:
        raise ForgeError("Gitea returned a different pull request")
    if pr.get("state") not in ("open", "closed") or type(pr.get("merged")) is not bool:
        raise ForgeError("Gitea returned an incomplete PR state")
    current = head(pr.get("head", {}).get("sha"))
    base = head(pr.get("base", {}).get("sha"))
    merged = pr["merged"]
    merge_sha = head(pr.get("merge_commit_sha")) if merged else None
    if merged and pr["state"] != "closed":
        raise ForgeError("Gitea merged/state fields disagree")
    result = dict(identity, state=pr["state"], merged=merged, head=current, base=base,
                  merge_commit_sha=merge_sha, draft=pr.get("draft", False),
                  mergeable=pr.get("mergeable"), checks_state="unobserved", checks_count=0)
    if checks and not merged:
        status = api.request("GET", f"/commits/{current}/status")
        if not isinstance(status, dict) or status.get("sha") != current:
            raise ForgeError("Gitea check status belongs to a different commit")
        count = status.get("total_count")
        if type(count) is not int or count < 0 or not isinstance(status.get("statuses"), list):
            raise ForgeError("Gitea returned incomplete commit checks")
        result.update(checks_state=status.get("state", "unknown"), checks_count=count,
                      checks=status["statuses"])
    return result


def verify(api, identity, expected):
    expected = head(expected)
    value = snapshot(api, identity)
    reasons = []
    if value["head"] != expected:
        reasons.append("head changed since validation")
    if value["state"] != "open" or value["merged"]:
        reasons.append("PR is not open and unmerged")
    if value["draft"]:
        reasons.append("PR is a draft")
    if value["mergeable"] is not True:
        reasons.append("mergeability is not yet confirmed")
    if value["checks_state"] != "success" or value["checks_count"] == 0:
        reasons.append("no successful check evidence for this head")
    if reasons:
        raise ForgeError("; ".join(reasons))
    return value


def merge(api, identity, expected, method):
    verify(api, identity, expected)
    api.request("POST", f"/pulls/{identity['number']}/merge", {
        "Do": method, "head_commit_id": expected, "force_merge": False,
        "delete_branch_after_merge": False, "merge_when_checks_succeed": False})
    result = snapshot(api, identity, checks=False)
    if not result["merged"] or result["head"] != expected:
        raise ForgeError("merge request was sent, but exact-head landing is not confirmed; retain the poll")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("identity", "record", "snapshot", "verify", "merge"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-head")
    parser.add_argument("--method", choices=("merge", "squash", "rebase"), default="squash")
    try:
        args = parser.parse_args()
        api, identity = identify(args.url)
        if args.command == "identity":
            value = identity
        elif args.command == "record":
            value = snapshot(api, identity, checks=False)
        elif args.command == "snapshot":
            value = snapshot(api, identity)
        elif args.command == "verify":
            value = verify(api, identity, args.expected_head)
        else:
            value = merge(api, identity, head(args.expected_head), args.method)
        print(json.dumps(value))
        return 0
    except (ForgeError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FirstMate Gitea PR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
