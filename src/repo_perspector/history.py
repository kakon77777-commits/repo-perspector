from __future__ import annotations

import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any


def _run_git(root: Path, args: list[str], timeout: int = 180) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=root, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return completed.stdout
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _normalize_rename(path: str) -> str:
    value = path.strip()
    if " => " not in value:
        return value
    if "{" in value and "}" in value:
        start = value.find("{")
        end = value.find("}", start)
        if end > start:
            inside = value[start + 1 : end]
            destination = inside.split(" => ", 1)[-1]
            return value[:start] + destination + value[end + 1 :]
    return value.split(" => ", 1)[-1]


def _empty_result(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason, "repository": {}, "files": {}, "components": {}, "cochange": []}


def collect_git_history(root: Path, file_component: dict[str, str], *, max_commits: int = 300) -> dict[str, Any]:
    """Collect bounded Git churn and component co-change coupling metrics."""
    if max_commits <= 0:
        return _empty_result("git history disabled")

    repo_root = _run_git(root, ["rev-parse", "--show-toplevel"])
    if not repo_root:
        return _empty_result("not a Git work tree or Git is unavailable")

    repo_root_path = Path(repo_root.strip()).resolve()
    try:
        root_prefix = root.resolve().relative_to(repo_root_path).as_posix().strip(".")
    except ValueError:
        root_prefix = ""
    root_prefix = root_prefix.strip("/")

    branch = (_run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"]) or "").strip() or None
    head = (_run_git(root, ["rev-parse", "HEAD"]) or "").strip() or None
    dirty_output = _run_git(root, ["status", "--porcelain"])
    dirty = bool(dirty_output and dirty_output.strip())

    pretty = "%x1e%H%x1f%aI%x1f%an%x1f%ae"
    log = _run_git(
        root,
        ["log", f"--max-count={max_commits}", "--date=iso-strict", f"--pretty=format:{pretty}", "--numstat", "--find-renames", "--", "."],
        timeout=240,
    )
    if log is None:
        return _empty_result("unable to read Git log")

    file_stats: dict[str, dict[str, Any]] = {}
    commit_ids: set[str] = set()
    all_authors: set[str] = set()
    commit_dates: list[datetime] = []
    commit_components: list[set[str]] = []

    for chunk in log.split("\x1e"):
        chunk = chunk.strip("\n\r ")
        if not chunk:
            continue
        lines = chunk.splitlines()
        metadata = lines[0].split("\x1f")
        if len(metadata) < 4:
            continue
        commit, date_text, author_name, author_email = metadata[:4]
        commit_ids.add(commit)
        author = f"{author_name} <{author_email}>".strip()
        all_authors.add(author)
        changed_at = _parse_datetime(date_text)
        if changed_at:
            commit_dates.append(changed_at)
        changed_components: set[str] = set()

        for line in lines[1:]:
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            additions_text, deletions_text, raw_path = parts
            path = _normalize_rename(raw_path).replace("\\", "/")
            if root_prefix and path.startswith(root_prefix + "/"):
                path = path[len(root_prefix) + 1 :]
            if path not in file_component:
                continue
            changed_components.add(file_component[path])
            additions = int(additions_text) if additions_text.isdigit() else 0
            deletions = int(deletions_text) if deletions_text.isdigit() else 0
            record = file_stats.setdefault(path, {
                "commit_ids": set(), "authors": set(), "additions": 0, "deletions": 0,
                "first_changed_at": None, "last_changed_at": None,
            })
            record["commit_ids"].add(commit)
            record["authors"].add(author)
            record["additions"] += additions
            record["deletions"] += deletions
            if changed_at:
                first = record["first_changed_at"]
                last = record["last_changed_at"]
                record["first_changed_at"] = changed_at if first is None or changed_at < first else first
                record["last_changed_at"] = changed_at if last is None or changed_at > last else last
        if changed_components:
            commit_components.append(changed_components)

    analyzed_commits = len(commit_ids)
    now = datetime.now(timezone.utc)
    serialized_files: dict[str, dict[str, Any]] = {}
    component_accumulator: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "commit_ids": set(), "authors": set(), "additions": 0, "deletions": 0,
        "first_changed_at": None, "last_changed_at": None, "changed_files": 0,
    })

    for path, raw in file_stats.items():
        commits = len(raw["commit_ids"])
        additions = int(raw["additions"])
        deletions = int(raw["deletions"])
        churn = additions + deletions
        last_changed = raw["last_changed_at"]
        serialized_files[path] = {
            "commit_count": commits,
            "author_count": len(raw["authors"]),
            "additions": additions,
            "deletions": deletions,
            "churn": churn,
            "change_frequency": round(commits / max(1, analyzed_commits), 4),
            "first_changed_at": raw["first_changed_at"].isoformat() if raw["first_changed_at"] else None,
            "last_changed_at": last_changed.isoformat() if last_changed else None,
            "age_days": (now - last_changed).days if last_changed else None,
        }
        component = file_component[path]
        acc = component_accumulator[component]
        acc["commit_ids"].update(raw["commit_ids"])
        acc["authors"].update(raw["authors"])
        acc["additions"] += additions
        acc["deletions"] += deletions
        acc["changed_files"] += 1
        first = raw["first_changed_at"]
        last = raw["last_changed_at"]
        if first and (acc["first_changed_at"] is None or first < acc["first_changed_at"]):
            acc["first_changed_at"] = first
        if last and (acc["last_changed_at"] is None or last > acc["last_changed_at"]):
            acc["last_changed_at"] = last

    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for changed in commit_components:
        for left, right in combinations(sorted(changed), 2):
            pair_counts[(left, right)] += 1

    serialized_components: dict[str, dict[str, Any]] = {}
    max_churn = max((int(value["additions"]) + int(value["deletions"]) for value in component_accumulator.values()), default=0)
    neighbor_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cochange: list[dict[str, Any]] = []
    component_commit_counts = {name: len(raw["commit_ids"]) for name, raw in component_accumulator.items()}
    for (left, right), joint in pair_counts.items():
        left_count = component_commit_counts.get(left, 0)
        right_count = component_commit_counts.get(right, 0)
        confidence = joint / max(1, min(left_count, right_count))
        jaccard = joint / max(1, left_count + right_count - joint)
        record = {
            "left": left, "right": right, "joint_commits": joint,
            "confidence": round(confidence, 4), "jaccard": round(jaccard, 4),
        }
        cochange.append(record)
        neighbor_map[left].append({"component": right, **{k: v for k, v in record.items() if k not in {"left", "right"}}})
        neighbor_map[right].append({"component": left, **{k: v for k, v in record.items() if k not in {"left", "right"}}})

    for component, raw in component_accumulator.items():
        commit_count = len(raw["commit_ids"])
        churn = int(raw["additions"]) + int(raw["deletions"])
        last_changed = raw["last_changed_at"]
        neighbors = sorted(neighbor_map.get(component, []), key=lambda item: (-float(item["confidence"]), -int(item["joint_commits"]), str(item["component"])))[:30]
        serialized_components[component] = {
            "commit_count": commit_count,
            "author_count": len(raw["authors"]),
            "changed_files": int(raw["changed_files"]),
            "additions": int(raw["additions"]),
            "deletions": int(raw["deletions"]),
            "churn": churn,
            "normalized_churn": round(churn / max(1, max_churn), 4),
            "change_frequency": round(commit_count / max(1, analyzed_commits), 4),
            "first_changed_at": raw["first_changed_at"].isoformat() if raw["first_changed_at"] else None,
            "last_changed_at": last_changed.isoformat() if last_changed else None,
            "age_days": (now - last_changed).days if last_changed else None,
            "cochange_neighbors": neighbors,
        }

    first_commit = min(commit_dates).isoformat() if commit_dates else None
    last_commit = max(commit_dates).isoformat() if commit_dates else None
    top_churn_files = sorted(
        ({"path": path, **metrics} for path, metrics in serialized_files.items()),
        key=lambda item: (-int(item["churn"]), -int(item["commit_count"]), str(item["path"])),
    )[:50]
    cochange.sort(key=lambda item: (-float(item["confidence"]), -int(item["joint_commits"]), str(item["left"]), str(item["right"])))

    return {
        "available": True,
        "reason": None,
        "repository": {
            "root": repo_root.strip(), "branch": branch, "head": head, "dirty": dirty,
            "max_commits_requested": max_commits, "commit_count_analyzed": analyzed_commits,
            "author_count": len(all_authors), "first_commit_at": first_commit, "last_commit_at": last_commit,
            "files_with_history": len(serialized_files), "components_with_history": len(serialized_components),
            "top_churn_files": top_churn_files, "cochange_pair_count": len(cochange),
        },
        "files": dict(sorted(serialized_files.items())),
        "components": dict(sorted(serialized_components.items())),
        "cochange": cochange[:200],
    }
