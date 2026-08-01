from __future__ import annotations

from pathlib import Path

from .analyzer import analyze_repository
from .renderers import write_outputs
from .source import prepare_source
from .state import record_snapshot


def run_analyze(args) -> int:
    prepared = prepare_source(args.source, clone_depth=max(1, args.clone_depth))
    try:
        report = analyze_repository(
            prepared,
            max_files=max(1, args.max_files),
            max_parse_bytes=max(1024, args.max_parse_bytes),
            history_commits=max(0, args.history_commits),
            policy_path=args.policy,
            cache_dir=args.cache_dir,
            use_cache=not args.no_cache,
            workers=max(0, args.workers),
            skip_generated=bool(args.skip_generated),
            max_analysis_seconds=max(0.0, args.max_analysis_seconds),
            load_parser_plugins=not args.no_parser_plugins,
            rule_packs=list(args.rule_pack or []),
        )
        outputs = write_outputs(report, Path(args.output).expanduser().resolve())
        snapshot = None
        if args.record:
            if not args.state_dir:
                raise ValueError("--record requires --state-dir")
            snapshot = record_snapshot(
                report.to_dict(), args.state_dir, label=args.label, retention=max(1, args.retention)
            )

        cache = report.analysis.get("cache", {})
        health = report.quality.get("health", {})
        print(f"Analyzed: {report.project['name']}")
        print(
            f"Files: {report.project['file_count']} | Components: {report.project['component_count']} | "
            f"Dependencies: {report.project['dependency_count']} | Symbols: {report.project['symbol_count']}"
        )
        print(
            f"Findings: {report.project['finding_count']} | "
            f"Git commits: {report.history.get('repository', {}).get('commit_count_analyzed', 0)}"
        )
        print(
            f"Incremental cache: {cache.get('hits', 0)} hit / {cache.get('misses', 0)} miss "
            f"({float(cache.get('hit_rate', 0.0)):.1%})"
        )
        print(f"Architecture candidate: {report.architecture['pattern']['primary']}")
        print(
            f"Architecture health: {float(health.get('score', 0.0)):.2f} "
            f"({health.get('grade', '?')} / {health.get('status', 'unknown')})"
        )
        print(
            f"Workspaces: {report.project.get('workspace_count', 1)} | "
            f"Workers: {report.analysis.get('concurrency', {}).get('workers', 1)} | "
            f"Partial: {report.analysis.get('partial', False)}"
        )
        for name, path in outputs.items():
            print(f"{name:10}: {path}")
        if snapshot is not None:
            action = "Recorded" if snapshot.get("recorded") else "Skipped duplicate"
            print(f"State: {action} -> {snapshot.get('state_dir')}")
        return 0
    finally:
        prepared.cleanup()
