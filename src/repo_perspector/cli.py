from __future__ import annotations

import argparse
import sys

from .command_analysis import run_analyze
from .command_query import run_mcp, run_query
from .command_reports import run_change_impact, run_check, run_diff, run_record, run_trend
from .rule_packs import available_rule_packs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-perspector",
        description="Evidence-first repository architecture intelligence",
    )
    parser.add_argument("--version", action="version", version="repo-perspector 0.6.0")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze a local folder or GitHub repository")
    analyze.add_argument("source", help="Local path, GitHub URL, or owner/repo")
    analyze.add_argument("-o", "--output", default="architecture-report", help="Output directory")
    analyze.add_argument("--max-files", type=int, default=10000)
    analyze.add_argument("--max-parse-bytes", type=int, default=1_000_000)
    analyze.add_argument("--history-commits", type=int, default=300, help="Maximum Git commits to analyze; 0 disables history")
    analyze.add_argument("--clone-depth", type=int, default=300, help="GitHub shallow-clone depth")
    analyze.add_argument("--policy", default=None, help="Explicit .perspector.yml/.yaml/.json policy; auto-discovered by default")
    analyze.add_argument("--cache-dir", default=None, help="Persistent incremental-analysis cache directory")
    analyze.add_argument("--no-cache", action="store_true", help="Disable incremental file parse cache")
    analyze.add_argument("--workers", type=int, default=0, help="Parser workers; 0 selects automatically")
    analyze.add_argument("--skip-generated", action="store_true", help="Detect and skip generated code files")
    analyze.add_argument("--max-analysis-seconds", type=float, default=0.0, help="Best-effort analysis time budget; 0 disables")
    analyze.add_argument("--no-parser-plugins", action="store_true", help="Disable external repo_perspector.parsers entry points")
    analyze.add_argument("--rule-pack", action="append", choices=available_rule_packs(), default=[], help="Built-in governance rule pack; repeatable")
    analyze.add_argument("--state-dir", default=None, help="Persistent architecture state directory")
    analyze.add_argument("--record", action="store_true", help="Record the completed report into --state-dir")
    analyze.add_argument("--label", default=None, help="Optional snapshot label when --record is used")
    analyze.add_argument("--retention", type=int, default=100, help="Maximum retained state snapshots")

    diff = sub.add_parser("diff", help="Compare two architecture.json reports or report directories")
    diff.add_argument("old", help="Baseline architecture.json or report directory")
    diff.add_argument("new", help="Current architecture.json or report directory")
    diff.add_argument("-o", "--output", default="architecture-diff", help="Output directory")

    check = sub.add_parser("check", help="CI gate for architecture findings and thresholds")
    check.add_argument("report", help="architecture.json or report directory")
    check.add_argument("--baseline", default=None, help="Baseline architecture report for legacy-debt suppression")
    check.add_argument("--new-only", action="store_true", help="Apply finding thresholds only to findings absent from baseline")
    check.add_argument("--fail-on-risk-regression", action="store_true", help="Fail when any component risk tier increases")
    check.add_argument("--fail-on-new-cycle", action="store_true", help="Fail when a new dependency cycle appears")
    check.add_argument("--fail-on", choices=("error", "warning", "note", "none"), default="error")
    check.add_argument("--max-cycles", type=int)
    check.add_argument("--max-critical", type=int)
    check.add_argument("--max-high", type=int)
    check.add_argument("--max-findings", type=int)
    check.add_argument("--max-hotspots", type=int)
    check.add_argument("--min-health", type=float, help="Minimum architecture health score")
    check.add_argument("--max-health-drop", type=float, help="Maximum allowed health-score drop versus baseline")
    check.add_argument("--format", choices=("text", "json"), default="text")

    change = sub.add_parser("change-impact", help="Map a Git diff to architecture blast radius and review risk")
    change.add_argument("report", help="Current architecture.json or report directory")
    change.add_argument("--repo", required=True, help="Local Git repository containing the refs")
    change.add_argument("--base", required=True, help="Base Git ref, usually origin/main or a baseline commit")
    change.add_argument("--head", default="HEAD", help="Head Git ref; default HEAD")
    change.add_argument("--baseline", default=None, help="Optional baseline architecture report")
    change.add_argument("-o", "--output", default="change-impact", help="Output directory")

    query = sub.add_parser("query", help="Read-only query against an architecture report")
    query.add_argument("report", help="architecture.json or report directory")
    query_sub = query.add_subparsers(dest="query_command", required=True)
    query_sub.add_parser("overview", help="Show project and architecture overview")
    workspace_cmd = query_sub.add_parser("workspaces", help="List monorepo/workspace package boundaries")
    workspace_cmd.add_argument("--search", default="")
    workspace_cmd.add_argument("--ecosystem", default="")
    workspace_cmd.add_argument("--limit", type=int, default=100)
    list_cmd = query_sub.add_parser("components", help="List/filter components")
    list_cmd.add_argument("--search", default="")
    list_cmd.add_argument("--stability", default="")
    list_cmd.add_argument("--role", default="")
    list_cmd.add_argument("--risk-tier", default="")
    list_cmd.add_argument("--limit", type=int, default=50)
    component_cmd = query_sub.add_parser("component", help="Get one component")
    component_cmd.add_argument("path")
    path_cmd = query_sub.add_parser("path", help="Find directed dependency path")
    path_cmd.add_argument("source")
    path_cmd.add_argument("target")
    impact_cmd = query_sub.add_parser("impact", help="Analyze component change impact")
    impact_cmd.add_argument("path")
    evidence_cmd = query_sub.add_parser("evidence", help="Search architecture evidence")
    evidence_cmd.add_argument("search")
    evidence_cmd.add_argument("--limit", type=int, default=50)
    symbols_cmd = query_sub.add_parser("symbols", help="List/search symbols")
    symbols_cmd.add_argument("--search", default="")
    symbols_cmd.add_argument("--kind", default="")
    symbols_cmd.add_argument("--language", default="")
    symbols_cmd.add_argument("--component", default="")
    symbols_cmd.add_argument("--limit", type=int, default=100)
    symbol_cmd = query_sub.add_parser("symbol", help="Get one symbol")
    symbol_cmd.add_argument("qualified_name")
    findings_cmd = query_sub.add_parser("findings", help="List architecture findings")
    findings_cmd.add_argument("--severity", default="")
    findings_cmd.add_argument("--rule", default="")
    findings_cmd.add_argument("--component", default="")
    findings_cmd.add_argument("--limit", type=int, default=100)
    hotspots_cmd = query_sub.add_parser("hotspots", help="List temporal architecture hotspots")
    hotspots_cmd.add_argument("--limit", type=int, default=50)
    cochange_cmd = query_sub.add_parser("cochange", help="List Git co-change coupling")
    cochange_cmd.add_argument("--component", default="")
    cochange_cmd.add_argument("--limit", type=int, default=50)
    search_cmd = query_sub.add_parser("search", help="Search compact architecture index")
    search_cmd.add_argument("search")
    search_cmd.add_argument("--kind", choices=("all", "component", "symbol"), default="all")
    search_cmd.add_argument("--limit", type=int, default=50)

    record = sub.add_parser("record", help="Record an architecture report into persistent state")
    record.add_argument("report", help="architecture.json or report directory")
    record.add_argument("--state-dir", required=True)
    record.add_argument("--label", default=None)
    record.add_argument("--retention", type=int, default=100)

    trend = sub.add_parser("trend", help="Render architecture history from persistent state")
    trend.add_argument("state_dir")
    trend.add_argument("-o", "--output", default="architecture-trend")

    mcp = sub.add_parser("mcp", help="Serve an architecture report over MCP")
    mcp.add_argument("report", help="architecture.json or report directory")
    mcp.add_argument("--transport", choices=("stdio", "streamable-http", "sse"), default="stdio")
    return parser



def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        handlers = {
            "analyze": run_analyze,
            "diff": run_diff,
            "check": run_check,
            "change-impact": run_change_impact,
            "record": run_record,
            "trend": run_trend,
            "query": run_query,
            "mcp": run_mcp,
        }
        handler = handlers.get(args.command)
        return handler(args) if handler is not None else 2
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
