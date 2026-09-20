"""Project lifecycle tests: real Git, tasks-axi and native home provisioning."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def git(*args, cwd=None, env=None):
    return subprocess.check_output(["git", *map(str, args)], cwd=cwd, env=env, text=True, stderr=subprocess.DEVNULL).strip()


class ProjectJourney(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "captain"
        self.home.mkdir()
        self.user = self.base / "user"
        self.user.mkdir()
        self.tools = self.base / "tools"
        self.tools.mkdir()
        gate = self.tools / "no-mistakes"
        gate.write_text('#!/bin/sh\ncase "$1" in\ninit) git remote add no-mistakes . 2>/dev/null || true;;\n--version) echo "no-mistakes v1.46.0";;\nesac\n')
        gate.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.user), FM_HOME=str(self.home),
                        GIT_CONFIG_GLOBAL=str(self.user / "gitconfig"),
                        PATH=str(self.tools) + os.pathsep + os.environ["PATH"],
                        GIT_AUTHOR_NAME="Fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
                        GIT_COMMITTER_NAME="Fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid")
        self.remote = self.base / "upstream.git"
        source = self.base / "seed"
        source.mkdir()
        git("init", "-b", "main", cwd=source, env=self.env)
        (source / "README.md").write_text("Original project\n")
        (source / "AGENTS.md").write_text("Preserve existing project instructions.\n")
        git("add", ".", cwd=source, env=self.env)
        git("commit", "-m", "fixture baseline", cwd=source, env=self.env)
        git("clone", "--bare", source, self.remote, env=self.env)
        self.issues = [
            {"number": 7, "title": "Existing unfinished work", "body": "Keep its intent", "state": "open"},
            {"number": 8, "title": "Closed history", "state": "closed"},
            {"number": 9, "title": "Pull request", "state": "open", "pull_request": {"url": "ignored"}},
        ]
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                path = urlsplit(self.path).path.rstrip("/")
                if path == "/api/v1/repos/team/widget":
                    value = {"full_name": "team/widget", "clone_url": owner.url + ".git", "default_branch": "main"}
                elif path == "/api/v1/repos/team/widget/issues":
                    value = owner.issues
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}/team/widget"
        git("config", "--global", "url." + self.remote.as_uri() + ".insteadOf", self.url + ".git", env=self.env)

    def invoke(self):
        return subprocess.run([sys.executable, str(ROOT / "bin/fm-project-onboard.py"),
                               "--project", "widget", "--url", self.url], env=self.env,
                              capture_output=True, text=True, timeout=90)

    def test_onboard_and_repeat_preserve_one_secondmate_and_open_backlog(self):
        first = self.invoke()
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        child = Path(result["home"])
        second = self.invoke()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["home"], str(child))
        self.assertEqual(json.loads(second.stdout)["imported"], [])
        self.assertEqual((child / "config/secondmate-harness").read_text().strip(), "opencode")
        self.assertEqual((child / "config/backend").read_text().strip(), "tmux")
        backlog = (child / "data/backlog.md").read_text()
        self.assertIn("Existing unfinished work", backlog)
        self.assertNotIn("Closed history", backlog)
        self.assertNotIn("Pull request", backlog)
        registry = (self.home / "data/secondmates.md").read_text()
        self.assertEqual(sum(line.startswith("- project-widget ") for line in registry.splitlines()), 1)
        self.assertEqual(git("config", "--get", "remote.origin.url", cwd=self.home / "projects/widget"), self.url + ".git")

    def test_existing_dirty_and_untracked_work_is_preserved(self):
        clone = self.home / "projects/widget"
        clone.parent.mkdir()
        git("clone", self.url + ".git", clone, env=self.env)
        (clone / "README.md").write_text("UNCOMMITTED MODIFICATION")
        (clone / "new.bin").write_bytes(b"untracked\0bytes")
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((clone / "README.md").read_text(), "UNCOMMITTED MODIFICATION")
        self.assertEqual((clone / "new.bin").read_bytes(), b"untracked\0bytes")

    def test_wrong_origin_is_refused_without_touching_work(self):
        clone = self.home / "projects/widget"
        clone.parent.mkdir()
        git("clone", self.remote, clone, env=self.env)
        (clone / "unique.txt").write_text("KEEP")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((clone / "unique.txt").read_text(), "KEEP")
        self.assertFalse((self.home / "data/secondmates.md").exists())

    def test_projects_symlink_cannot_escape_home(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.home / "projects").symlink_to(outside, target_is_directory=True)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
