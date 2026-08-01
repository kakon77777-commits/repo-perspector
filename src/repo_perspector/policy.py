from __future__ import annotations

import ast
import fnmatch
import json
from pathlib import Path
from typing import Any

from .models import Component, Dependency, Finding


_POLICY_NAMES = (".perspector.yml", ".perspector.yaml", ".perspector.json")


def _scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    lowered = value.lower()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part.strip()) for part in inner.split(",")]
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None
    try:
        return json.loads(value)
    except Exception:
        try:
            return ast.literal_eval(value)
        except Exception:
            return value.strip("\"'")


def _minimal_yaml_load(text: str) -> dict[str, Any]:
    """Parse the indentation/list subset used by Perspector policies without dependencies."""
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, raw.strip()))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        is_list = index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("-")
        if is_list:
            result: list[Any] = []
            while index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("-"):
                content = lines[index][1][1:].strip()
                index += 1
                if not content:
                    if index < len(lines) and lines[index][0] > indent:
                        item, index = parse_block(index, lines[index][0])
                    else:
                        item = None
                elif ":" in content:
                    key, value = content.split(":", 1)
                    item = {key.strip(): _scalar(value)}
                    if value.strip() == "" and index < len(lines) and lines[index][0] > indent:
                        nested, index = parse_block(index, lines[index][0])
                        item[key.strip()] = nested
                    if index < len(lines) and lines[index][0] > indent:
                        continuation, index = parse_block(index, lines[index][0])
                        if isinstance(continuation, dict):
                            item.update(continuation)
                else:
                    item = _scalar(content)
                result.append(item)
            return result, index

        result_dict: dict[str, Any] = {}
        while index < len(lines) and lines[index][0] == indent and not lines[index][1].startswith("-"):
            content = lines[index][1]
            if ":" not in content:
                raise ValueError(f"invalid YAML line: {content}")
            key, value = content.split(":", 1)
            key = key.strip()
            index += 1
            if value.strip():
                result_dict[key] = _scalar(value)
            elif index < len(lines) and lines[index][0] > indent:
                nested, index = parse_block(index, lines[index][0])
                result_dict[key] = nested
            else:
                result_dict[key] = {}
        return result_dict, index

    if not lines:
        return {}
    parsed, index = parse_block(0, lines[0][0])
    if index != len(lines) or not isinstance(parsed, dict):
        raise ValueError("policy YAML root must be a mapping")
    return parsed


def discover_policy(root: Path, explicit: str | Path | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            raise ValueError(f"Policy file not found: {path}")
        return path.resolve()
    for name in _POLICY_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate.resolve()
    return None


def load_policy(path: Path | None) -> tuple[dict[str, Any], list[str]]:
    if path is None:
        return {}, []
    warnings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Unable to read policy {path}: {exc}") from exc
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            try:
                import yaml  # type: ignore
            except ImportError:
                payload = _minimal_yaml_load(text)
                warnings.append("PyYAML unavailable; used the built-in policy YAML subset parser.")
            else:
                payload = yaml.safe_load(text) or {}
    except Exception as exc:
        raise ValueError(f"Unable to parse policy {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Perspector policy root must be a mapping/object")
    return payload, warnings


def _matches(path: str, patterns: object) -> bool:
    if isinstance(patterns, str):
        patterns = [patterns]
    if not isinstance(patterns, list):
        return False
    return any(fnmatch.fnmatch(path, str(pattern)) for pattern in patterns)


def evaluate_policy(
    policy: dict[str, Any],
    components: list[Component],
    dependencies: list[Dependency],
    *,
    source_path: Path | None = None,
) -> tuple[dict[str, Any], list[Finding]]:
    if not policy:
        return {"loaded": False, "source": None, "layers": {}, "thresholds": {}}, []

    layer_defs = policy.get("layers", [])
    component_layers: dict[str, str] = {}
    layer_permissions: dict[str, set[str]] = {}
    if isinstance(layer_defs, list):
        for entry in layer_defs:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            name = str(entry["name"])
            allowed = entry.get("may_depend_on", [])
            if isinstance(allowed, str):
                allowed = [allowed]
            layer_permissions[name] = {str(value) for value in allowed if value is not None}
            for component in components:
                if component.path not in component_layers and _matches(component.path, entry.get("match", [])):
                    component_layers[component.path] = name

    findings: list[Finding] = []
    for dep in dependencies:
        source_layer = component_layers.get(dep.source)
        target_layer = component_layers.get(dep.target)
        if source_layer and target_layer and source_layer in layer_permissions:
            allowed = layer_permissions[source_layer]
            if allowed and target_layer not in allowed and target_layer != source_layer:
                findings.append(Finding(
                    rule_id="policy.layer_dependency",
                    severity="error",
                    title="違反架構分層依賴規則",
                    message=f"{dep.source}（{source_layer}）不可依賴 {dep.target}（{target_layer}）。",
                    component=dep.source,
                    path=dep.evidence[0].split(":", 1)[0] if dep.evidence else None,
                    evidence=dep.evidence,
                    properties={"source_layer": source_layer, "target_layer": target_layer},
                ))

    deny_rules = policy.get("deny_dependencies", [])
    if isinstance(deny_rules, list):
        for index, rule in enumerate(deny_rules, start=1):
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("id") or f"policy.deny_dependency.{index}")
            severity = str(rule.get("severity") or "error")
            for dep in dependencies:
                if _matches(dep.source, rule.get("from", [])) and _matches(dep.target, rule.get("to", [])):
                    findings.append(Finding(
                        rule_id=rule_id,
                        severity=severity if severity in {"error", "warning", "note"} else "error",
                        title=str(rule.get("title") or "違反禁止依賴規則"),
                        message=str(rule.get("message") or f"{dep.source} 不可依賴 {dep.target}。"),
                        component=dep.source,
                        path=dep.evidence[0].split(":", 1)[0] if dep.evidence else None,
                        evidence=dep.evidence,
                        properties={"source": dep.source, "target": dep.target},
                    ))

    required = policy.get("required_components", [])
    existing = {component.path for component in components}
    if isinstance(required, list):
        for index, rule in enumerate(required, start=1):
            if isinstance(rule, str):
                rule = {"match": [rule]}
            if not isinstance(rule, dict):
                continue
            patterns = rule.get("match", [])
            if not any(_matches(path, patterns) for path in existing):
                findings.append(Finding(
                    rule_id=str(rule.get("id") or f"policy.required_component.{index}"),
                    severity=str(rule.get("severity") or "error"),
                    title=str(rule.get("title") or "缺少必要架構模組"),
                    message=str(rule.get("message") or f"找不到符合 {patterns} 的必要模組。"),
                    properties={"patterns": patterns},
                ))

    thresholds = policy.get("thresholds", {}) if isinstance(policy.get("thresholds", {}), dict) else {}
    summary = {
        "loaded": True,
        "source": str(source_path) if source_path else None,
        "version": policy.get("version", 1),
        "component_layers": component_layers,
        "layer_count": len(layer_permissions),
        "thresholds": thresholds,
        "finding_count": len(findings),
    }
    return summary, findings
