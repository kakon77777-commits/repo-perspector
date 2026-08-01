from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .models import Component, FileRecord, Finding


def calculate_health(
    *,
    components: Iterable[Component],
    findings: Iterable[Finding],
    cycles: list[list[str]],
    records: Iterable[FileRecord],
    partial: bool = False,
) -> dict[str, Any]:
    """Return an explainable governance score, not a failure probability."""
    component_list = list(components)
    finding_list = list(findings)
    record_list = list(records)
    severities = Counter(item.severity for item in finding_list)
    risks = Counter(str(item.impact.get("risk_tier", "unknown")) for item in component_list)
    hotspots = sum(1 for item in component_list if float(item.metrics.get("hotspot_score", 0.0)) >= 0.72)
    parse_warnings = sum(1 for item in record_list if item.parse_error and item.parse_error != "generated file skipped")
    parse_ratio = parse_warnings / max(1, len(record_list))

    penalties = {
        "errors": min(35.0, severities["error"] * 10.0),
        "warnings": min(20.0, severities["warning"] * 3.0),
        "notes": min(5.0, severities["note"] * 0.5),
        "cycles": min(20.0, len(cycles) * 8.0),
        "critical_risk": min(25.0, risks["critical"] * 8.0),
        "high_risk": min(20.0, risks["high"] * 2.0),
        "hotspots": min(10.0, hotspots * 1.0),
        "partial_report": 15.0 if partial else 0.0,
        "parse_coverage": min(10.0, parse_ratio * 50.0),
    }
    score = round(max(0.0, 100.0 - sum(penalties.values())), 2)
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "E"
    status = "healthy" if score >= 90 else "watch" if score >= 75 else "at_risk" if score >= 50 else "critical"
    return {
        "model": "repo-perspector.health/v0.6",
        "score": score,
        "grade": grade,
        "status": status,
        "interpretation": "Heuristic architecture-governance score; not a reliability or defect probability.",
        "penalties": {key: round(value, 2) for key, value in penalties.items()},
        "signals": {
            "findings": dict(severities),
            "risk_tiers": dict(risks),
            "cycles": len(cycles),
            "hotspots": hotspots,
            "parse_warnings": parse_warnings,
            "partial": partial,
        },
    }
