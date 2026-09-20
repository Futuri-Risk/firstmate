"""Public label CLI against an external Gitea-compatible HTTP fixture."""
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


class LabelJourney(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / "config/gitea-projects").mkdir(parents=True)
        self.labels = [{"id": 1, "name": "manual-important"}, {"id": 2, "name": "topic:z-code"}]
        self.issue_labels = {7: [1, 2], 8: [1]}
        self.writes = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def handle_request(self):
                path = urlsplit(self.path).path.removeprefix("/api/v1/repos/team/widget")
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"null")
                if self.command != "GET":
                    owner.writes.append((self.command, path, data))
                if path == "/labels" and self.command == "GET":
                    value = owner.labels
                elif path == "/labels" and self.command == "POST":
                    value = dict(data, id=max(row["id"] for row in owner.labels) + 1)
                    owner.labels.append(value)
                elif path == "/issues":
                    value = [{"number": 7, "state": "open"}, {"number": 8, "state": "closed"}]
                elif path.startswith("/issues/") and "/labels" in path:
                    parts = path.split("/")
                    number = int(parts[2])
                    if self.command == "POST":
                        owner.issue_labels[number] = list(set(owner.issue_labels[number] + data["labels"]))
                    elif self.command == "DELETE":
                        owner.issue_labels[number].remove(int(parts[-1]))
                    elif self.command != "GET":
                        self.send_error(405)
                        return
                    value = [row for row in owner.labels if row["id"] in owner.issue_labels[number]]
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())
            do_GET = do_POST = do_DELETE = do_PUT = handle_request
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        url = f"http://127.0.0.1:{self.server.server_port}/team/widget"
        (self.home / "config/gitea-projects/widget.json").write_text(json.dumps({"project": "widget", "url": url}))
        self.env = dict(os.environ, FM_HOME=str(self.home))

    def invoke(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "bin/fm-gitea-labels.py"), "--project", "widget", *args],
                              env=self.env, capture_output=True, text=True, timeout=15)

    def test_alias_normalization_is_additive_and_idempotent(self):
        result = self.invoke("--issue", "7", "--alias", "topic:z-code=topic:zcode", "--label", "skill:Memory")
        self.assertEqual(result.returncode, 0, result.stderr)
        names = {row["name"] for row in self.labels if row["id"] in self.issue_labels[7]}
        self.assertEqual(names, {"manual-important", "topic:zcode", "skill:memory"})
        self.assertFalse(any(method == "PUT" for method, _, _ in self.writes))
        count = len(self.writes)
        repeated = self.invoke("--issue", "7", "--label", "skill:memory")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(len(self.writes), count)

    def test_backfill_does_not_activate_or_change_closed_history(self):
        result = self.invoke("--backfill", "--alias", "topic:z-code=topic:zcode")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.issue_labels[8], [1])
        self.assertFalse(any("/issues/8" in path for _, path, _ in self.writes))

    def test_alias_cycles_fail_before_remote_mutation(self):
        result = self.invoke("--issue", "7", "--alias", "topic:a=topic:b", "--alias", "topic:b=topic:a")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.writes, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
