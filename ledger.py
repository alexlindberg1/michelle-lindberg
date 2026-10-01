import base64
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path


class FileLedger:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]\n")

    def read(self):
        with self._lock:
            return self._read()

    def update(self, mutate):
        with self._lock:
            rows = mutate(self._read())
            self._write(rows)
            return rows

    def _read(self):
        raw = self.path.read_text() or "[]"
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Ledger file is not a list.")
        return data

    def _write(self, rows):
        self.path.write_text(json.dumps(rows, indent=2) + "\n")


class GitLedger:
    """Private GitHub repo used as the saved copy of the tracker.

    Render's free disk is wiped on every restart, so each change is committed
    to a private repository with a deploy key that can write only to that repo.
    """

    def __init__(self, repo_url, key_b64, branch="main"):
        self.repo_url = repo_url
        self.branch = branch
        self._lock = threading.Lock()
        self.root = Path(tempfile.mkdtemp(prefix="ledger-"))
        self.repo_dir = self.root / "repo"
        self.key_path = None
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        if key_b64:
            self.key_path = self.root / "id_ed25519"
            key = base64.b64decode(key_b64).decode()
            if not key.endswith("\n"):
                key += "\n"
            self.key_path.write_text(key)
            self.key_path.chmod(0o600)
            known = self.root / "known_hosts"
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {self.key_path} -o IdentitiesOnly=yes "
                f"-o UserKnownHostsFile={known} -o StrictHostKeyChecking=accept-new"
            )
        self.env = env
        self._run(
            ["git", "clone", "--branch", branch, repo_url, str(self.repo_dir)],
            cwd=self.root,
        )

    def read(self):
        with self._lock:
            self._pull()
            return self._read_file()

    def update(self, mutate):
        with self._lock:
            self._pull()
            rows = mutate(self._read_file())
            self._write_and_push(rows)
            return rows

    def _read_file(self):
        path = self.repo_dir / "applications.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text() or "[]")
        if not isinstance(data, list):
            raise ValueError("applications.json is not a list.")
        return data

    def _write_and_push(self, rows):
        path = self.repo_dir / "applications.json"
        path.write_text(json.dumps(rows, indent=2) + "\n")
        self._run(["git", "add", "applications.json"])
        status = self._run(["git", "status", "--porcelain"])
        if not status.stdout.strip():
            return
        self._run(
            [
                "git",
                "-c",
                "user.email=ledger@michellelind.com",
                "-c",
                "user.name=Application ledger",
                "commit",
                "-m",
                "Update applications",
            ]
        )
        self._run(["git", "push", "origin", f"HEAD:{self.branch}"])

    def _pull(self):
        self._run(["git", "pull", "--rebase", "origin", self.branch])

    def _run(self, args, cwd=None):
        completed = subprocess.run(
            args,
            cwd=cwd or self.repo_dir,
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(detail or f"git failed: {' '.join(args[:3])}")
        return completed
