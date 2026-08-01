from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from .query import ReportIndex


def build_server(report_path: str | Path) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError('MCP support requires: pip install -e ".[mcp]"') from exc

    index = ReportIndex.from_path(report_path)
    mcp = FastMCP("Repository Architecture Perspector")

    @mcp.tool()
    def project_overview() -> dict[str, Any]:
        """Return project, architecture, quality, policy, history, cycles, and warnings."""
        return index.overview()

    @mcp.tool()
    def list_workspaces(query: str = "", ecosystem: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """List detected monorepo/workspace package boundaries and their files/components."""
        return index.list_workspaces(query=query, ecosystem=ecosystem, limit=limit)

    @mcp.tool()
    def list_components(query: str = "", stability: str = "", role: str = "", risk_tier: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """List components filtered by text, stability, role, or impact-risk tier."""
        return index.list_components(query=query, stability=stability, role=role, risk_tier=risk_tier, limit=limit)

    @mcp.tool()
    def get_component(path: str) -> dict[str, Any]:
        """Return one component with dependencies, symbols, churn, quality, and impact metrics."""
        return index.get_component(path)

    @mcp.tool()
    def find_dependency_path(source: str, target: str) -> dict[str, Any]:
        """Find a shortest directed static-dependency path."""
        return index.dependency_path(source, target)

    @mcp.tool()
    def analyze_change_impact(path: str, max_items: int = 100) -> dict[str, Any]:
        """Return blast radius, risk, quality metrics, and Git co-change neighbors."""
        return index.impact_analysis(path, max_items=max_items)

    @mcp.tool()
    def list_symbols(query: str = "", kind: str = "", language: str = "", component: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """Search indexed classes, functions, methods, interfaces, types, and other declarations."""
        return index.list_symbols(query=query, kind=kind, language=language, component=component, limit=limit)

    @mcp.tool()
    def get_symbol(qualified_name: str) -> dict[str, Any]:
        """Return one symbol and its resolved call relationships."""
        return index.get_symbol(qualified_name)

    @mcp.tool()
    def list_architecture_findings(severity: str = "", rule_id: str = "", component: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """List built-in and policy architecture findings."""
        return index.list_findings(severity=severity, rule_id=rule_id, component=component, limit=limit)

    @mcp.tool()
    def list_hotspots(limit: int = 50) -> list[dict[str, Any]]:
        """List components ranked by complexity-plus-churn temporal hotspot score."""
        return index.hotspots(limit=limit)

    @mcp.tool()
    def list_cochange_coupling(component: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """List components that frequently change together in Git history."""
        return index.cochange(component=component, limit=limit)

    @mcp.tool()
    def search_architecture_evidence(query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Search import evidence, symbol calls, findings, and classification reasons."""
        return index.search_evidence(query, limit=limit)

    @mcp.resource("perspector://architecture")
    def architecture_resource() -> str:
        return json.dumps(index.report, ensure_ascii=False, indent=2)

    @mcp.resource("perspector://workspaces")
    def workspaces_resource() -> str:
        return json.dumps(index.report.get("workspaces", []), ensure_ascii=False, indent=2)

    @mcp.resource("perspector://findings")
    def findings_resource() -> str:
        return json.dumps(index.report.get("findings", []), ensure_ascii=False, indent=2)

    @mcp.resource("perspector://symbols")
    def symbols_resource() -> str:
        return json.dumps(index.report.get("symbols", []), ensure_ascii=False, indent=2)

    return mcp


def run_server(report_path: str | Path, transport: str = "stdio") -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    build_server(report_path).run(transport=transport)
