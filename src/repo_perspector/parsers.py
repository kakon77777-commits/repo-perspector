from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


EXTENSION_LANGUAGE = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".c": "C", ".h": "C/C++", ".cc": "C++", ".cpp": "C++", ".hpp": "C++",
    ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".scala": "Scala",
    ".sh": "Shell", ".sql": "SQL", ".vue": "Vue", ".svelte": "Svelte",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".md": "Markdown",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
}


@dataclass(slots=True, frozen=True)
class ImportMatch:
    value: str
    line: int
    excerpt: str


def language_for(path: Path) -> str:
    return EXTENSION_LANGUAGE.get(path.suffix.lower(), "Other")


def _line_excerpt(text: str, line: int) -> str:
    lines = text.splitlines()
    if 1 <= line <= len(lines):
        return lines[line - 1].strip()[:240]
    return ""


def _python_import_matches(text: str, module_name: str) -> list[ImportMatch]:
    tree = ast.parse(text)
    matches: list[ImportMatch] = []
    current_package = module_name.split(".")[:-1]
    for node in ast.walk(tree):
        values: list[str] = []
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                trim = max(0, len(current_package) - node.level + 1)
                base = current_package[:trim]
            else:
                base = []
            if node.module:
                base.extend(node.module.split("."))
            prefix = ".".join(base)
            if prefix:
                values.append(prefix)
            for alias in node.names:
                candidate = ".".join([*base, alias.name]) if base else alias.name
                values.append(candidate)
        for value in values:
            matches.append(ImportMatch(value=value, line=int(getattr(node, "lineno", 1)), excerpt=_line_excerpt(text, int(getattr(node, "lineno", 1)))))
    unique: dict[tuple[str, int], ImportMatch] = {}
    for item in matches:
        unique[(item.value, item.line)] = item
    return sorted(unique.values(), key=lambda item: (item.line, item.value))


_JS_IMPORT_RE = re.compile(
    r"(?:import\s+(?:[^;]*?\s+from\s+)?|export\s+[^;]*?\s+from\s+|require\s*\()"
    r"[\"']([^\"']+)[\"']"
)
_DYNAMIC_JS_RE = re.compile(r"import\s*\(\s*[\"']([^\"']+)[\"']\s*\)")
_GO_IMPORT_RE = re.compile(r"[\"`]([^\"`]+)[\"`]")
_RUST_USE_RE = re.compile(r"^\s*(?:pub\s+)?use\s+([^;]+);", re.MULTILINE)
_RUST_MOD_RE = re.compile(r"^\s*(?:pub\s+)?mod\s+([A-Za-z_][A-Za-z0-9_]*);", re.MULTILINE)
_JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([A-Za-z0-9_.*]+);", re.MULTILINE)


def _regex_matches(text: str, regex: re.Pattern[str], transform=lambda value: value) -> list[ImportMatch]:
    results: list[ImportMatch] = []
    for match in regex.finditer(text):
        value = transform(match.group(1))
        line = text.count("\n", 0, match.start()) + 1
        results.append(ImportMatch(value=value, line=line, excerpt=_line_excerpt(text, line)))
    return results


def parse_import_matches(path: Path, text: str, module_name: str) -> list[ImportMatch]:
    language = language_for(path)
    if language == "Python":
        return _python_import_matches(text, module_name)
    if language in {"JavaScript", "TypeScript", "Vue", "Svelte"}:
        values = _regex_matches(text, _JS_IMPORT_RE) + _regex_matches(text, _DYNAMIC_JS_RE)
        unique = {(item.value, item.line): item for item in values}
        return sorted(unique.values(), key=lambda item: (item.line, item.value))
    if language == "Go":
        results: list[ImportMatch] = []
        in_block = False
        for line_number, line_text in enumerate(text.splitlines(), start=1):
            stripped = line_text.strip()
            if stripped.startswith("import ("):
                in_block = True
                continue
            if in_block and stripped == ")":
                in_block = False
                continue
            if in_block or stripped.startswith("import "):
                for value in _GO_IMPORT_RE.findall(stripped):
                    results.append(ImportMatch(value=value, line=line_number, excerpt=stripped[:240]))
        return results
    if language == "Rust":
        results = _regex_matches(text, _RUST_USE_RE, lambda value: value.split("::{", 1)[0].replace(" ", ""))
        results.extend(_regex_matches(text, _RUST_MOD_RE, lambda value: f"crate::{value}"))
        return sorted(results, key=lambda item: (item.line, item.value))
    if language in {"Java", "Kotlin"}:
        return _regex_matches(text, _JAVA_IMPORT_RE)
    return []


def parse_imports(path: Path, text: str, module_name: str) -> list[str]:
    return sorted({item.value for item in parse_import_matches(path, text, module_name)})


def module_name_for(path: Path, root: Path, source_roots: list[Path]) -> str:
    absolute = path.resolve()
    selected = root
    for candidate in source_roots:
        try:
            absolute.relative_to(candidate.resolve())
            if len(candidate.parts) > len(selected.parts):
                selected = candidate
        except ValueError:
            continue
    relative = absolute.relative_to(selected.resolve())
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] in {"__init__", "index", "mod"}:
        parts = parts[:-1]
    return ".".join(parts)
