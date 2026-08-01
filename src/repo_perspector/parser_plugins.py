from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import SymbolRecord
from .parsers import EXTENSION_LANGUAGE, ImportMatch, language_for as builtin_language_for, parse_import_matches
from .symbols import RawCall, extract_symbols


@dataclass(slots=True)
class ParseResult:
    imports: list[ImportMatch] = field(default_factory=list)
    symbols: list[SymbolRecord] = field(default_factory=list)
    calls: list[RawCall] = field(default_factory=list)
    complexity: int = 0


@runtime_checkable
class ParserPlugin(Protocol):
    name: str
    version: str
    extensions: dict[str, str]

    def parse(
        self,
        path: Path,
        text: str,
        module_name: str,
        relative_path: str,
        component: str,
    ) -> ParseResult: ...


class BuiltinParserPlugin:
    name = "repo-perspector-builtins"
    version = "0.6.0"
    extensions = dict(EXTENSION_LANGUAGE)

    def parse(self, path: Path, text: str, module_name: str, relative_path: str, component: str) -> ParseResult:
        imports = parse_import_matches(path, text, module_name)
        symbols, calls, complexity = extract_symbols(path, text, module_name, relative_path, component)
        return ParseResult(imports, symbols, calls, complexity)


class ParserRegistry:
    def __init__(self, *, load_plugins: bool = True) -> None:
        self._by_extension: dict[str, ParserPlugin] = {}
        self.loaded: list[dict[str, object]] = []
        self.errors: list[str] = []
        self.register(BuiltinParserPlugin(), source="builtin")
        if load_plugins:
            self.load_entry_points()

    def register(self, plugin: ParserPlugin, *, source: str = "manual") -> None:
        if not isinstance(plugin, ParserPlugin):
            raise TypeError("parser plugin does not satisfy ParserPlugin protocol")
        extensions = {str(key).lower(): str(value) for key, value in plugin.extensions.items()}
        if not extensions:
            raise ValueError("parser plugin must declare at least one extension")
        for extension in extensions:
            if not extension.startswith("."):
                raise ValueError(f"invalid parser extension: {extension}")
            self._by_extension[extension] = plugin
        self.loaded.append({
            "name": plugin.name,
            "version": plugin.version,
            "source": source,
            "extensions": sorted(extensions),
            "languages": sorted(set(extensions.values())),
        })

    def load_entry_points(self) -> None:
        try:
            points = metadata.entry_points()
            selected = points.select(group="repo_perspector.parsers") if hasattr(points, "select") else points.get("repo_perspector.parsers", [])
        except Exception as exc:  # packaging metadata varies across environments
            self.errors.append(f"entry point discovery failed: {exc}")
            return
        for point in selected:
            try:
                loaded = point.load()
                plugin = loaded() if isinstance(loaded, type) else loaded
                self.register(plugin, source=f"entry-point:{point.name}")
            except Exception as exc:
                self.errors.append(f"parser plugin {getattr(point, 'name', '?')} failed: {exc}")

    def language_for(self, path: Path) -> str:
        plugin = self._by_extension.get(path.suffix.lower())
        if plugin is None:
            return builtin_language_for(path)
        return plugin.extensions.get(path.suffix.lower(), "Other")

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self._by_extension

    def parser_identity(self, path: Path) -> str:
        plugin = self._by_extension.get(path.suffix.lower())
        return f"{plugin.name}@{plugin.version}" if plugin else "unsupported"

    def parse(self, path: Path, text: str, module_name: str, relative_path: str, component: str) -> ParseResult:
        plugin = self._by_extension.get(path.suffix.lower())
        if plugin is None:
            return ParseResult()
        return plugin.parse(path, text, module_name, relative_path, component)

    def summary(self) -> dict[str, object]:
        return {
            "loaded": self.loaded,
            "errors": self.errors,
            "extension_count": len(self._by_extension),
        }
