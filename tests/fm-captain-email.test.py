"""Native captain holds and SMTP mail exercised through public commands."""
import json
import os
from pathlib import Path
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EmailJourney(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for name in ("state", "data", "config"):
            (self.home / name).mkdir()
        (self.home / ".tasks.toml").write_text((ROOT / ".tasks.toml").read_text())
        (self.home / "data/backlog.md").write_text("# Backlog\n\n## Queued\n\n## In flight\n\n## Done\n")
        certificate, key = self.home / "smtp.crt", self.home / "smtp.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                        "-out", str(certificate), "-days", "1", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        self.messages = []
        self.reject = False
        owner = self
        class SMTP(socketserver.StreamRequestHandler):
            def setup(self):
                self.request = context.wrap_socket(self.request, server_side=True)
                super().setup()
            def finish(self):
                try:
                    super().finish()
                finally:
                    self.request.close()
            def handle(self):
                self.wfile.write(b"220 localhost fixture SMTP\r\n")
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    command = line.decode().strip().upper()
                    if command.startswith("EHLO"):
                        self.wfile.write(b"250-localhost\r\n250 AUTH PLAIN LOGIN\r\n")
                    elif command.startswith("AUTH"):
                        self.wfile.write(b"235 authenticated\r\n")
                    elif command.startswith("RCPT") and owner.reject:
                        self.wfile.write(b"550 fixture rejection\r\n")
                    elif command.startswith("DATA"):
                        self.wfile.write(b"354 data\r\n")
                        payload = []
                        while True:
                            data = self.rfile.readline()
                            if data in (b".\r\n", b".\n", b""):
                                break
                            payload.append(data)
                        owner.messages.append(b"".join(payload))
                        self.wfile.write(b"250 queued\r\n")
                    elif command.startswith("QUIT"):
                        self.wfile.write(b"221 bye\r\n")
                        return
                    else:
                        self.wfile.write(b"250 ok\r\n")
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SMTP)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.env = dict(os.environ, FM_HOME=str(self.home), FM_MAIL_USER="fixture@example.invalid",
                        FM_MAIL_PASS="fixture-only", FM_IMAP_HOST="localhost", FM_SMTP_HOST="localhost",
                        FM_SMTP_PORT=str(self.server.server_address[1]), FM_MAIL_TIMEOUT="5",
                        SSL_CERT_FILE=str(certificate))

    def hold(self):
        result = subprocess.run([str(ROOT / "bin/fm-captain-hold.sh"), "hold", "decision-test", "--title",
                                 "Choose a direction", "--reason", "A real product decision is needed"],
                                cwd=self.home, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def send(self):
        return subprocess.run([sys.executable, str(ROOT / "bin/fm-captain-email.py"), "decision-test", "--to",
                               "captain@example.invalid"], cwd=self.home, env=self.env,
                              capture_output=True, text=True, timeout=30)

    def test_existing_hold_is_emailed_once_and_not_resolved(self):
        self.hold()
        first = self.send()
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.send()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["state"], "already-sent")
        self.assertEqual(len(self.messages), 1)
        active = subprocess.run([str(ROOT / "bin/fm-captain-hold.sh"), "open", "decision-test"], cwd=self.home, env=self.env)
        self.assertEqual(active.returncode, 0)

    def test_non_hold_never_sends_email(self):
        result = self.send()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.messages, [])

    def test_smtp_failure_keeps_hold_and_prevents_blind_duplicate_retry(self):
        self.hold()
        self.reject = True
        failed = self.send()
        self.assertNotEqual(failed.returncode, 0)
        again = self.send()
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("uncertain", again.stderr)
        self.assertEqual(self.messages, [])
        active = subprocess.run([str(ROOT / "bin/fm-captain-hold.sh"), "open", "decision-test"], cwd=self.home, env=self.env)
        self.assertEqual(active.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
