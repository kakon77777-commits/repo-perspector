from __future__ import annotations

import json
from typing import Any

from .models import ArchitectureReport, Finding


def _rule(finding: Finding) -> dict[str, Any]:
    return {
        "id": finding.rule_id,
        "name": finding.rule_id.replace(".", "_"),
        "shortDescription": {"text": finding.title},
        "fullDescription": {"text": finding.message},
        "defaultConfiguration": {"level": finding.severity},
    }


def render_sarif(report: ArchitectureReport) -> str:
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for finding in report.findings:
        rules.setdefault(finding.rule_id, _rule(finding))
        result: dict[str, Any] = {
            "ruleId": finding.rule_id,
            "level": finding.severity,
            "message": {"text": finding.message},
            "properties": {"component": finding.component, **finding.properties},
        }
        if finding.path:
            region: dict[str, int] = {}
            if finding.line:
                region["startLine"] = max(1, int(finding.line))
            location: dict[str, Any] = {
                "physicalLocation": {"artifactLocation": {"uri": finding.path}}
            }
            if region:
                location["physicalLocation"]["region"] = region
            result["locations"] = [location]
        results.append(result)

    payload = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "repo-perspector",
                "version": "0.4.0",
                "informationUri": "https://github.com/",
                "rules": list(rules.values()),
            }},
            "results": results,
        }],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
