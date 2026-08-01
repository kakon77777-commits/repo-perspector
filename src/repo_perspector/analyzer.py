from __future__ import annotations

from pathlib import Path

from .models import ArchitectureReport
from .parser_plugins import ParserRegistry
from .report_builder import build_report
from .source import PreparedSource


def analyze_repository(
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
    """Analyze a repository and return the evidence-first architecture report."""
    return build_report(
        source,
        max_files=max_files,
        max_parse_bytes=max_parse_bytes,
        history_commits=history_commits,
        policy_path=policy_path,
        cache_dir=cache_dir,
        use_cache=use_cache,
        workers=workers,
        skip_generated=skip_generated,
        max_analysis_seconds=max_analysis_seconds,
        load_parser_plugins=load_parser_plugins,
        parser_registry=parser_registry,
        rule_packs=rule_packs,
    )
