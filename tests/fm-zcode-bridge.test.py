"""Real FirstMate wrapper -> real ACPx -> real zcode-acp -> external peer.

Only the paid vendor app-server is substituted. The bridge and ACPx are the
pinned executable builds, including their session and translation machinery.
"""
import json
import os
from pathlib import Path
import runpy
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
Base = runpy.run_path(str(ROOT / "tests/fm-acpx-worker.test.py"))["WorkerJourney"]


class ZCodeBridgeJourney(unittest.TestCase):
    command = Base.command
    invoke = Base.invoke

    def setUp(self):
        Base.setUp(self)
        entry = os.environ.get("FM_TEST_ZCODE_ENTRY", "")
        if not entry or not Path(entry).is_file():
            self.fail("FM_TEST_ZCODE_ENTRY must name the real built ZCode ACP bridge")
        self.vendor_log = self.home / "vendor.jsonl"
        self.env.update(ZCODE_BIN=str(ROOT / "tests/assets/fm-zcode-app-server.cjs"),
                        ZCODE_ACP_RUNTIME="node", ZCODE_HOME=str(self.home / "isolated-zcode"),
                        FLEET_ZCODE_FIXTURE_LOG=str(self.vendor_log))
        (self.home / ".acpx/config.json").write_text(json.dumps({"agents": {"zcode": {"argv": ["node", entry]}}}))

    def requests(self):
        return [json.loads(line) for line in self.vendor_log.read_text().splitlines()]

    def test_real_bridge_preserves_worktree_and_native_session_for_follow_up(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RECEIVED:SECOND REQUEST", result.stdout)
        requests = self.requests()
        created = [row for row in requests if row.get("method") == "session/create"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["params"]["workspace"]["workspacePath"], str(self.cwd))
        sent = [row["params"] for row in requests if row.get("method") == "session/send"]
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0]["sessionId"], sent[1]["sessionId"])
        self.assertTrue((self.state / "test-task.turn-ended").exists())

    def test_real_bridge_reopens_the_same_materialized_vendor_session(self):
        first = self.invoke("/exit\n")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.invoke("/exit\n")
        self.assertEqual(second.returncode, 0, second.stderr)
        requests = self.requests()
        self.assertEqual(len([row for row in requests if row.get("method") == "session/create"]), 1)
        sent = [row["params"]["sessionId"] for row in requests if row.get("method") == "session/send"]
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0], sent[1])
        self.assertTrue(any(row.get("method") == "session/resume" for row in requests))


if __name__ == "__main__":
    unittest.main(verbosity=2)
