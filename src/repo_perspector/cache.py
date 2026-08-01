from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import SymbolRecord
from .parsers import ImportMatch
from .symbols import RawCall

CACHE_SCHEMA = "repo-perspector.cache/v0.6"
PARSER_REVISION = "2026-07-14.2"


def content_fingerprint(
    content: bytes,
    *,
    language: str,
    module_name: str,
    component: str,
    parser_identity: str = "builtin",
) -> str:
    digest = hashlib.sha256()
    for value in (PARSER_REVISION, parser_identity, language, module_name, component):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    digest.update(content)
    return digest.hexdigest()


def default_cache_dir(root: Path, source_type: str, origin_url: str | None) -> Path:
    identity = f"{source_type}:{origin_url or root.resolve()}".encode("utf-8", errors="replace")
    key = hashlib.sha256(identity).hexdigest()[:20]
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "repo-perspector" / key


class AnalysisCache:
    def __init__(self, directory: Path | None, *, enabled: bool = True) -> None:
        self.enabled = bool(enabled and directory is not None)
        self.directory = directory
        self.path = directory / "analysis-cache.json" if directory is not None else None
        self.entries: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.invalidated = 0
        self.load_warning: str | None = None
        self._seen: set[str] = set()
        self._lock = threading.RLock()
        if self.enabled:
            self._load()

    def _load(self) -> None:
        assert self.path is not None
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != CACHE_SCHEMA:
                self.invalidated = len(payload.get("entries", {})) if isinstance(payload, dict) else 0
                return
            entries = payload.get("entries", {})
            if isinstance(entries, dict):
                self.entries = {str(key): value for key, value in entries.items() if isinstance(value, dict)}
        except (OSError, ValueError, TypeError) as exc:
            self.load_warning = f"cache load failed: {exc}"
            self.entries = {}

    def get(self, relative_path: str, fingerprint: str) -> tuple[list[ImportMatch], list[SymbolRecord], list[RawCall], int, int] | None:
        with self._lock:
            self._seen.add(relative_path)
            if not self.enabled:
                self.misses += 1
                return None
            entry = self.entries.get(relative_path)
            if not entry or entry.get("fingerprint") != fingerprint:
                if entry:
                    self.invalidated += 1
                    self.entries.pop(relative_path, None)
                self.misses += 1
                return None
            try:
                imports = [ImportMatch(**item) for item in entry.get("imports", [])]
                symbols = [SymbolRecord(**item) for item in entry.get("symbols", [])]
                calls = [RawCall(**item) for item in entry.get("calls", [])]
                line_count = int(entry.get("line_count", 0))
                complexity = int(entry.get("complexity", 0))
            except (TypeError, ValueError, KeyError):
                self.invalidated += 1
                self.entries.pop(relative_path, None)
                self.misses += 1
                return None
            self.hits += 1
            return imports, symbols, calls, line_count, complexity

    def put(
        self,
        relative_path: str,
        fingerprint: str,
        imports: list[ImportMatch],
        symbols: list[SymbolRecord],
        calls: list[RawCall],
        line_count: int,
        complexity: int,
    ) -> None:
        with self._lock:
            self._seen.add(relative_path)
            if not self.enabled:
                return
            self.entries[relative_path] = {
                "fingerprint": fingerprint,
                "imports": [asdict(item) for item in imports],
                "symbols": [asdict(item) for item in symbols],
                "calls": [asdict(item) for item in calls],
                "line_count": int(line_count),
                "complexity": int(complexity),
            }
            self.writes += 1

    def mark_seen(self, relative_path: str) -> None:
        with self._lock:
            self._seen.add(relative_path)

    def finalize(self) -> None:
        with self._lock:
            if not self.enabled or self.path is None or self.directory is None:
                return
            stale = [key for key in self.entries if key not in self._seen]
            for key in stale:
                self.entries.pop(key, None)
            self.invalidated += len(stale)
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": CACHE_SCHEMA,
                "parser_revision": PARSER_REVISION,
                "entries": dict(sorted(self.entries.items())),
            }
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            temporary.replace(self.path)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            return {
                "enabled": self.enabled,
                "path": str(self.path) if self.path else None,
                "schema_version": CACHE_SCHEMA,
                "parser_revision": PARSER_REVISION,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total else 0.0,
                "writes": self.writes,
                "invalidated": self.invalidated,
                "entry_count": len(self.entries),
                "warning": self.load_warning,
            }
