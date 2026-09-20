"""Exercise the fleet boundary with real subprocesses and a local HTTP peer."""
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from fm_forge import ForgeError, Gitea, run


class CommandBoundary(unittest.TestCase):
    def error(self, program, env=None, timeout=5):
        with self.assertRaises(ForgeError) as caught:
            run(sys.executable, "-c", program, env=env, timeout=timeout)
        return str(caught.exception)

    def test_json_error_on_stdout_is_reported(self):
        result = self.error('import sys; print(\'{"error":{"code":"NOT_FOUND"}}\'); sys.exit(1)')
        self.assertIn("NOT_FOUND", result)
        self.assertIn("exited 1", result)

    def test_stderr_warning_does_not_hide_structured_stdout_error(self):
        result = self.error('import sys; print("runtime warning", file=sys.stderr); print("NOT_FOUND"); sys.exit(1)')
        self.assertIn("runtime warning", result)
        self.assertIn("NOT_FOUND", result)

    def test_long_secret_is_redacted_before_error_is_truncated(self):
        env = dict(os.environ, FIXTURE_SECRET="BEGIN" + "x" * 2500 + "END")
        result = self.error('import os, sys; print(os.environ["FIXTURE_SECRET"]); sys.exit(1)', env=env)
        self.assertIn("[redacted]", result)
        self.assertNotIn("x" * 32, result)
        self.assertNotIn("BEGIN", result)
        self.assertNotIn("END", result)

    def test_url_credentials_are_not_reported(self):
        result = self.error('import sys; print("https://fixture-user:fixture-password@example.invalid/repo"); sys.exit(7)')
        self.assertIn("[redacted]@example.invalid/repo", result)
        self.assertNotIn("fixture-password", result)
        self.assertNotIn("fixture-user", result)

    def test_timeout_remains_a_failure(self):
        result = self.error('import time; time.sleep(5)', timeout=0.02)
        self.assertIn("could not complete", result)


class GiteaBoundary(unittest.TestCase):
    def setUp(self):
        self.paths = []
        self.redirect = False
        self.payload = None
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                owner.paths.append(self.path)
                canonical = "/api/v1/repos/team/widget"
                if owner.redirect or self.path != canonical:
                    self.send_response(302)
                    self.send_header("Location", "/must-not-receive-token")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(owner.payload).encode())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}/team/widget"
        self.payload = {"full_name": "team/widget", "clone_url": self.url + ".git"}

    def test_repository_uses_canonical_non_redirecting_endpoint(self):
        repository = Gitea(self.url).repository()
        self.assertEqual(repository["full_name"], "team/widget")
        self.assertEqual(self.paths, ["/api/v1/repos/team/widget"])

    def test_non_object_response_is_a_controlled_failure(self):
        self.payload = []
        with self.assertRaises(ForgeError):
            Gitea(self.url).repository()

    def test_redirect_does_not_contact_another_endpoint(self):
        self.redirect = True
        with self.assertRaises(ForgeError):
            Gitea(self.url).repository()
        self.assertEqual(len(self.paths), 1)
        self.assertNotIn("/must-not-receive-token", self.paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
