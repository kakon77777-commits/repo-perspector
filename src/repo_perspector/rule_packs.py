from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import Finding

RULE_PACKS: dict[str, dict[str, Any]] = {
    "balanced": {
        "thresholds": {"max_cycles": 0, "max_critical_components": 0, "max_high_components": 10, "max_hotspots": 20},
        "rules": {},
    },
    "strict": {
        "thresholds": {"max_cycles": 0, "max_critical_components": 0, "max_high_components": 3, "max_findings": 10, "max_hotspots": 5},
        "rules": {
            "architecture.high_fanout": {"severity": "error"},
            "architecture.temporal_hotspot": {"severity": "error"},
            "architecture.hidden_change_coupling": {"severity": "warning"},
        },
    },
    "legacy": {
        "thresholds": {"max_cycles": 5, "max_critical_components": 5, "max_high_components": 30, "max_findings": 100, "max_hotspots": 50},
        "rules": {"architecture.hidden_change_coupling": {"enabled": False}},
    },
    "monorepo": {
        "thresholds": {"max_cycles": 0, "max_critical_components": 0, "max_high_components": 15, "max_findings": 50, "max_hotspots": 25},
        "rules": {"architecture.high_fanout": {"severity": "note"}},
    },
}


def available_rule_packs() -> tuple[str, ...]:
    return tuple(sorted(RULE_PACKS))


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        elif isinstance(value, list) and isinstance(result.get(key), list):
            result[key] = [*result[key], *deepcopy(value)]
        else:
            result[key] = deepcopy(value)
    return result


def merge_rule_packs(policy: dict[str, Any], names: list[str] | tuple[str, ...]) -> tuple[dict[str, Any], list[str]]:
    result: dict[str, Any] = {}
    selected: list[str] = []
    for name in names:
        if name not in RULE_PACKS:
            raise ValueError(f"Unknown rule pack: {name}. Available: {', '.join(available_rule_packs())}")
        result = _merge(result, RULE_PACKS[name])
        selected.append(name)
    result = _merge(result, policy)
    return result, selected


def apply_rule_configuration(findings: list[Finding], policy: dict[str, Any]) -> tuple[list[Finding], dict[str, Any]]:
    rules = policy.get("rules", {}) if isinstance(policy.get("rules", {}), dict) else {}
    retained: list[Finding] = []
    disabled: list[str] = []
    overridden: dict[str, str] = {}
    for finding in findings:
        config = rules.get(finding.rule_id, {})
        if not isinstance(config, dict):
            config = {}
        if config.get("enabled") is False:
            disabled.append(finding.rule_id)
            continue
        severity = str(config.get("severity", finding.severity))
        if severity in {"error", "warning", "note"} and severity != finding.severity:
            finding.severity = severity
            overridden[finding.rule_id] = severity
        retained.append(finding)
    return retained, {
        "configured_rule_count": len(rules),
        "disabled_rules": sorted(set(disabled)),
        "severity_overrides": dict(sorted(overridden.items())),
    }
