from __future__ import annotations

import json

from .query import ReportIndex


def run_query(args) -> int:
    index = ReportIndex.from_path(args.report)
    if args.query_command == "overview":
        result = index.overview()
    elif args.query_command == "workspaces":
        result = index.list_workspaces(query=args.search, ecosystem=args.ecosystem, limit=args.limit)
    elif args.query_command == "components":
        result = index.list_components(
            query=args.search,
            stability=args.stability,
            role=args.role,
            risk_tier=args.risk_tier,
            limit=args.limit,
        )
    elif args.query_command == "component":
        result = index.get_component(args.path)
    elif args.query_command == "path":
        result = index.dependency_path(args.source, args.target)
    elif args.query_command == "impact":
        result = index.impact_analysis(args.path)
    elif args.query_command == "evidence":
        result = index.search_evidence(args.search, limit=args.limit)
    elif args.query_command == "symbols":
        result = index.list_symbols(
            query=args.search,
            kind=args.kind,
            language=args.language,
            component=args.component,
            limit=args.limit,
        )
    elif args.query_command == "symbol":
        result = index.get_symbol(args.qualified_name)
    elif args.query_command == "findings":
        result = index.list_findings(
            severity=args.severity,
            rule_id=args.rule,
            component=args.component,
            limit=args.limit,
        )
    elif args.query_command == "hotspots":
        result = index.hotspots(limit=args.limit)
    elif args.query_command == "cochange":
        result = index.cochange(component=args.component, limit=args.limit)
    elif args.query_command == "search":
        result = index.search(args.search, kind=args.kind, limit=args.limit)
    else:
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_mcp(args) -> int:
    from .mcp_server import run_server

    run_server(args.report, transport=args.transport)
    return 0
