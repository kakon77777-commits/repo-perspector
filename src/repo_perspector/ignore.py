from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .heuristics import IGNORE_DIRS


@dataclass(slots=True, frozen=True)
class IgnoreRule:
    pattern: str
    negate: bool = False
    directory_only: bool = False
    anchored: bool = False
    source: str = ""


def _parse_rules(path: Path) -> list[IgnoreRule]:
    if not path.is_file():
        return []
    rules: list[IgnoreRule] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for raw in lines:
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        negate = value.startswith("!")
        if negate:
            value = value[1:]
        if value.startswith("\\#") or value.startswith("\\!"):
            value = value[1:]
        anchored = value.startswith("/")
        if anchored:
            value = value[1:]
        directory_only = value.endswith("/")
        value = value.rstrip("/")
        if value:
            rules.append(IgnoreRule(value, negate, directory_only, anchored, path.name))
    return rules


class IgnoreMatcher:
    """Small dependency-free subset of gitignore semantics.

    Supports comments, negation, root anchoring, directory suffixes, *, ?, [] and **.
    Built-in generated/cache directories remain hard ignored for safety.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.rules = [*_parse_rules(self.root / ".gitignore"), *_parse_rules(self.root / ".perspectorignore")]
        self.ignored_files = 0
        self.ignored_directories = 0

    @staticmethod
    def _builtin(relative: PurePosixPath) -> bool:
        return any(part in IGNORE_DIRS or part.endswith(".egg-info") for part in relative.parts)

    @staticmethod
    def _matches(rule: IgnoreRule, path: str, is_dir: bool) -> bool:
        if rule.directory_only and not is_dir:
            # A directory rule also applies to descendants. Detect that below.
            pass
        pattern = rule.pattern
        if rule.anchored:
            return fnmatch.fnmatchcase(path, pattern) or path.startswith(pattern.rstrip("/") + "/")
        if "/" in pattern:
            return fnmatch.fnmatchcase(path, pattern) or path.startswith(pattern.rstrip("/") + "/")
        parts = PurePosixPath(path).parts
        return any(fnmatch.fnmatchcase(part, pattern) for part in parts)

    def should_ignore(self, relative: Path, *, is_dir: bool) -> bool:
        posix = PurePosixPath(relative.as_posix())
        if self._builtin(posix):
            ignored = True
        else:
            ignored = False
            text = posix.as_posix()
            for rule in self.rules:
                if self._matches(rule, text, is_dir):
                    ignored = not rule.negate
        if ignored:
            if is_dir:
                self.ignored_directories += 1
            else:
                self.ignored_files += 1
        return ignored

    def summary(self) -> dict[str, object]:
        return {
            "sources": [name for name in (".gitignore", ".perspectorignore") if (self.root / name).is_file()],
            "rule_count": len(self.rules),
            "ignored_files": self.ignored_files,
            "ignored_directories": self.ignored_directories,
        }
