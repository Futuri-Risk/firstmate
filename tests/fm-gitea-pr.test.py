"""Gitea PR contract: public commands against an external HTTP fixture."""
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
HEAD, BASE, MERGE = "a" * 40, "b" * 40, "c" * 40


class PullRequestJourney(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / "config/gitea-projects").mkdir(parents=True)
        (self.home / "state").mkdir()
        self.requests = []
        self.merged = False
        self.draft = False
        self.state = "success"
        self.total = 1
        self.response_head = HEAD
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def handle_request(self):
                path = urlsplit(self.path).path
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"null")
                owner.requests.append((self.command, path, data))
                if path.endswith("/pulls/12/merge") and self.command == "POST":
                    if data.get("head_commit_id") != owner.response_head:
                        self.send_error(409)
                        return
                    owner.merged = True
                    self.send_response(200)
                    self.end_headers()
                    return
                if path.endswith("/pulls/12"):
                    value = {"number": 12, "html_url": owner.url, "state": "closed" if owner.merged else "open",
                             "merged": owner.merged, "draft": owner.draft, "mergeable": True,
                             "head": {"sha": owner.response_head}, "base": {"sha": BASE},
                             "merge_commit_sha": MERGE if owner.merged else None}
                elif path.endswith("/status"):
                    value = {"sha": owner.response_head, "state": owner.state, "total_count": owner.total,
                             "statuses": [{"id": 1, "context": "test", "status": owner.state}] if owner.total else []}
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())
            do_GET = do_POST = handle_request
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.repo = f"http://127.0.0.1:{self.server.server_port}/team/widget"
        self.url = self.repo + "/pulls/12"
        (self.home / "config/gitea-projects/widget.json").write_text(json.dumps({"project": "widget", "url": self.repo}))
        self.env = dict(os.environ, FM_HOME=str(self.home))

    def invoke(self, command, *args):
        return subprocess.run([sys.executable, str(ROOT / "bin/fm-gitea-pr.py"), command,
                               "--url", self.url, *args], env=self.env, capture_output=True, text=True, timeout=15)

    def test_identity_requires_a_configured_repository_without_network(self):
        identity = self.invoke("identity")
        self.assertEqual(identity.returncode, 0, identity.stderr)
        self.assertEqual(json.loads(identity.stdout)["provider"], "gitea")
        self.assertEqual(self.requests, [])
        (self.home / "config/gitea-projects/widget.json").unlink()
        unknown = self.invoke("identity")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertEqual(self.requests, [])

    def test_snapshot_and_verify_bind_exact_head(self):
        snapshot = self.invoke("snapshot")
        self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
        self.assertEqual(json.loads(snapshot.stdout)["head"], HEAD)
        good = self.invoke("verify", "--expected-head", HEAD)
        self.assertEqual(good.returncode, 0, good.stderr)
        stale = self.invoke("verify", "--expected-head", "d" * 40)
        self.assertNotEqual(stale.returncode, 0)
        self.assertFalse(any(method == "POST" for method, _, _ in self.requests))

    def test_pending_empty_and_draft_are_not_green(self):
        for state, count, draft in (("pending", 1, False), ("success", 0, False), ("success", 1, True)):
            with self.subTest(state=state, count=count, draft=draft):
                self.state, self.total, self.draft = state, count, draft
                result = self.invoke("verify", "--expected-head", HEAD)
                self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(method == "POST" for method, _, _ in self.requests))

    def test_merge_is_head_fenced_synchronous_and_has_no_protection_bypass(self):
        result = self.invoke("merge", "--expected-head", HEAD, "--method", "squash")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [data for method, _, data in self.requests if method == "POST"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["head_commit_id"], HEAD)
        self.assertFalse(calls[0]["force_merge"])
        self.assertFalse(calls[0]["delete_branch_after_merge"])
        self.assertFalse(calls[0]["merge_when_checks_succeed"])
        value = json.loads(result.stdout)
        self.assertTrue(value["merged"])
        self.assertEqual(value["merge_commit_sha"], MERGE)

    def test_native_pr_identity_accepts_only_configured_gitea(self):
        result = subprocess.run(["bash", "-c", '. "$1/bin/fm-pr-lib.sh"; fm_pr_url_parse "$2"; printf "%s\\n" "$FM_PR_PROVIDER"',
                                 "_", str(ROOT), self.url], env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "gitea")


if __name__ == "__main__":
    unittest.main(verbosity=2)
