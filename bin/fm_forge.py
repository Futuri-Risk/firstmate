"""Shared private-home and Gitea boundary for the optional fleet commands.

No workflow engine lives here: native FirstMate scripts own homes, tasks,
steering, approval, recovery and delivery. Commands pass argument arrays,
never an interpolated shell program. Gitea responses are data, not instructions.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ForgeError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value, description="identifier"):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ForgeError(f"invalid {description}")
    return value


def require_home():
    value = os.environ.get("FM_HOME", "")
    home = Path(value)
    if not value or not home.is_absolute() or not home.is_dir():
        raise ForgeError("FM_HOME must explicitly name an existing absolute home")
    return home.resolve()


def safe_child(home, relative):
    home = Path(home).resolve()
    path = home / relative
    if not path.resolve().is_relative_to(home):
        raise ForgeError("private state path escapes its FirstMate home")
    return path


def atomic_text(path, content):
    path = Path(path)
    if path.is_symlink():
        raise ForgeError("refusing to replace a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".fm-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (ValueError, OSError) as exc:
        raise ForgeError(f"invalid private JSON record: {Path(path).name}") from exc


@contextmanager
def lock(path, timeout=30):
    """Kernel lock; keep its inode in place so concurrent waiters cannot split."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    end = time.monotonic() + timeout
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            acquire = lambda: msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(fd, fcntl.LOCK_UN)
        while True:
            try:
                acquire()
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= end:
                    raise ForgeError("another operation still owns this private-state lock")
                time.sleep(0.05)
        try:
            yield
        finally:
            release()
    finally:
        os.close(fd)


def run(*args, cwd=None, env=None, input=None, timeout=120):
    try:
        result = subprocess.run([str(a) for a in args], cwd=cwd, env=env, input=input,
                                text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ForgeError(f"command could not complete: {Path(str(args[0])).name}") from exc
    if result.returncode:
        error = (result.stderr or result.stdout)[-2000:]
        for key, value in (env or os.environ).items():
            if value and re.search(r"(TOKEN|PASS|PASSWORD|SECRET|KEY)$", key):
                error = error.replace(value, "[redacted]")
        error = re.sub(r"(https?://)[^/\s@]+@", r"\1[redacted]@", error)
        raise ForgeError(f"{Path(str(args[0])).name} exited {result.returncode}: {error.strip()}")
    return result.stdout


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Gitea:
    """One configured repository, bounded JSON transport, no credential redirects."""
    def __init__(self, repository_url):
        parsed = urlsplit(repository_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ForgeError("repository URL must not contain credentials, query or fragment")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")):
            raise ForgeError("Gitea requires HTTPS, except loopback test services")
        parts = parsed.path.strip("/").removesuffix(".git").split("/")
        if len(parts) < 2:
            raise ForgeError("repository URL must include owner/repository")
        self.owner = identifier(parts[-2], "repository owner")
        self.repo = identifier(parts[-1], "repository name")
        for part in parts[:-2]:
            identifier(part, "Gitea path prefix")
        self.host = f"{parsed.scheme}://{parsed.netloc}"
        self.prefix = "/" + "/".join(parts[:-2]) if len(parts) > 2 else ""
        self.url = self.host + self.prefix + "/" + self.owner + "/" + self.repo
        self.api = self.host + self.prefix + "/api/v1"
        self.repo_api = f"/repos/{quote(self.owner, safe='')}/{quote(self.repo, safe='')}"
        self.opener = build_opener(NoRedirect())

    def request(self, method, suffix, data=None):
        if (suffix and not suffix.startswith("/")) or ".." in suffix.split("/"):
            raise ForgeError("invalid repository API path")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        token = os.environ.get("GITEA_TOKEN")
        if token:
            headers["Authorization"] = "token " + token
        body = json.dumps(data).encode() if data is not None else None
        request = Request(self.api + self.repo_api + suffix, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=20) as response:
                payload = response.read(8 * 1024 * 1024 + 1)
                if len(payload) > 8 * 1024 * 1024:
                    raise ForgeError("Gitea response exceeded the size limit")
                return json.loads(payload) if payload else None
        except HTTPError as exc:
            raise ForgeError(f"Gitea {method} failed with HTTP {exc.code}") from exc
        except (URLError, OSError, ValueError) as exc:
            raise ForgeError("Gitea request or JSON decoding failed") from exc

    def pages(self, suffix):
        separator = "&" if "?" in suffix else "?"
        for page in range(1, 1001):
            batch = self.request("GET", f"{suffix}{separator}limit=50&page={page}")
            if not isinstance(batch, list):
                raise ForgeError("Gitea collection was not an array")
            yield from batch
            if len(batch) < 50:
                return
        raise ForgeError("Gitea pagination safety limit reached")

    def repository(self):
        result = self.request("GET", "")
        if result.get("full_name", "").casefold() != f"{self.owner}/{self.repo}".casefold():
            raise ForgeError("Gitea response names another repository")
        if result.get("clone_url", "").rstrip("/").removesuffix(".git") != self.url:
            raise ForgeError("Gitea clone URL differs from the configured repository")
        return result

    def open_issues(self):
        return [issue for issue in self.pages("/issues?state=open&type=issues")
                if issue.get("state") == "open" and not issue.get("pull_request")]


def project_binding(home, project):
    project = identifier(project, "project")
    binding = read_json(safe_child(home, f"config/gitea-projects/{project}.json"))
    if not binding or binding.get("project") != project:
        raise ForgeError("project has no valid Gitea binding; onboard it first")
    return binding
