from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import SymbolRecord, SymbolRelationship
from .parsers import language_for


@dataclass(slots=True)
class RawCall:
    source: str
    target: str
    path: str
    line: int
    excerpt: str


def _visibility(name: str) -> str:
    if name.startswith("__") and name.endswith("__"):
        return "dunder"
    if name.startswith("_"):
        return "private"
    return "public"


def _complexity(node: ast.AST) -> int:
    decision_nodes = (
        ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.BoolOp,
        ast.IfExp, ast.comprehension, ast.Match, ast.ExceptHandler,
    )
    return 1 + sum(1 for child in ast.walk(node) if isinstance(child, decision_nodes))


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        value = ast.unparse(node.args)
    except Exception:
        value = "..."
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}{node.name}({value})"


def _python_symbols(
    path: Path,
    text: str,
    module_name: str,
    relative_path: str,
    component: str,
) -> tuple[list[SymbolRecord], list[RawCall], int]:
    tree = ast.parse(text)
    lines = text.splitlines()
    symbols: list[SymbolRecord] = []
    calls: list[RawCall] = []
    alias_map: dict[str, str] = {}

    current_package = module_name.split(".")[:-1]
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                alias_map[alias.asname or alias.name.split(".", 1)[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            base: list[str] = []
            if node.level:
                trim = max(0, len(current_package) - node.level + 1)
                base = current_package[:trim]
            if node.module:
                base.extend(node.module.split("."))
            for alias in node.names:
                alias_map[alias.asname or alias.name] = ".".join([*base, alias.name]) if base else alias.name

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []
            self.current_symbol: str | None = None

        def _qualified(self, name: str) -> str:
            parts = [part for part in [module_name, *self.stack, name] if part]
            return ".".join(parts)

        def _record(self, node: ast.AST, name: str, kind: str, signature: str = "") -> str:
            qualified = self._qualified(name)
            doc = ast.get_docstring(node, clean=True) if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) else None
            record = SymbolRecord(
                id=f"{relative_path}:{int(getattr(node, 'lineno', 1))}:{qualified}",
                qualified_name=qualified,
                name=name,
                kind=kind,
                path=relative_path,
                component=component,
                language="Python",
                line_start=int(getattr(node, "lineno", 1)),
                line_end=int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                signature=signature,
                visibility=_visibility(name),
                parent=".".join([module_name, *self.stack]) or None,
                complexity=_complexity(node),
                docstring=(doc.splitlines()[0][:240] if doc else None),
            )
            symbols.append(record)
            return qualified

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            qualified = self._record(node, node.name, "class", f"class {node.name}")
            previous = self.current_symbol
            self.current_symbol = qualified
            self.stack.append(node.name)
            for child in node.body:
                self.visit(child)
            self.stack.pop()
            self.current_symbol = previous

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            kind = "method" if self.stack else "function"
            qualified = self._record(node, node.name, kind, _signature(node))
            previous = self.current_symbol
            self.current_symbol = qualified
            self.stack.append(node.name)
            for child in node.body:
                self.visit(child)
            self.stack.pop()
            self.current_symbol = previous

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)

        def visit_Call(self, node: ast.Call) -> None:
            if self.current_symbol:
                target = _call_name(node.func)
                if target:
                    first, *rest = target.split(".")
                    if first in alias_map:
                        target = ".".join([alias_map[first], *rest]) if rest else alias_map[first]
                    line = int(getattr(node, "lineno", 1))
                    excerpt = lines[line - 1].strip()[:240] if 1 <= line <= len(lines) else ""
                    calls.append(RawCall(self.current_symbol, target, relative_path, line, excerpt))
            self.generic_visit(node)

    Visitor().visit(tree)
    file_complexity = 1 + sum(1 for child in ast.walk(tree) if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.BoolOp, ast.Match)))
    return symbols, calls, file_complexity


