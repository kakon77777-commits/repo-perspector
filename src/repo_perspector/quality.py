from __future__ import annotations

from collections import Counter
from typing import Iterable

from .models import Component, Dependency, FileRecord, Finding, SymbolRecord


_SEVERITY_ORDER = {"error": 3, "warning": 2, "note": 1}
_STABILITY_RANK = {"core": 0, "stable": 1, "evolving": 2, "experimental": 3}


def apply_quality_metrics(
    components: list[Component],
    files: Iterable[FileRecord],
    symbols: Iterable[SymbolRecord],
) -> dict[str, object]:
    file_by_component: dict[str, list[FileRecord]] = {}
    for record in files:
        file_by_component.setdefault(record.component, []).append(record)
    symbol_by_component: dict[str, list[SymbolRecord]] = {}
    for symbol in symbols:
        symbol_by_component.setdefault(symbol.component, []).append(symbol)

    raw_complexity: dict[str, int] = {}
    for component in components:
        complexity = sum(record.complexity for record in file_by_component.get(component.path, []))
        raw_complexity[component.path] = complexity
    max_complexity = max(raw_complexity.values(), default=1)

    for component in components:
        ca = len(component.dependents)
        ce = len(component.internal_dependencies)
        total = ca + ce
        instability = ce / total if total else 0.0
        component_symbols = symbol_by_component.get(component.path, [])
        complexity = raw_complexity.get(component.path, 0)
        normalized_complexity = complexity / max(1, max_complexity)
        normalized_churn = float(component.history.get("normalized_churn", 0.0) or 0.0)
        hotspot = min(1.0, 0.6 * normalized_complexity + 0.4 * normalized_churn)
        component.metrics = {
            "afferent_coupling": ca,
            "efferent_coupling": ce,
            "instability": round(instability, 4),
            "file_count": len(file_by_component.get(component.path, [])),
            "symbol_count": len(component_symbols),
            "complexity": complexity,
            "normalized_complexity": round(normalized_complexity, 4),
            "average_symbol_complexity": round(
                sum(symbol.complexity for symbol in component_symbols) / max(1, len(component_symbols)), 4
            ),
            "hotspot_score": round(hotspot, 4),
        }

    hotspot_components = sorted(
        (
            {
                "component": component.path,
                "hotspot_score": component.metrics["hotspot_score"],
                "complexity": component.metrics["complexity"],
                "churn": component.history.get("churn", 0),
                "risk_tier": component.impact.get("risk_tier", "unknown"),
            }
            for component in components
        ),
        key=lambda item: (-float(item["hotspot_score"]), -int(item["complexity"]), str(item["component"])),
    )[:50]
    return {
        "metric_model": "repo-perspector.quality/v0.4",
        "component_count": len(components),
        "total_symbols": sum(len(value) for value in symbol_by_component.values()),
        "total_complexity": sum(raw_complexity.values()),
        "hotspots": hotspot_components,
    }


def detect_findings(
    components: list[Component],
    dependencies: list[Dependency],
    cycles: list[list[str]],
    cochange_pairs: list[dict[str, object]],
) -> list[Finding]:
    findings: list[Finding] = []
    by_name = {component.path: component for component in components}

    for cycle in cycles:
        representative = by_name.get(cycle[0]) if cycle else None
        findings.append(Finding(
            rule_id="architecture.cycle",
            severity="error",
            title="跨模組循環依賴",
            message="偵測到跨模組循環：" + " → ".join(cycle),
            component=cycle[0] if cycle else None,
            path=representative.files[0] if representative and representative.files else None,
            evidence=[" → ".join(cycle)],
            properties={"cycle": cycle, "size": len(cycle)},
        ))

    for dependency in dependencies:
        source = by_name.get(dependency.source)
        target = by_name.get(dependency.target)
        if not source or not target:
            continue
        source_rank = _STABILITY_RANK.get(source.stability, 1)
        target_rank = _STABILITY_RANK.get(target.stability, 1)
        if target_rank - source_rank >= 2:
            severity = "error" if source.stability == "core" and target.stability == "experimental" else "warning"
            findings.append(Finding(
                rule_id="architecture.unstable_dependency",
                severity=severity,
                title="穩定模組依賴較不穩定模組",
                message=f"{source.path}（{source.stability}）依賴 {target.path}（{target.stability}）。",
                component=source.path,
                path=(dependency.evidence[0].split(":", 1)[0] if dependency.evidence else (source.files[0] if source.files else None)),
                evidence=dependency.evidence,
                properties={"source": source.path, "target": target.path},
            ))

    for component in components:
        metrics = component.metrics or {}
        ce = int(metrics.get("efferent_coupling", 0))
        symbol_count = int(metrics.get("symbol_count", 0))
        file_count = int(metrics.get("file_count", 0))
        hotspot = float(metrics.get("hotspot_score", 0.0))
        governance_exempt = component.role in {"tests", "documentation", "examples"} or (component.role == "orchestration" and int(metrics.get("complexity", 0)) < 30)
        if ce >= 8 and not governance_exempt:
            findings.append(Finding(
                rule_id="architecture.high_fanout",
                severity="warning",
                title="模組出向耦合過高",
                message=f"{component.path} 直接依賴 {ce} 個模組，修改與測試範圍可能過寬。",
                component=component.path,
                path=component.files[0] if component.files else None,
                properties={"efferent_coupling": ce},
            ))
        if component.centrality >= 0.75 and (symbol_count >= 25 or file_count >= 10) and not governance_exempt:
            findings.append(Finding(
                rule_id="architecture.god_component",
                severity="warning",
                title="疑似巨型中心模組",
                message=f"{component.path} 同時具有高中心性與大量內容。",
                component=component.path,
                path=component.files[0] if component.files else None,
                properties={"centrality": component.centrality, "symbols": symbol_count, "files": file_count},
            ))
        if hotspot >= 0.72 and component.impact.get("risk_tier") in {"high", "critical"}:
            findings.append(Finding(
                rule_id="architecture.temporal_hotspot",
                severity="warning",
                title="高風險演化熱點",
                message=f"{component.path} 同時具有高複雜度、變更 churn 與影響風險。",
                component=component.path,
                path=component.files[0] if component.files else None,
                properties={"hotspot_score": hotspot, "risk_tier": component.impact.get("risk_tier")},
            ))

    static_pairs = {(dep.source, dep.target) for dep in dependencies} | {(dep.target, dep.source) for dep in dependencies}
    for pair in cochange_pairs:
        left = str(pair.get("left", ""))
        right = str(pair.get("right", ""))
        joint = int(pair.get("joint_commits", 0) or 0)
        confidence = float(pair.get("confidence", 0.0) or 0.0)
        if joint >= 3 and confidence >= 0.6 and (left, right) not in static_pairs:
            component = by_name.get(left)
            findings.append(Finding(
                rule_id="architecture.hidden_change_coupling",
                severity="note",
                title="隱藏的共同變更耦合",
                message=f"{left} 與 {right} 經常共同變更，但未發現直接靜態依賴。",
                component=left,
                path=component.files[0] if component and component.files else None,
                properties={"left": left, "right": right, "joint_commits": joint, "confidence": confidence},
            ))

    findings.sort(key=lambda item: (-_SEVERITY_ORDER.get(item.severity, 0), item.rule_id, item.component or ""))
    return findings


def finding_summary(findings: Iterable[Finding]) -> dict[str, int]:
    counts = Counter(finding.severity for finding in findings)
    return {"error": counts["error"], "warning": counts["warning"], "note": counts["note"], "total": sum(counts.values())}
