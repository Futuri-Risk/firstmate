"""Temporary assertion-guarded cloud edit helper; removed before merge."""
from pathlib import Path

changed = []
def patch(name, old, new):
    path = Path(name)
    text = path.read_text()
    if new in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f"{name}: expected exactly one anchor: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1))
    changed.append(name)

patch("bin/fm_forge.py", "error = result.stderr[-2000:]", "error = (result.stderr or result.stdout)[-2000:]")
patch("bin/fm_forge.py", "if not suffix.startswith(\"/\") or \"..\" in suffix.split(\"/\"):", "if (suffix and not suffix.startswith(\"/\")) or \"..\" in suffix.split(\"/\"):")
patch("bin/fm_forge.py", "result = self.request(\"GET\", \"/\")", "result = self.request(\"GET\", \"\")")
patch("bin/fm-project-onboard.py", 'run("tasks-axi", "add", "--id", task, "--title", title, "--body", body,', 'run("tasks-axi", "add", task, title, "--body-file", str(body_path),')
patch("bin/fm-project-onboard.py", '                run("tasks-axi", "add", task, title, "--body-file", str(body_path),', '                body_path = safe_child(child, f"data/gitea-imports/{task}.md")\n                atomic_text(body_path, body)\n                run("tasks-axi", "add", task, title, "--body-file", str(body_path),')
patch("bin/fm-captain-email.py", "        task = identifier(args.task, \"task ID\")", "        if (home / \".fm-secondmate-parent\").exists():\n            raise ForgeError(\"Secondmate outcomes must use the native parent channel; send captain mail from the parent home\")\n        task = identifier(args.task, \"task ID\")")
patch("tests/fm-captain-email.test.py", "            def handle(self):\n                self.wfile.write", "            def finish(self):\n                try:\n                    super().finish()\n                finally:\n                    self.request.close()\n            def handle(self):\n                self.wfile.write")
patch(".github/workflows/fleet-cloud-evidence.yml", "    branches: [feat/gitea-acpx-fleet]\n  workflow_dispatch:", "    branches: [feat/gitea-acpx-fleet]\n    paths: [.github/workflows/fleet-cloud-evidence.yml]\n  workflow_dispatch:")
print("Changed:", ", ".join(changed))
