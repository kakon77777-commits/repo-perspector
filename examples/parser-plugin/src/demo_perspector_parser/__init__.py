from __future__ import annotations

from repo_perspector.models import SymbolRecord
from repo_perspector.parser_plugins import ParseResult
from repo_perspector.parsers import ImportMatch


class DemoParser:
    """Minimal parser plugin for files ending in .xyz."""

    name = "demo-xyz-parser"
    version = "0.1.0"
    extensions = {".xyz": "XLang"}

    def parse(self, path, text, module_name, relative_path, component):
        symbols = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("fn "):
                name = stripped[3:].split("(", 1)[0].strip()
                qualified = ".".join(part for part in (module_name, name) if part)
                symbols.append(SymbolRecord(
                    id=f"{relative_path}:{line_number}:{qualified}",
                    qualified_name=qualified,
                    name=name,
                    kind="function",
                    path=relative_path,
                    component=component,
                    language="XLang",
                    line_start=line_number,
                    line_end=line_number,
                    signature=f"{name}()",
                ))
        imports = [
            ImportMatch(line.split(None, 1)[1].strip(), number, line.strip())
            for number, line in enumerate(text.splitlines(), start=1)
            if line.strip().startswith("use ")
        ]
        return ParseResult(imports=imports, symbols=symbols, complexity=1)
