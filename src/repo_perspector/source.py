from __future__ import annotations

import re
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


_GITHUB_RE = re.compile(
    r"^(?:https?://github\.com/)?(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


@dataclass(slots=True)
class PreparedSource:
    path: Path
    display_name: str
    source_type: str
    origin_url: str | None
    branch: str | None
    commit: str | None
    _tempdir: tempfile.TemporaryDirectory[str] | None = None

    def cleanup(self) -> None:
        if self._tempdir is not None:
            self._tempdir.cleanup()


def parse_github_source(value: str) -> tuple[str, str] | None:
    match = _GITHUB_RE.match(value.strip())
    if not match:
        return None
    return match.group("owner"), match.group("repo")


def _run_git(args: list[str], cwd: Path | None = None) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
        return completed.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def _download_zip(owner: str, repo: str, destination: Path) -> tuple[Path, str]:
    last_error: Exception | None = None
    for branch in ("main", "master"):
        url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}"
        zip_path = destination / "repo.zip"
        try:
            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(destination)
            candidates = [p for p in destination.iterdir() if p.is_dir()]
            if not candidates:
                raise RuntimeError("Downloaded archive did not contain a directory")
            return candidates[0], branch
        except (urllib.error.URLError, zipfile.BadZipFile, RuntimeError) as exc:
            last_error = exc
            zip_path.unlink(missing_ok=True)
    raise RuntimeError(f"Unable to download GitHub repository: {last_error}")


def prepare_source(value: str, *, clone_depth: int = 300) -> PreparedSource:
    local = Path(value).expanduser()
    if local.exists():
        resolved = local.resolve()
        if not resolved.is_dir():
            raise ValueError(f"Source must be a directory: {resolved}")
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=resolved)
        commit = _run_git(["rev-parse", "HEAD"], cwd=resolved)
        origin = _run_git(["remote", "get-url", "origin"], cwd=resolved)
        return PreparedSource(
            path=resolved,
            display_name=resolved.name,
            source_type="local",
            origin_url=origin,
            branch=branch,
            commit=commit,
        )

    parsed = parse_github_source(value)
    if not parsed:
        raise ValueError("Source is neither an existing directory nor a valid GitHub URL/owner/repo")

    owner, repo = parsed
    tempdir = tempfile.TemporaryDirectory(prefix="repo-perspector-")
    temp_path = Path(tempdir.name)
    clone_path = temp_path / repo
    origin = f"https://github.com/{owner}/{repo}"

    cloned = _run_git(["clone", "--depth", str(max(1, clone_depth)), origin, str(clone_path)])
    if cloned is None or not clone_path.exists():
        clone_path, branch = _download_zip(owner, repo, temp_path)
        commit = None
    else:
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=clone_path)
        commit = _run_git(["rev-parse", "HEAD"], cwd=clone_path)

    return PreparedSource(
        path=clone_path,
        display_name=f"{owner}/{repo}",
        source_type="github",
        origin_url=origin,
        branch=branch,
        commit=commit,
        _tempdir=tempdir,
    )
