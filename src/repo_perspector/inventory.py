from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .file_parsing import parse_files
from .inventory_mapping import build_mapping
from .inventory_scan import scan_paths
from .models import FileRecord, SymbolRecord
from .workspaces import Workspace, finalize_workspaces


@dataclass(slots=True)
class InventoryResult:
    records: list[FileRecord]
    source_roots: list[Path]
    config_files: list[str]
    warnings: list[str]
    all_paths: list[Path]
    file_component: dict[str, str]
    module_component: dict[str, str]
    module_name_by_file: dict[str, str]
    import_matches_by_file: dict[str, list[Any]]
    symbols: list[SymbolRecord]
    raw_calls: list[Any]
    workspaces: list[Workspace]
    skipped_large: int
    skipped_generated: int
    skipped_limit: bool
    time_budget_exceeded: bool
    cache: dict[str, Any]
    ignore: dict[str, Any]
    parser_registry: dict[str, Any]
    parser_coverage: dict[str, Any]
    workers: int


def build_inventory(
    root: Path,
    *,
    max_files: int,
    max_parse_bytes: int,
    cache,
    registry,
    workers: int = 0,
    skip_generated: bool = False,
    deadline: float | None = None,
) -> InventoryResult:
    root = root.resolve()
    scan = scan_paths(root, max_files=max_files, deadline=deadline)
    mapping = build_mapping(root, scan.paths, registry)
    parsed, resolved_workers, parse_budget_exceeded = parse_files(
        root=root,
        candidates=mapping.parse_candidates,
        file_component=mapping.file_component,
        module_name_by_file=mapping.module_name_by_file,
        registry=registry,
        cache=cache,
        max_parse_bytes=max_parse_bytes,
        skip_generated=skip_generated,
        workers=workers,
        deadline=deadline,
    )

    records: list[FileRecord] = []
    import_matches_by_file: dict[str, list[Any]] = {}
    symbols: list[SymbolRecord] = []
    raw_calls: list[Any] = []
    skipped_large = 0
    skipped_generated_count = 0
    parsed_count = 0
    parse_error_count = 0
    parser_counts: dict[str, int] = {}
    candidate_set = set(mapping.parse_candidates)

    for relative in scan.paths:
        rel_string = relative.as_posix()
        absolute = root / relative
        result = parsed.get(rel_string)
        parser_identity = registry.parser_identity(absolute)
        imports: list[str] = []
        symbol_ids: list[str] = []
        parse_error: str | None = None
        line_count = 0
        complexity = 0
        generated = False
        if result is not None:
            parsed_count += 1
            parser_counts[parser_identity] = parser_counts.get(parser_identity, 0) + 1
            import_matches_by_file[rel_string] = result.imports
            imports = sorted({match.value for match in result.imports})
            symbols.extend(result.symbols)
            raw_calls.extend(result.calls)
            symbol_ids = [symbol.id for symbol in result.symbols]
            line_count = result.line_count
            complexity = result.complexity
            parse_error = result.parse_error
            generated = result.generated
            skipped_large += int(result.skipped_large)
            skipped_generated_count += int(result.skipped_generated)
            parse_error_count += int(bool(parse_error and not result.skipped_generated))
        elif relative in candidate_set:
            parse_error = "analysis time budget exceeded"
            parse_error_count += 1

        records.append(FileRecord(
            path=rel_string,
            language=mapping.file_language[rel_string],
            size=mapping.sizes[rel_string],
            component=mapping.file_component[rel_string],
            line_count=line_count,
            complexity=complexity,
            imports=imports,
            symbols=symbol_ids,
            parse_error=parse_error,
            workspace=mapping.file_workspace[rel_string],
            parser=parser_identity,
            generated=generated,
        ))

    cache.finalize()
    warnings: list[str] = []
    if cache.load_warning:
        warnings.append(cache.load_warning)
    if registry.errors:
        warnings.extend(registry.errors)

    workspaces = finalize_workspaces(
        mapping.workspaces,
        mapping.file_workspace,
        mapping.file_component,
        mapping.file_language,
    )
    code_files = len(mapping.parse_candidates)
    parser_coverage = {
        "code_files": code_files,
        "completed": parsed_count,
        "parse_errors": parse_error_count,
        "skipped_large": skipped_large,
        "skipped_generated": skipped_generated_count,
        "completion_rate": round(parsed_count / code_files, 4) if code_files else 1.0,
        "parsers": dict(sorted(parser_counts.items())),
    }
    return InventoryResult(
        records=records,
        source_roots=mapping.source_roots,
        config_files=mapping.config_files,
        warnings=warnings,
        all_paths=scan.paths,
        file_component=mapping.file_component,
        module_component=mapping.module_component,
        module_name_by_file=mapping.module_name_by_file,
        import_matches_by_file=import_matches_by_file,
        symbols=symbols,
        raw_calls=raw_calls,
        workspaces=workspaces,
        skipped_large=skipped_large,
        skipped_generated=skipped_generated_count,
        skipped_limit=scan.skipped_limit,
        time_budget_exceeded=scan.time_budget_exceeded or parse_budget_exceeded,
        cache=cache.stats(),
        ignore=scan.ignore,
        parser_registry=registry.summary(),
        parser_coverage=parser_coverage,
        workers=resolved_workers,
    )