_DECLARATION_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "JavaScript": [
        ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)", re.MULTILINE)),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", re.MULTILINE)),
    ],
    "TypeScript": [
        ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
        ("type", re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*=", re.MULTILINE)),
        ("enum", re.compile(r"^\s*(?:export\s+)?enum\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
        ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)", re.MULTILINE)),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", re.MULTILINE)),
    ],
    "Go": [
        ("type", re.compile(r"^\s*type\s+([A-Za-z_][\w]*)\s+(?:struct|interface)\b", re.MULTILINE)),
        ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)\s*\(([^)]*)\)", re.MULTILINE)),
    ],
    "Rust": [
        ("struct", re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_][\w]*)", re.MULTILINE)),
        ("enum", re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Za-z_][\w]*)", re.MULTILINE)),
        ("trait", re.compile(r"^\s*(?:pub\s+)?trait\s+([A-Za-z_][\w]*)", re.MULTILINE)),
        ("function", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_][\w]*)\s*\(([^)]*)\)", re.MULTILINE)),
    ],
    "Java": [
        ("class", re.compile(r"^\s*(?:public|protected|private|abstract|final|static|sealed|non-sealed|\s)+\s*(?:class|interface|enum|record)\s+([A-Za-z_][\w]*)", re.MULTILINE)),
        ("method", re.compile(r"^\s*(?:public|protected|private|static|final|abstract|synchronized|native|\s)+[\w<>\[\], ?]+\s+([A-Za-z_][\w]*)\s*\(([^)]*)\)\s*(?:throws[^\{]+)?\{", re.MULTILINE)),
    ],
    "Kotlin": [
        ("class", re.compile(r"^\s*(?:public|private|internal|protected|open|data|sealed|abstract|\s)*(?:class|interface|object|enum class)\s+([A-Za-z_][\w]*)", re.MULTILINE)),
        ("function", re.compile(r"^\s*(?:public|private|internal|protected|open|override|suspend|inline|\s)*fun\s+([A-Za-z_][\w]*)\s*\(([^)]*)\)", re.MULTILINE)),
    ],
    "C#": [
        ("class", re.compile(r"^\s*(?:public|private|internal|protected|abstract|sealed|static|partial|\s)*(?:class|interface|record|struct|enum)\s+([A-Za-z_][\w]*)", re.MULTILINE)),
        ("method", re.compile(r"^\s*(?:public|private|internal|protected|static|virtual|override|async|sealed|abstract|\s)+[\w<>\[\], ?]+\s+([A-Za-z_][\w]*)\s*\(([^)]*)\)", re.MULTILINE)),
    ],
}


def _regex_symbols(
    path: Path,
    text: str,
    module_name: str,
    relative_path: str,
    component: str,
) -> tuple[list[SymbolRecord], list[RawCall], int]:
    language = language_for(path)
    patterns = _DECLARATION_PATTERNS.get(language, _DECLARATION_PATTERNS.get("JavaScript", []) if language in {"Vue", "Svelte"} else [])
    symbols: list[SymbolRecord] = []
    seen: set[tuple[str, int, str]] = set()
    for kind, pattern in patterns:
        for match in pattern.finditer(text):
            name = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            key = (name, line, kind)
            if key in seen:
                continue
            seen.add(key)
            signature = f"{name}({match.group(2).strip()})" if match.lastindex and match.lastindex >= 2 and match.group(2) is not None else name
            qualified = ".".join(part for part in [module_name, name] if part)
            segment = text[match.start(): min(len(text), match.start() + 1600)]
            complexity = 1 + len(re.findall(r"\b(?:if|for|while|case|catch|match|switch)\b|&&|\|\|", segment))
            symbols.append(SymbolRecord(
                id=f"{relative_path}:{line}:{qualified}",
                qualified_name=qualified,
                name=name,
                kind=kind,
                path=relative_path,
                component=component,
                language=language,
                line_start=line,
                line_end=line,
                signature=signature,
                visibility=_visibility(name),
                parent=module_name or None,
                complexity=complexity,
            ))
    file_complexity = 1 + len(re.findall(r"\b(?:if|for|while|case|catch|match|switch)\b|&&|\|\|", text))
    return symbols, [], file_complexity


def extract_symbols(
    path: Path,
    text: str,
    module_name: str,
    relative_path: str,
    component: str,
) -> tuple[list[SymbolRecord], list[RawCall], int]:
    language = language_for(path)
    if language == "Python":
        return _python_symbols(path, text, module_name, relative_path, component)
    return _regex_symbols(path, text, module_name, relative_path, component)


def resolve_symbol_relationships(symbols: Iterable[SymbolRecord], raw_calls: Iterable[RawCall]) -> list[SymbolRelationship]:
    symbols = list(symbols)
    by_qualified = {symbol.qualified_name: symbol for symbol in symbols}
    by_simple: dict[str, list[SymbolRecord]] = defaultdict(list)
    by_path: dict[str, list[SymbolRecord]] = defaultdict(list)
    for symbol in symbols:
        by_simple[symbol.name].append(symbol)
        by_path[symbol.path].append(symbol)

    evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
    for call in raw_calls:
        target: SymbolRecord | None = None
        candidate = call.target.replace("::", ".")
        if candidate in by_qualified:
            target = by_qualified[candidate]
        else:
            source_symbol = by_qualified.get(call.source)
            source_module = source_symbol.qualified_name.rsplit(".", 1)[0] if source_symbol and "." in source_symbol.qualified_name else ""
            local_candidate = f"{source_module}.{candidate}" if source_module else candidate
            if local_candidate in by_qualified:
                target = by_qualified[local_candidate]
            else:
                simple = candidate.rsplit(".", 1)[-1]
                same_file = [item for item in by_path.get(call.path, []) if item.name == simple]
                if len(same_file) == 1:
                    target = same_file[0]
                elif len(by_simple.get(simple, [])) == 1:
                    target = by_simple[simple][0]
        if target and target.qualified_name != call.source:
            key = (call.source, target.qualified_name)
            item = f"{call.path}:{call.line}: {call.excerpt}"
            if item not in evidence[key] and len(evidence[key]) < 20:
                evidence[key].append(item)

    return [
        SymbolRelationship(source=source, target=target, kind="call", evidence=values, count=len(values))
        for (source, target), values in sorted(evidence.items())
    ]
