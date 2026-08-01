from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from .ignore import IgnoreMatcher


@dataclass(slots=True)
class ScanResult:
    paths: list[Path]
    skipped_limit: bool
    time_budget_exceeded: bool
    ignore: dict[str, Any]


def scan_paths(root: Path, *, max_files: int, deadline: float | None) -> ScanResult:
    matcher = IgnoreMatcher(root)
    paths: list[Path] = []
    skipped_limit = False
    time_budget_exceeded = False
    for current, dirs, files in os.walk(root):
        if deadline is not None and monotonic() >= deadline:
            time_budget_exceeded = True
            break
        current_path = Path(current)
        rel_dir = current_path.relative_to(root)
        dirs[:] = [
            directory for directory in sorted(dirs)
            if not matcher.should_ignore(rel_dir / directory, is_dir=True)
        ]
        for filename in sorted(files):
            relative = rel_dir / filename
            if matcher.should_ignore(relative, is_dir=False):
                continue
            paths.append(relative)
            if len(paths) >= max_files:
                skipped_limit = True
                break
        if skipped_limit:
            break
    return ScanResult(sorted(paths), skipped_limit, time_budget_exceeded, matcher.summary())
