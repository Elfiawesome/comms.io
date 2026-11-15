from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from comms.config import AppConfig
from comms.logging import get_logger
from comms.timeutil import iso_utc, now_ts

log = get_logger("publish")


class PublishError(RuntimeError):
    pass


class GitPublisher:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def publish(
        self,
        data_dir: str | Path,
        *,
        message: str | None = None,
        allow_large: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        source = Path(data_dir)
        if not source.exists():
            raise PublishError(f"Data directory does not exist: {source}")
        total_bytes = _tree_size(source)
        max_bytes = self.config.export.max_data_mb * 1024 * 1024
        if total_bytes > max_bytes and not allow_large:
            raise PublishError(
                f"Refusing to publish {total_bytes / 1024 / 1024:.1f} MB "
                f"(max_data_mb={self.config.export.max_data_mb}). Use --allow-large to override."
            )
        if dry_run:
            return {
                "pushed": False,
                "dry_run": True,
                "branch": self.config.publish.branch,
                "bytes": total_bytes,
                "message": message or _default_message(),
            }

        repo_root = Path(_run(["git", "rev-parse", "--show-toplevel"]).stdout.strip())
        remote_url = _run(
            ["git", "remote", "get-url", self.config.publish.remote],
            cwd=repo_root,
        ).stdout.strip()
        backup = self._backup(source)
        auth_dir, env = _auth_env()
        temp = Path(tempfile.mkdtemp(prefix="comms-publish-"))
        try:
            branch = self.config.publish.branch
            if self.config.publish.squash:
                # Do not download the previous snapshot just to replace it.
                _run(["git", "init", str(temp)])
                _run(["git", "-C", str(temp), "remote", "add", "origin", remote_url])
                _run(["git", "-C", str(temp), "checkout", "--orphan", branch])
            else:
                clone = _run(
                    [
                        "git",
                        "clone",
                        "--depth",
                        "1",
                        "--single-branch",
                        "--branch",
                        branch,
                        remote_url,
                        str(temp),
                    ],
                    env=env,
                    check=False,
                )
                if clone.returncode != 0:
                    log.info("Remote branch %s not found yet; creating an orphan branch", branch)
                    _run(["git", "init", str(temp)])
                    _run(["git", "-C", str(temp), "remote", "add", "origin", remote_url])
                    _run(["git", "-C", str(temp), "checkout", "--orphan", branch])

            # Always replace the full tree: stale shards must not survive an update.
            _clear_worktree(temp)
            _copy_tree(source, temp)
            _run(["git", "-C", str(temp), "add", "-A"])
            status = _run(["git", "-C", str(temp), "status", "--porcelain"]).stdout.strip()
            if not status:
                log.info("No data changes to publish")
                return {
                    "pushed": False,
                    "branch": branch,
                    "bytes": total_bytes,
                    "backup": str(backup) if backup else None,
                    "message": "no changes",
                }
            commit_message = message or _default_message()
            _run(
                [
                    "git",
                    "-C",
                    str(temp),
                    "-c",
                    "user.name=comms.io bot",
                    "-c",
                    "user.email=comms-io@users.noreply.github.com",
                    "commit",
                    "-m",
                    commit_message,
                ],
                env=env,
            )
            if self.config.publish.squash:
                _run(["git", "-C", str(temp), "push", "--force", "origin", branch], env=env)
            else:
                _run(["git", "-C", str(temp), "push", "origin", branch], env=env)
            commit = _run(["git", "-C", str(temp), "rev-parse", "HEAD"]).stdout.strip()
            log.info("Published %s to %s (%s)", source, branch, commit[:12])
            deploy_triggered = (
                self._trigger_deploy() if self.config.publish.trigger_deploy else False
            )
            return {
                "pushed": True,
                "branch": branch,
                "commit": commit,
                "bytes": total_bytes,
                "backup": str(backup) if backup else None,
                "message": commit_message,
                "deploy_triggered": deploy_triggered,
            }
        finally:
            shutil.rmtree(temp, ignore_errors=True)
            shutil.rmtree(auth_dir, ignore_errors=True)

    def _trigger_deploy(self) -> bool:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            log.warning(
                "GITHUB_TOKEN is not set; data was pushed but the Pages deploy was not triggered. "
                "Run the deploy-site workflow manually."
            )
            return False
        repo = self.config.publish.repo.strip("/")
        workflow = self.config.publish.deploy_workflow
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
        body = json.dumps({"ref": self.config.publish.deploy_ref}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "comms.io-publisher",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if 200 <= response.status < 300:
                    log.info("Triggered Pages deploy workflow %s", workflow)
                    return True
                log.warning("Pages deploy dispatch returned HTTP %s", response.status)
                return False
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            log.warning(
                "Could not trigger %s (HTTP %s): %s. "
                "The data branch is still updated; run the deploy workflow manually.",
                workflow,
                exc.code,
                detail,
            )
            return False
        except Exception as exc:
            log.warning("Could not trigger %s: %s", workflow, exc)
            return False

    def _backup(self, source: Path) -> Path | None:
        backup_dir_value = self.config.publish.backup_dir
        if not backup_dir_value:
            return None
        backup_dir = Path(backup_dir_value)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = iso_utc(now_ts()).replace(":", "").replace("-", "").replace(".", "")
        backup = backup_dir / f"data-{stamp}.tar.gz"
        with tarfile.open(backup, "w:gz") as archive:
            archive.add(source, arcname=source.name)
        log.info("Backed up data to %s", backup)
        return backup


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise PublishError(
            f"Command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
        )
    return result


def _auth_env() -> tuple[Path, dict[str, str]]:
    auth_dir = Path(tempfile.mkdtemp(prefix="comms-auth-"))
    env = os.environ.copy()
    token = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")
    if not token:
        return auth_dir, env
    env["GITHUB_TOKEN"] = token
    env["GIT_TERMINAL_PROMPT"] = "0"
    if os.name == "nt":
        askpass = auth_dir / "askpass.bat"
        askpass.write_text(
            "@echo off\n"
            'echo %~1 | findstr /I "username" >nul\n'
            "if %errorlevel%==0 (echo x-access-token) else (echo %GITHUB_TOKEN%)\n",
            encoding="utf-8",
        )
    else:
        askpass = auth_dir / "askpass.sh"
        askpass.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            "  *Username*) echo x-access-token ;;\n"
            '  *) echo "$GITHUB_TOKEN" ;;\n'
            "esac\n",
            encoding="utf-8",
        )
        askpass.chmod(0o700)
    env["GIT_ASKPASS"] = str(askpass)
    return auth_dir, env


def _clear_worktree(root: Path) -> None:
    for child in root.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _copy_tree(source: Path, target: Path) -> None:
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def _tree_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _default_message() -> str:
    return f"data: publish {iso_utc()}"
