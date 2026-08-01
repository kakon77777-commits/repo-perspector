from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, perf_counter

from .cache import AnalysisCache, default_cache_dir
from .finalization import finalize_quality_and_policy
from .graph_builder import build_dependency_graph
from .history import collect_git_history
from .inventory import build_inventory
from .models import ArchitectureReport
from .parser_plugins import ParserRegistry
from .source import PreparedSource


def build_report(
    source: PreparedSource,
    *,
    max_files: int = 10000,
    max_parse_bytes: int = 1_000_000,
    history_commits: int = 300,
    policy_path: str | Path | None = None,
    cache_dir: str | Path | None = None,
    use_cache: bool = True,
    workers: int = 0,
    skip_generated: bool = False,
    max_analysis_seconds: float = 0.0,
    load_parser_plugins: bool = True,
    parser_registry: ParserRegistry | None = None,
    rule_packs: list[str] | tuple[str, ...] = (),
) -> ArchitectureReport:
    started = perf_counter()
    root = source.path.resolve()
    deadline = monotonic() + max_analysis_seconds if max_analysis_seconds > 0 else None
    resolved_cache_dir = (
        Path(cache_dir).expanduser().resolve()
        if cache_dir is not None
        else default_cache_dir(root, source.source_type, source.origin_url)
    )
    cache = AnalysisCache(resolved_cache_dir, enabled=use_cache)
    registry = parser_registry or ParserRegistry(load_plugins=load_parser_plugins)

    inventory_started = perf_counter()
    inventory = build_inventory(
        root,
        max_files=max_files,
        max_parse_bytes=max_parse_bytes,
        cache=cache,
        registry=registry,
        workers=workers,
        skip_generated=skip_generated,
        deadline=deadline,
    )
    inventory_seconds = perf_counter() - inventory_started

    history_started = perf_counter()
    if inventory.time_budget_exceeded or (deadline is not None and monotonic() >= deadline):
        git_history = {"available": False, "reason": "analysis time budget exceeded", "repository": {}, "components": {}, "files": {}, "cochange": []}
    else:
        git_history = collect_git_history(
            root,
            inventory.file_component,
            max_commits=history_commits,
        )
    history_seconds = perf_counter() - history_started
    component_history = git_history.get("components", {}) if git_history.get("available") else {}

    graph_started = perf_counter()
    dependencies, components, cycles, symbol_relationships = build_dependency_graph(
        root,
        inventory,
        component_history,
    )
    graph_seconds = perf_counter() - graph_started

    partial = bool(inventory.skipped_limit or inventory.time_budget_exceeded)
    finalization_started = perf_counter()
    quality, policy_summary, findings, architecture_pattern, policy_warnings = finalize_quality_and_policy(
        root,
        components=components,
        dependencies=dependencies,
        cycles=cycles,
        records=inventory.records,
        symbols=inventory.symbols,
        cochange=list(git_history.get("cochange", [])),
        config_files=inventory.config_files,
        policy_path=policy_path,
        rule_packs=rule_packs,
        partial=partial,
    )
    finalization_seconds = perf_counter() - finalization_started

    warnings = [*inventory.warnings, *policy_warnings]
    parse_errors = [record for record in inventory.records if record.parse_error and record.parse_error != "generated file skipped"]
    if inventory.skipped_limit:
        warnings.append(f"File scan stopped at max_files={max_files}; report is partial.")
    if inventory.time_budget_exceeded:
        warnings.append(f"Analysis stopped at max_analysis_seconds={max_analysis_seconds}; report is partial.")
    if inventory.skipped_large:
        warnings.append(f"Skipped parsing {inventory.skipped_large} oversized code files.")
    if inventory.skipped_generated:
        warnings.append(f"Skipped parsing {inventory.skipped_generated} generated code files.")
    if parse_errors:
        warnings.append(f"{len(parse_errors)} files had parse/read warnings; see evidence.parse_warnings.")
    if not dependencies:
        warnings.append("No internal dependencies were resolved; this may be a data-only repo or require deeper language parsing.")
    if not git_history.get("available"):
        warnings.append(f"Git history unavailable: {git_history.get('reason', 'unknown reason')}.")
    elif git_history.get("repository", {}).get("commit_count_analyzed", 0) <= 1:
        warnings.append("Git history contains one or fewer analyzed commits; churn/co-change evidence is weak.")

    language_counts = Counter(record.language for record in inventory.records)
    total_seconds = perf_counter() - started
    analysis = {
        "engine_version": "0.6.0",
        "cache": inventory.cache,
        "partial": partial,
        "concurrency": {"workers": inventory.workers},
        "ignore": inventory.ignore,
        "parser_registry": inventory.parser_registry,
        "parser_coverage": inventory.parser_coverage,
        "timing_seconds": {
            "inventory": round(inventory_seconds, 6),
            "history": round(history_seconds, 6),
            "graph": round(graph_seconds, 6),
            "finalization": round(finalization_seconds, 6),
            "total": round(total_seconds, 6),
        },
        "incremental": {
            "reused_files": int(inventory.cache.get("hits", 0)),
            "parsed_files": int(inventory.cache.get("misses", 0)),
            "cache_hit_rate": float(inventory.cache.get("hit_rate", 0.0)),
        },
    }

    workspace_payload = [asdict(workspace) for workspace in inventory.workspaces]
    return ArchitectureReport(
        schema_version="repo-perspector.ir/v0.6",
        generated_at=datetime.now(timezone.utc).isoformat(),
        project={
            "name": source.display_name,
            "root": str(root),
            "source_type": source.source_type,
            "origin_url": source.origin_url,
            "branch": source.branch,
            "commit": source.commit,
            "file_count": len(inventory.records),
            "component_count": len(components),
            "dependency_count": len(dependencies),
            "symbol_count": len(inventory.symbols),
            "symbol_relationship_count": len(symbol_relationships),
            "finding_count": len(findings),
            "workspace_count": len(workspace_payload),
            "monorepo": len(workspace_payload) > 1,
            "partial": partial,
            "total_bytes": sum(record.size for record in inventory.records),
            "languages": dict(sorted(language_counts.items(), key=lambda item: (-item[1], item[0]))),
            "git_history_available": bool(git_history.get("available")),
        },
        analysis=analysis,
        evidence={
            "config_files": inventory.config_files,
            "source_roots": [
                str(path.relative_to(root)) if path != root else "."
                for path in inventory.source_roots
            ],
            "parse_warnings": [
                {"path": record.path, "warning": record.parse_error}
                for record in parse_errors[:200]
            ],
            "analysis_limits": {
                "max_files": max_files,
                "max_parse_bytes": max_parse_bytes,
                "history_commits": history_commits,
                "max_analysis_seconds": max_analysis_seconds,
                "skip_generated": skip_generated,
            },
            "file_history": git_history.get("files", {}),
            "symbol_parser": {
                "python": "stdlib AST",
                "other_languages": "declaration-aware structural regex fallback or parser plugin",
            },
        },
        history={
            "available": bool(git_history.get("available")),
            "reason": git_history.get("reason"),
            "repository": git_history.get("repository", {}),
            "cochange": git_history.get("cochange", []),
        },
        architecture={
            "pattern": architecture_pattern,
            "classification_legend": {
                "core": "高中心性或核心路徑證據；移除可能破壞主要系統",
                "stable": "一般穩定模組；目前無實驗性證據",
                "evolving": "插件、整合、範例等可選或演化區域",
                "experimental": "實驗、alpha、beta、prototype 等明確路徑證據",
            },
        },
        quality=quality,
        policy=policy_summary,
        files=inventory.records,
        components=sorted(
            components,
            key=lambda component: (
                -float(component.impact.get("risk_score", 0.0)),
                -float(component.metrics.get("hotspot_score", 0.0)),
                -component.centrality,
                component.path,
            ),
        ),
        dependencies=dependencies,
        symbols=sorted(
            inventory.symbols,
            key=lambda symbol: (symbol.path, symbol.line_start, symbol.qualified_name),
        ),
        symbol_relationships=symbol_relationships,
        findings=findings,
        cycles=cycles,
        workspaces=workspace_payload,
        warnings=warnings,
    )
