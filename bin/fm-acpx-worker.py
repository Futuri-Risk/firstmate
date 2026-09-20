#!/usr/bin/env python3
"""ACP harness console hosted by FirstMate's existing tmux backend.

Usage: FM_HOME=/home fm-acpx-worker.py --task ID --agent NAME --cwd WORKTREE
       --brief FILE --gen GENERATION [--model MODEL] [--effort EFFORT]
       fm-acpx-worker.py --task ID --gen GENERATION --control status|cancel|close
ACPx owns protocol and provider sessions; FirstMate owns tasks and its inbox.
An ACP turn ending never marks a FirstMate task complete. Configure custom
agents with ACPx's agents.NAME.argv setting. Optional permission rules belong
in the private home config/acpx-permission-policy.json; absent rules retain
ACPx's read-only approval default and fail unattended write requests closed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from fm_forge import (ForgeError, atomic_json, identifier, lock, read_json,
                      require_home, run, safe_child)

ROOT = Path(__file__).resolve().parent


class StopWorker(Exception):
    pass


def metadata(path):
    fields = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            if key in fields:
                raise ForgeError("duplicate task metadata field")
            fields[key] = value
    return fields


class Worker:
    def __init__(self, args):
        self.args = args
        self.home = require_home()
        self.task = identifier(args.task, "task ID")
        self.state = safe_child(self.home, "state")
        self.meta = metadata(self.state / (self.task + ".meta"))
        self.binding_file = safe_child(self.home, "state/" + self.task + ".acpx.json")
        self.binding = read_json(self.binding_file, {})
        self.agent = identifier(args.agent or self.binding.get("agent", ""), "ACP agent")
        self.cwd = Path(args.cwd or self.binding.get("cwd", "")).resolve()
        self.gen = args.gen or self.meta.get("busy_gen", "")
        self.name = "fm-" + self.task + "-" + hashlib.sha256((str(self.home) + "\0" + str(self.cwd)).encode()).hexdigest()[:16]
        self.active = None
        self.exiting = False
        self.last_progress = 0.0
        self.validate()

    def validate(self):
        current = metadata(self.state / (self.task + ".meta"))
        if current.get("harness") != "acp:" + self.agent or Path(current.get("worktree", "")).resolve() != self.cwd:
            raise ForgeError("ACP invocation does not match the recorded task/worktree")
        if not self.gen or current.get("busy_gen") != self.gen:
            raise ForgeError("stale ACP worker generation; refusing to touch its replacement")
        if self.binding and (self.binding.get("agent") != self.agent or self.binding.get("cwd") != str(self.cwd)):
            raise ForgeError("saved ACP session belongs to another agent or worktree")

    def command(self):
        command = ["acpx", "--cwd", str(self.cwd), "--format", "json", "--json-strict",
                   "--non-interactive-permissions", "fail", "--ttl", "300"]
        policy = safe_child(self.home, "config/acpx-permission-policy.json")
        if policy.exists():
            command += ["--permission-policy", str(policy)]
        if self.args.model and self.args.model != "default":
            command += ["--model", self.args.model]
        return command + [self.agent]

    def json_command(self, *args):
        self.validate()
        try:
            return json.loads(run(*self.command(), *args, timeout=30))
        except ValueError as exc:
            raise ForgeError("ACPx returned invalid control output") from exc

    def event(self, state, event):
        self.validate()
        run(str(ROOT / "fm-busy-event.sh"), "apply", str(self.state), self.task, state,
            "--gen", self.gen, "--source", "acpx-bridge", "--event", event)

    def save(self, **values):
        self.validate()
        self.binding.update(values)
        atomic_json(self.binding_file, self.binding)

    def connect(self):
        ensure = ["sessions", "ensure", "--name", self.name]
        if self.binding.get("closed") and self.binding.get("acp_session_id"):
            ensure += ["--resume-session", self.binding["acp_session_id"]]
        self.json_command(*ensure)
        session = self.json_command("sessions", "show", self.name)
        if Path(session.get("cwd", "")).resolve() != self.cwd:
            raise ForgeError("ACPx returned an ancestor or different worktree session")
        if self.binding.get("acp_session_id") and session.get("acpSessionId") != self.binding["acp_session_id"]:
            raise ForgeError("resume changed provider identity; preserved binding requires recovery")
        self.binding.update(schema="fm-acpx-binding.v1", agent=self.agent, cwd=str(self.cwd),
                            name=self.name, generation=self.gen, acpx_record_id=session["acpxRecordId"],
                            acp_session_id=session["acpSessionId"], closed=False)
        self.save()
        status = self.json_command("status", "--session", self.name)
        if status.get("status") == "running":
            self.cancel()
        if self.args.effort and self.args.effort != "default":
            options = session.get("acpx", {}).get("config_options", [])
            selected = next((option for option in options if option.get("id") in ("thought_level", "reasoning_effort", "effort")), None)
            allowed = {option.get("value") for option in (selected or {}).get("options", [])}
            if not selected or self.args.effort not in allowed:
                raise ForgeError("ACP server does not advertise the requested effort")
            self.json_command("set", "--session", self.name, selected["id"], self.args.effort)

    def cancel(self):
        return self.json_command("cancel", "--session", self.name)

    def interrupted(self, _number, _frame):
        try:
            self.cancel()
        except ForgeError as exc:
            print(f"ACP cancellation not confirmed: {exc}", file=sys.stderr, flush=True)

    def terminate(self, number, frame):
        self.exiting = True
        self.interrupted(number, frame)
        if self.active is None:
            raise StopWorker()

    def prompt(self, text):
        self.event("busy", "prompt-submit")
        self.save(last_prompt_state="submitted", last_prompt_digest=hashlib.sha256(text.encode()).hexdigest())
        stderr_file = safe_child(self.home, "state/" + self.task + ".acpx-stderr")
        flags = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        reason, code = None, 1
        fd = os.open(stderr_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w") as error_log:
            self.active = subprocess.Popen(self.command() + ["prompt", "--session", self.name, "--file", "-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error_log, text=True, **flags)
            process = self.active
            try:
                process.stdin.write(text)
                process.stdin.close()
                for line in process.stdout:
                    print(line, end="", flush=True)
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    result = event.get("result", {})
                    if isinstance(result, dict) and "stopReason" in result:
                        reason = result["stopReason"]
                    if time.monotonic() - self.last_progress > 1:
                        run(str(ROOT / "fm-busy-event.sh"), "progress", str(self.state), self.task, "--gen", self.gen)
                        self.last_progress = time.monotonic()
                code = process.wait(timeout=30)
            finally:
                if process.poll() is None:
                    try:
                        self.cancel()
                        process.wait(timeout=10)
                    except (ForgeError, subprocess.TimeoutExpired):
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                if process.stdout:
                    process.stdout.close()
                self.active = None
        if code != 0 or reason is None:
            self.event("unknown", "prompt-failed")
            self.save(last_prompt_state="failed", exit_code=code)
            with (self.state / (self.task + ".status")).open("a") as status:
                status.write("blocked: ACP prompt failed or requested unattended approval; inspect ACPx and the private task error log. Worktree preserved.\n")
        else:
            self.event("idle", "cancelled" if reason == "cancelled" else "prompt-returned")
            self.save(last_prompt_state=reason, exit_code=code)
        (self.state / (self.task + ".turn-ended")).touch()
        return code

    def close(self):
        result = self.json_command("sessions", "close", self.name)
        self.save(closed=True)
        return result

    def console(self):
        with lock(self.state / (self.task + ".acpx-owner.lock")):
            self.connect()
            signal.signal(signal.SIGINT, self.interrupted)
            signal.signal(signal.SIGTERM, self.terminate)
            try:
                self.prompt(Path(self.args.brief).read_text())
                while not self.exiting:
                    try:
                        text = input("❯ ")
                    except EOFError:
                        break
                    if text.strip() == "/exit":
                        break
                    if text.strip():
                        self.prompt(text)
            except StopWorker:
                pass
            finally:
                self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("agent", "cwd", "brief", "gen", "model", "effort"):
        parser.add_argument("--" + name)
    parser.add_argument("--task", required=True)
    parser.add_argument("--control", choices=("status", "cancel", "close"))
    args = parser.parse_args()
    try:
        worker = Worker(args)
        if args.control == "status":
            print(json.dumps(worker.json_command("status", "--session", worker.name)))
        elif args.control == "cancel":
            print(json.dumps(worker.cancel()))
        elif args.control == "close":
            print(json.dumps(worker.close()))
        elif not args.brief:
            raise ForgeError("a launch brief is required")
        else:
            worker.console()
        return 0
    except (ForgeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"FirstMate ACPx worker: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
