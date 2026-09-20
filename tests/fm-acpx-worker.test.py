"""Worker contract tests run a real ACPx process against an external peer."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkerJourney(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.state = self.home / "state"
        self.state.mkdir()
        (self.home / "config").mkdir()
        self.cwd = self.home / "work tree with spaces"
        self.cwd.mkdir()
        self.log = self.home / "protocol.jsonl"
        (self.home / ".acpx").mkdir()
        (self.home / ".acpx/config.json").write_text(json.dumps({"agents": {"zcode": {
            "argv": [sys.executable, str(ROOT / "tests/assets/fm-acp-peer.py"), str(self.log)]}}}))
        self.env = dict(os.environ, HOME=str(self.home), FM_HOME=str(self.home))
        self.gen = subprocess.check_output([str(ROOT / "bin/fm-busy-event.sh"), "arm", str(self.state), "test-task"], env=self.env, text=True).strip()
        (self.state / "test-task.meta").write_text(f"harness=acp:zcode\nworktree={self.cwd}\nbusy_gen={self.gen}\n")
        self.brief = self.home / "brief.txt"
        self.brief.write_text("FIRST REQUEST")

    def command(self):
        return [sys.executable, str(ROOT / "bin/fm-acpx-worker.py"), "--task", "test-task", "--agent", "zcode",
                "--cwd", str(self.cwd), "--gen", self.gen, "--brief", str(self.brief)]

    def invoke(self, text="SECOND REQUEST\n/exit\n"):
        return subprocess.run(self.command(), input=text, text=True, capture_output=True, env=self.env, timeout=40)

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_two_prompts_share_one_provider_session_and_do_not_complete_task(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RECEIVED:SECOND REQUEST", result.stdout)
        events = self.events()
        self.assertEqual(len([e for e in events if e["method"] == "session/new"]), 1)
        self.assertEqual([e["params"]["cwd"] for e in events if e["method"] == "session/new"], [str(self.cwd)])
        prompts = [e["params"] for e in events if e["method"] == "session/prompt"]
        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[0]["sessionId"], prompts[1]["sessionId"])
        self.assertTrue((self.state / "test-task.turn-ended").exists())
        status = self.state / "test-task.status"
        self.assertNotIn("done:", status.read_text() if status.exists() else "")

    def test_closed_session_resumes_exact_provider_conversation(self):
        first = self.invoke("/exit\n")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.invoke("/exit\n")
        self.assertEqual(second.returncode, 0, second.stderr)
        prompts = [e["params"] for e in self.events() if e["method"] == "session/prompt"]
        self.assertEqual(prompts[0]["sessionId"], prompts[1]["sessionId"])
        self.assertEqual(len([e for e in self.events() if e["method"] == "session/new"]), 1)

    def test_stale_generation_is_refused_before_provider_contact(self):
        (self.state / "test-task.meta").write_text(f"harness=acp:zcode\nworktree={self.cwd}\nbusy_gen=replacement\n")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stale", result.stderr)
        self.assertFalse(self.log.exists())

    def test_cancel_releases_waiting_turn_without_losing_workspace(self):
        self.brief.write_text("WAIT until cancelled")
        unique = self.cwd / "unfinished.txt"
        unique.write_text("UNCOMMITTED WORK")
        with tempfile.TemporaryFile(mode="w+") as output:
            process = subprocess.Popen(self.command(), stdin=subprocess.PIPE, stdout=output, stderr=output,
                                       env=self.env, text=True)
            try:
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if self.log.exists() and any(e["method"] == "session/prompt" for e in self.events()):
                        break
                    time.sleep(.1)
                else:
                    self.fail("ACP prompt never reached the peer")
                command = [sys.executable, str(ROOT / "bin/fm-acpx-worker.py"), "--task", "test-task", "--gen", self.gen, "--control", "cancel"]
                cancelled = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=35)
                self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
                process.communicate("/exit\n", timeout=30)
                self.assertEqual(process.returncode, 0)
                self.assertEqual(unique.read_text(), "UNCOMMITTED WORK")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    unittest.main(verbosity=2)
