from __future__ import annotations

from pathlib import Path
from typing import Any

from .heuristics import infer_architecture_pattern
from .models import Component, Dependency, FileRecord, Finding, SymbolRecord
from .health import calculate_health
from .policy import discover_policy, evaluate_policy, load_policy
from .quality import apply_quality_metrics, detect_findings, finding_summary
from .rule_packs import apply_rule_configuration, merge_rule_packs


def finalize_quality_and_policy(
    root: Path,
    *,
    components: list[Component],
    dependencies: list[Dependency],
    cycles: list[list[str]],
    records: list[FileRecord],
    symbols: list[SymbolRecord],
    cochange: list[dict[str, Any]],
    config_files: list[str],
    policy_path: str | Path | None,
    rule_packs: list[str] | tuple[str, ...] = (),
    partial: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], list[Finding], dict[str, Any], list[str]]:
    quality = apply_quality_metrics(components, records, symbols)
    built_in_findings = detect_findings(components, dependencies, cycles, cochange)

    selected_policy = discover_policy(root, policy_path)
    policy_payload, policy_warnings = load_policy(selected_policy)
    policy_payload, selected_packs = merge_rule_packs(policy_payload, rule_packs)
    policy_summary, policy_findings = evaluate_policy(
        policy_payload,
        components,
        dependencies,
        source_path=selected_policy,
    )
    findings, rule_configuration = apply_rule_configuration([*policy_findings, *built_in_findings], policy_payload)
    policy_summary["rule_packs"] = selected_packs
    policy_summary["rule_configuration"] = rule_configuration
    findings.sort(
        key=lambda finding: (
            {"error": 0, "warning": 1, "note": 2}.get(finding.severity, 3),
            finding.rule_id,
            finding.component or "",
        )
    )
    quality["finding_summary"] = finding_summary(findings)
    quality["health"] = calculate_health(
        components=components, findings=findings, cycles=cycles, records=records, partial=partial
    )
    pattern = infer_architecture_pattern([component.path for component in components], config_files)
    return quality, policy_summary, findings, pattern, policy_warnings
