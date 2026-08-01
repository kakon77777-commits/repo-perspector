from __future__ import annotations

from typing import Any

from .models import ArchitectureReport


def build_query_index(report: ArchitectureReport) -> dict[str, Any]:
    components = {}
    tokens: dict[str, list[str]] = {}
    for component in report.components:
        components[component.path] = {
            "path": component.path,
            "name": component.name,
            "role": component.role,
            "stability": component.stability,
            "risk_tier": component.impact.get("risk_tier", "unknown"),
            "risk_score": component.impact.get("risk_score", 0.0),
            "hotspot_score": component.metrics.get("hotspot_score", 0.0),
            "dependencies": component.internal_dependencies,
            "dependents": component.dependents,
            "files": component.files,
        }
        words = set((component.path + " " + component.name + " " + component.role + " " + component.description).lower().replace("/", " ").replace("_", " ").split())
        for word in words:
            if len(word) >= 2:
                tokens.setdefault(word, []).append(component.path)
    symbols = {
        symbol.qualified_name: {
            "qualified_name": symbol.qualified_name,
            "name": symbol.name,
            "kind": symbol.kind,
            "path": symbol.path,
            "line": symbol.line_start,
            "component": symbol.component,
            "language": symbol.language,
        }
        for symbol in report.symbols
    }
    return {
        "schema_version": "repo-perspector.index/v0.6",
        "generated_at": report.generated_at,
        "project": {"name": report.project.get("name"), "commit": report.project.get("commit")},
        "components": components,
        "symbols": symbols,
        "tokens": {key: sorted(set(value)) for key, value in sorted(tokens.items())},
    }
