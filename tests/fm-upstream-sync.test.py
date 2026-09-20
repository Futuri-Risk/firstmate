"""Real Git mirrors and native Secondmate backlog/wake handoff."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
prior = runpy.run_path(str(ROOT / "tests/fm-gitea-onboarding.test.py"))
Base = prior["ProjectJourney"]
git = prior["git"]


class UpstreamJourney(unittest.TestCase):
    def setUp(self):
        Base.setUp(self)
        setup = Base.invoke(self)
        self.assertEqual(setup.returncode, 0, setup.stderr)
        self.child = Path(json.loads(setup.stdout)["home"])
        self.mirror = self.base / "source-cache.git"
        result = self.sync("configure", "--upstream", self.remote.as_uri(), "--branch", "main", "--mirror", str(self.mirror))
        self.assertEqual(result.returncode, 0, result.stderr)

    def sync(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "bin/fm-upstream-sync.py"), *args,
                               "--project", "widget"], env=self.env, text=True,
                              capture_output=True, timeout=50)

    def advance_upstream(self):
        seed = self.base / "seed"
        (seed / "new-upstream.txt").write_text("new upstream capability")
        git("add", ".", cwd=seed, env=self.env)
        git("commit", "-m", "upstream feature", cwd=seed, env=self.env)
        git("push", self.remote, "main", cwd=seed, env=self.env)
        return git("rev-parse", "HEAD", cwd=seed, env=self.env)

    def test_new_commit_becomes_one_native_task_and_wake_without_touching_fork(self):
        clone = self.home / "projects/widget"
        before = git("rev-parse", "HEAD", cwd=clone)
        (clone / "unfinished.txt").write_text("KEEP MY UNTRACKED WORK")
        upstream = self.advance_upstream()
        first = self.sync("once")
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        self.assertEqual(result["state"], "queued")
        self.assertEqual(result["upstream_head"], upstream)
        again = self.sync("once")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)["task"], result["task"])
        backlog = (self.child / "data/backlog.md").read_text()
        self.assertIn(result["task"], backlog)
        self.assertIn(upstream, subprocess.check_output(["tasks-axi", "show", result["task"], "--full"],
                      cwd=self.child, env=dict(self.env, FM_HOME=str(self.child)), text=True))
        self.assertEqual(git("rev-parse", "HEAD", cwd=clone), before)
        self.assertEqual((clone / "unfinished.txt").read_text(), "KEEP MY UNTRACKED WORK")
        wakes = (self.child / "state/.wake-queue").read_text()
        self.assertEqual(sum(result["task"] in line for line in wakes.splitlines()), 1)
        self.assertEqual(git("rev-parse", "--is-bare-repository", cwd=self.mirror), "true")

    def test_equal_upstream_is_quiet(self):
        result = self.sync("once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["state"], "current")
        self.assertNotIn("upstream-widget", (self.child / "data/backlog.md").read_text())

    def test_failed_fetch_retains_mirror_but_marks_evidence_stale(self):
        first = self.sync("once")
        self.assertEqual(first.returncode, 0, first.stderr)
        before = git("rev-parse", "refs/heads/main", cwd=self.mirror)
        self.remote.rename(self.base / "unavailable.git")
        result = self.sync("once")
        self.assertNotEqual(result.returncode, 0)
        receipt = json.loads((self.home / "state/upstream/widget.json").read_text())
        self.assertEqual(receipt["freshness"], "stale")
        self.assertEqual(receipt["upstream_head"], before)
        self.assertEqual(git("rev-parse", "refs/heads/main", cwd=self.mirror), before)

    def test_existing_nonmirror_directory_is_not_overwritten(self):
        self.mirror.mkdir()
        protected = self.mirror / "precious.txt"
        protected.write_text("KEEP")
        result = self.sync("once")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(protected.read_text(), "KEEP")


if __name__ == "__main__":
    unittest.main(verbosity=2)
