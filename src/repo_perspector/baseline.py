from __future__ import annotations

from typing import Any

_RISK = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def finding_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(item.get("rule_id", "")),
        str(item.get("component") or ""),
        str(item.get("path") or ""),
        str(item.get("title") or ""),
    )


def compare_baseline(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    baseline_findings = {
        finding_key(item): item
        for item in baseline.get("findings", [])
        if isinstance(item, dict)
    }
    current_findings = {
        finding_key(item): item
        for item in current.get("findings", [])
        if isinstance(item, dict)
    }
    new_keys = sorted(set(current_findings) - set(baseline_findings))
    resolved_keys = sorted(set(baseline_findings) - set(current_findings))

    before_components = {
        str(item.get("path")): item
        for item in baseline.get("components", [])
        if isinstance(item, dict) and item.get("path")
    }
    after_components = {
        str(item.get("path")): item
        for item in current.get("components", [])
        if isinstance(item, dict) and item.get("path")
    }
    risk_regressions: list[dict[str, Any]] = []
    risk_improvements: list[dict[str, Any]] = []
    for path in sorted(set(before_components) & set(after_components)):
        before = str((before_components[path].get("impact") or {}).get("risk_tier", "unknown"))
        after = str((after_components[path].get("impact") or {}).get("risk_tier", "unknown"))
        if _RISK.get(after, 0) > _RISK.get(before, 0):
            risk_regressions.append({"component": path, "before": before, "after": after})
        elif _RISK.get(after, 0) < _RISK.get(before, 0):
            risk_improvements.append({"component": path, "before": before, "after": after})

    baseline_cycles = {tuple(sorted(group)) for group in baseline.get("cycles", []) if isinstance(group, list)}
    current_cycles = {tuple(sorted(group)) for group in current.get("cycles", []) if isinstance(group, list)}
    new_cycles = [list(group) for group in sorted(current_cycles - baseline_cycles)]
    resolved_cycles = [list(group) for group in sorted(baseline_cycles - current_cycles)]

    baseline_health = float(((baseline.get("quality") or {}).get("health") or {}).get("score", 0.0))
    current_health = float(((current.get("quality") or {}).get("health") or {}).get("score", 0.0))
    return {
        "schema_version": "repo-perspector.baseline/v0.6",
        "summary": {
            "new_findings": len(new_keys),
            "resolved_findings": len(resolved_keys),
            "risk_regressions": len(risk_regressions),
            "risk_improvements": len(risk_improvements),
            "new_cycles": len(new_cycles),
            "resolved_cycles": len(resolved_cycles),
            "health_before": baseline_health,
            "health_after": current_health,
            "health_change": round(current_health - baseline_health, 2),
        },
        "new_findings": [current_findings[key] for key in new_keys],
        "resolved_findings": [baseline_findings[key] for key in resolved_keys],
        "risk_regressions": risk_regressions,
        "risk_improvements": risk_improvements,
        "new_cycles": new_cycles,
        "resolved_cycles": resolved_cycles,
    }
