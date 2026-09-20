"""One-time cutover preserves Git and dirty bytes; no old runtime adoption."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
prior = runpy.run_path(str(ROOT / "tests/fm-gitea-onboarding.test.py"))
Base, git = prior["ProjectJourney"], prior["git"]


class CutoverJourney(unittest.TestCase):
    def setUp(self):
        Base.setUp(self)
        self.old = self.base / "legacy-forge"
        self.old.mkdir()
        (self.old / "runtime.json").write_text('{"old_session_id":"must-not-be-imported"}')
        (self.old / ".env").write_text("PRIVATE_FIXTURE_SECRET=never-publish\n")
        self.source = self.base / "seed"
        git("remote", "add", "origin", self.url + ".git", cwd=self.source, env=self.env)
        git("branch", "unfinished-feature", cwd=self.source)
        (self.source / "README.md").write_text("UNCOMMITTED PROJECT CONTENT")
        (self.source / "draft.bin").write_bytes(b"untracked\0binary")
        self.backup = self.base / "rollback"
        self.manifest = self.base / "cutover.json"
        self.manifest.write_text(json.dumps({"schema": "fm-forge-cutover.v1", "id": "fixture-cutover",
            "backup_root": str(self.backup), "legacy_roots": [str(self.old)],
            "projects": [{"project": "widget", "url": self.url, "source": str(self.source)}]}))

    def invoke(self, command, *args):
        return subprocess.run([sys.executable, str(ROOT / "bin/fm-forge-cutover.py"), command,
                               "--manifest", str(self.manifest), *args], env=self.env, text=True,
                              capture_output=True, timeout=100)

    def test_plan_does_not_mutate_either_system(self):
        result = self.invoke("plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.backup.exists())
        self.assertFalse((self.home / "projects").exists())
        self.assertEqual((self.source / "draft.bin").read_bytes(), b"untracked\0binary")

    def test_cutover_preserves_dirty_work_branches_and_private_rollback(self):
        result = self.invoke("apply", "--quiesced")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["state"], "source-prepared")
        clone = self.home / "projects/widget"
        self.assertEqual((clone / "README.md").read_text(), "UNCOMMITTED PROJECT CONTENT")
        self.assertEqual((clone / "draft.bin").read_bytes(), b"untracked\0binary")
        self.assertEqual(git("rev-parse", "unfinished-feature", cwd=clone), git("rev-parse", "unfinished-feature", cwd=self.source))
        child = Path(receipt["projects"][0]["home"])
        self.assertIn("Existing unfinished work", (child / "data/backlog.md").read_text())
        self.assertFalse((child / "runtime.json").exists())
        self.assertEqual((self.old / "runtime.json").read_text(), '{"old_session_id":"must-not-be-imported"}')
        self.assertTrue(Path(receipt["rollback_manifest"]).is_file())
        if os.name != "nt":
            self.assertEqual(self.backup.stat().st_mode & 0o077, 0)
        again = self.invoke("apply", "--quiesced")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)["rollback_manifest"], receipt["rollback_manifest"])

    def test_apply_requires_quiescence_and_never_overwrites_existing_destination(self):
        result = self.invoke("apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.backup.exists())
        clone = self.home / "projects/widget"
        clone.mkdir(parents=True)
        (clone / "precious.txt").write_text("KEEP")
        result = self.invoke("apply", "--quiesced")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((clone / "precious.txt").read_text(), "KEEP")


if __name__ == "__main__":
    unittest.main(verbosity=2)
