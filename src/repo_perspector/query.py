from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from .diffing import load_report_path


class ReportIndex:
    """Read-only query facade shared by CLI/MCP integrations."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        self.components = {
            str(component["path"]): component
            for component in report.get("components", [])
            if isinstance(component, dict) and "path" in component
        }
        self.symbols = {
            str(symbol["qualified_name"]): symbol
            for symbol in report.get("symbols", [])
            if isinstance(symbol, dict) and "qualified_name" in symbol
        }
        self.edges = {name: list(component.get("internal_dependencies", [])) for name, component in self.components.items()}
        self.workspaces = [item for item in report.get("workspaces", []) if isinstance(item, dict)]

    @classmethod
    def from_path(cls, value: str | Path) -> "ReportIndex":
        return cls(load_report_path(value))

    def overview(self) -> dict[str, Any]:
        return {
            "schema_version": self.report.get("schema_version"),
            "project": self.report.get("project", {}),
            "analysis": self.report.get("analysis", {}),
            "architecture": self.report.get("architecture", {}),
            "quality": self.report.get("quality", {}),
            "policy": self.report.get("policy", {}),
            "history": self.report.get("history", {}).get("repository", {}),
            "workspaces": self.report.get("workspaces", []),
            "cycles": self.report.get("cycles", []),
            "warnings": self.report.get("warnings", []),
        }

    def list_workspaces(self, *, query: str = "", ecosystem: str = "", limit: int = 100) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        values: list[dict[str, Any]] = []
        for workspace in self.workspaces:
            haystack = " ".join(str(workspace.get(key, "")) for key in ("path", "name", "ecosystem", "manifest")).lower()
            if needle and needle not in haystack:
                continue
            if ecosystem and workspace.get("ecosystem") != ecosystem:
                continue
            values.append(workspace)
        values.sort(key=lambda item: (str(item.get("path", ".")) != ".", str(item.get("path", ""))))
        return values[: max(1, min(limit, 500))]

    def list_components(self, *, query: str = "", stability: str = "", role: str = "", risk_tier: str = "", limit: int = 50) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        values = []
        for component in self.components.values():
            haystack = " ".join(str(component.get(key, "")) for key in ("path", "role", "description", "stability")).lower()
            if needle and needle not in haystack:
                continue
            if stability and component.get("stability") != stability:
                continue
            if role and component.get("role") != role:
                continue
            if risk_tier and (component.get("impact") or {}).get("risk_tier") != risk_tier:
                continue
            values.append(component)
        values.sort(key=lambda item: (
            -float((item.get("impact") or {}).get("risk_score", 0.0)),
            -float((item.get("metrics") or {}).get("hotspot_score", 0.0)),
            -float(item.get("centrality", 0.0)), str(item.get("path", "")),
        ))
        return values[: max(1, min(limit, 500))]

    def get_component(self, path: str) -> dict[str, Any]:
        if path not in self.components:
            raise ValueError(f"Unknown component: {path}")
        return self.components[path]

    def dependency_path(self, source: str, target: str) -> dict[str, Any]:
        if source not in self.components or target not in self.components:
            raise ValueError("Both source and target must be existing component paths")
        queue: deque[str] = deque([source])
        previous: dict[str, str | None] = {source: None}
        while queue:
            node = queue.popleft()
            if node == target:
                break
            for neighbor in sorted(self.edges.get(node, [])):
                if neighbor not in previous:
                    previous[neighbor] = node
                    queue.append(neighbor)
        if target not in previous:
            return {"found": False, "source": source, "target": target, "path": []}
        path: list[str] = []
        current: str | None = target
        while current is not None:
            path.append(current)
            current = previous[current]
        path.reverse()
        return {"found": True, "source": source, "target": target, "path": path, "hops": len(path) - 1}

    def impact_analysis(self, path: str, max_items: int = 100) -> dict[str, Any]:
        component = self.get_component(path)
        impact = dict(component.get("impact") or {})
        impact["component"] = path
        impact["metrics"] = component.get("metrics", {})
        impact["cochange_neighbors"] = (component.get("history") or {}).get("cochange_neighbors", [])[: max(1, min(max_items, 500))]
        impact["transitive_dependents"] = impact.get("transitive_dependents", [])[: max(1, min(max_items, 500))]
        return impact

    def list_symbols(self, *, query: str = "", kind: str = "", language: str = "", component: str = "", limit: int = 100) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        values = []
        for symbol in self.symbols.values():
            haystack = " ".join(str(symbol.get(key, "")) for key in ("qualified_name", "name", "path", "signature", "kind")).lower()
            if needle and needle not in haystack:
                continue
            if kind and symbol.get("kind") != kind:
                continue
            if language and symbol.get("language") != language:
                continue
            if component and symbol.get("component") != component:
                continue
            values.append(symbol)
        values.sort(key=lambda item: (-int(item.get("complexity", 0)), str(item.get("qualified_name", ""))))
        return values[: max(1, min(limit, 1000))]

    def get_symbol(self, qualified_name: str) -> dict[str, Any]:
        if qualified_name not in self.symbols:
            raise ValueError(f"Unknown symbol: {qualified_name}")
        relationships = [
            relationship for relationship in self.report.get("symbol_relationships", [])
            if relationship.get("source") == qualified_name or relationship.get("target") == qualified_name
        ]
        return {**self.symbols[qualified_name], "relationships": relationships}

    def list_findings(self, *, severity: str = "", rule_id: str = "", component: str = "", limit: int = 100) -> list[dict[str, Any]]:
        values = []
        for finding in self.report.get("findings", []):
            if severity and finding.get("severity") != severity:
                continue
            if rule_id and rule_id.lower() not in str(finding.get("rule_id", "")).lower():
                continue
            if component and finding.get("component") != component:
                continue
            values.append(finding)
        return values[: max(1, min(limit, 1000))]

    def hotspots(self, limit: int = 50) -> list[dict[str, Any]]:
        values = []
        for component in self.components.values():
            values.append({
                "component": component.get("path"),
                "hotspot_score": (component.get("metrics") or {}).get("hotspot_score", 0.0),
                "complexity": (component.get("metrics") or {}).get("complexity", 0),
                "churn": (component.get("history") or {}).get("churn", 0),
                "risk_tier": (component.get("impact") or {}).get("risk_tier", "unknown"),
            })
        values.sort(key=lambda item: (-float(item["hotspot_score"]), -int(item["complexity"]), str(item["component"])))
        return values[: max(1, min(limit, 500))]

    def cochange(self, component: str = "", limit: int = 50) -> list[dict[str, Any]]:
        values = self.report.get("history", {}).get("cochange", [])
        if component:
            values = [item for item in values if item.get("left") == component or item.get("right") == component]
        return values[: max(1, min(limit, 500))]


    def search(self, query: str, *, kind: str = "all", limit: int = 50) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        if not needle:
            return []
        values: list[dict[str, Any]] = []
        if kind in {"all", "component"}:
            for component in self.components.values():
                haystack = " ".join(str(component.get(key, "")) for key in ("path", "name", "role", "description", "stability")).lower()
                if needle in haystack:
                    values.append({
                        "type": "component",
                        "id": component.get("path"),
                        "path": component.get("path"),
                        "role": component.get("role"),
                        "stability": component.get("stability"),
                        "risk_tier": (component.get("impact") or {}).get("risk_tier"),
                        "hotspot_score": (component.get("metrics") or {}).get("hotspot_score", 0.0),
                    })
        if kind in {"all", "symbol"}:
            for symbol in self.symbols.values():
                haystack = " ".join(str(symbol.get(key, "")) for key in ("qualified_name", "name", "path", "signature", "kind", "language")).lower()
                if needle in haystack:
                    values.append({
                        "type": "symbol",
                        "id": symbol.get("qualified_name"),
                        "qualified_name": symbol.get("qualified_name"),
                        "kind": symbol.get("kind"),
                        "path": symbol.get("path"),
                        "line": symbol.get("line_start"),
                        "component": symbol.get("component"),
                    })
        values.sort(key=lambda item: (0 if item["type"] == "component" else 1, str(item.get("id", ""))))
        return values[: max(1, min(limit, 1000))]

    def search_evidence(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        if not needle:
            return []
        results: list[dict[str, Any]] = []
        for dependency in self.report.get("dependencies", []):
            joined = " ".join(str(item) for item in dependency.get("evidence", [])).lower()
            if needle in joined or needle in str(dependency.get("source", "")).lower() or needle in str(dependency.get("target", "")).lower():
                results.append({"type": "dependency", **dependency})
        for relationship in self.report.get("symbol_relationships", []):
            joined = " ".join(str(item) for item in relationship.get("evidence", [])).lower()
            if needle in joined or needle in str(relationship.get("source", "")).lower() or needle in str(relationship.get("target", "")).lower():
                results.append({"type": "symbol_relationship", **relationship})
        for finding in self.report.get("findings", []):
            joined = " ".join(str(finding.get(key, "")) for key in ("rule_id", "title", "message", "component")).lower()
            if needle in joined:
                results.append({"type": "finding", **finding})
        for component in self.components.values():
            reasons = component.get("classification_reason", [])
            if needle in " ".join(str(item) for item in reasons).lower():
                results.append({"type": "classification", "path": component["path"], "evidence": reasons})
        return results[: max(1, min(limit, 500))]
