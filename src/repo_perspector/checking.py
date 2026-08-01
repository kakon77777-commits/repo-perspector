from __future__ import annotations

from collections import Counter
from typing import Any

from .baseline import compare_baseline

_SEVERITY = {"none": 99, "error": 3, "warning": 2, "note": 1}


def check_report(
    report: dict[str, Any],
    *,
    fail_on: str = "error",
    max_cycles: int | None = None,
    max_critical: int | None = None,
    max_high: int | None = None,
    max_findings: int | None = None,
    max_hotspots: int | None = None,
    min_health: float | None = None,
    max_health_drop: float | None = None,
    baseline: dict[str, Any] | None = None,
    new_only: bool = False,
    fail_on_risk_regression: bool = False,
    fail_on_new_cycle: bool = False,
) -> dict[str, Any]:
    policy_thresholds = ((report.get("policy") or {}).get("thresholds") or {})
    max_cycles = policy_thresholds.get("max_cycles") if max_cycles is None else max_cycles
    max_critical = policy_thresholds.get("max_critical_components") if max_critical is None else max_critical
    max_high = policy_thresholds.get("max_high_components") if max_high is None else max_high
    max_findings = policy_thresholds.get("max_findings") if max_findings is None else max_findings
    max_hotspots = policy_thresholds.get("max_hotspots") if max_hotspots is None else max_hotspots
    min_health = policy_thresholds.get("min_health") if min_health is None else min_health
    max_health_drop = policy_thresholds.get("max_health_drop") if max_health_drop is None else max_health_drop

    baseline_comparison = compare_baseline(baseline, report) if baseline is not None else None
    all_findings = [item for item in report.get("findings", []) if isinstance(item, dict)]
    findings = (
        list(baseline_comparison.get("new_findings", []))
        if new_only and baseline_comparison is not None
        else all_findings
    )
    severity_counts = Counter(str(item.get("severity", "note")) for item in findings)
    total_severity_counts = Counter(str(item.get("severity", "note")) for item in all_findings)
    risk_counts = Counter(
        str((component.get("impact") or {}).get("risk_tier", "unknown"))
        for component in report.get("components", [])
    )
    hotspot_count = sum(
        1
        for component in report.get("components", [])
        if float((component.get("metrics") or {}).get("hotspot_score", 0.0)) >= 0.72
    )
    checks: list[dict[str, Any]] = []

    def add(name: str, actual: int, maximum: int | None) -> None:
        if maximum is None:
            return
        checks.append({
            "name": name,
            "actual": actual,
            "maximum": int(maximum),
            "passed": actual <= int(maximum),
        })

    add("cycles", len(report.get("cycles", [])), max_cycles)
    add("critical_components", risk_counts["critical"], max_critical)
    add("high_components", risk_counts["high"], max_high)
    add("findings", len(findings), max_findings)
    add("hotspots", hotspot_count, max_hotspots)

    severity_failed = False
    if fail_on != "none":
        threshold = _SEVERITY.get(fail_on, 3)
        severity_failed = any(
            _SEVERITY.get(str(item.get("severity", "note")), 1) >= threshold
            for item in findings
        )

    risk_regression_failed = bool(
        fail_on_risk_regression
        and baseline_comparison
        and baseline_comparison.get("risk_regressions")
    )
    new_cycle_failed = bool(
        fail_on_new_cycle
        and baseline_comparison
        and baseline_comparison.get("new_cycles")
    )
    health_score = float((((report.get("quality") or {}).get("health") or {}).get("score", 0.0)))
    baseline_health = float(((((baseline or {}).get("quality") or {}).get("health") or {}).get("score", health_score)))
    health_drop = round(baseline_health - health_score, 2) if baseline is not None else 0.0
    health_failed = min_health is not None and health_score < float(min_health)
    health_drop_failed = max_health_drop is not None and baseline is not None and health_drop > float(max_health_drop)
    passed = (
        not severity_failed
        and not risk_regression_failed
        and not new_cycle_failed
        and not health_failed
        and not health_drop_failed
        and all(item["passed"] for item in checks)
    )
    return {
        "passed": passed,
        "scope": "new_findings" if new_only and baseline_comparison is not None else "all_findings",
        "fail_on": fail_on,
        "severity_counts": dict(severity_counts),
        "total_severity_counts": dict(total_severity_counts),
        "risk_counts": dict(risk_counts),
        "hotspot_count": hotspot_count,
        "checks": checks,
        "failed_by_severity": severity_failed,
        "failed_by_risk_regression": risk_regression_failed,
        "failed_by_new_cycle": new_cycle_failed,
        "health_score": health_score,
        "minimum_health": min_health,
        "health_drop": health_drop,
        "maximum_health_drop": max_health_drop,
        "failed_by_health": health_failed,
        "failed_by_health_drop": health_drop_failed,
        "baseline": baseline_comparison,
    }
