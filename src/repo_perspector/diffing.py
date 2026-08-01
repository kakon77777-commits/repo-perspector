from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_report_path(value: str | Path) -> dict[str, Any]:
    path = Path(value).expanduser().resolve()
    if path.is_dir():
        path = path / "architecture.json"
    if not path.is_file():
        raise ValueError(f"Architecture report not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read architecture report {path}: {exc}") from exc
    if not isinstance(payload, dict) or "components" not in payload or "dependencies" not in payload:
        raise ValueError(f"Not a repo-perspector architecture report: {path}")
    return payload


def _component_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(component["path"]): component for component in report.get("components", []) if "path" in component}


def _dependency_set(report: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {(str(dep.get("source")), str(dep.get("target")), str(dep.get("kind", "static_import"))) for dep in report.get("dependencies", [])}


def _symbol_set(report: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {(str(symbol.get("qualified_name")), str(symbol.get("kind")), str(symbol.get("path"))) for symbol in report.get("symbols", [])}


def _workspace_set(report: dict[str, Any]) -> set[tuple[str, str, str, str]]:
    return {
        (str(item.get("path")), str(item.get("name")), str(item.get("ecosystem")), str(item.get("manifest")))
        for item in report.get("workspaces", []) if isinstance(item, dict)
    }


def _finding_set(report: dict[str, Any]) -> set[tuple[str, str, str, str]]:
    return {
        (str(item.get("rule_id")), str(item.get("severity")), str(item.get("component")), str(item.get("message")))
        for item in report.get("findings", [])
    }


def compare_reports(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_components, new_components = _component_map(old), _component_map(new)
    old_names, new_names = set(old_components), set(new_components)
    changed_components: list[dict[str, Any]] = []
    watched_fields = ("role", "description", "stability", "incoming", "outgoing", "centrality")
    for name in sorted(old_names & new_names):
        before, after = old_components[name], new_components[name]
        changes: dict[str, dict[str, Any]] = {}
        for field in watched_fields:
            if before.get(field) != after.get(field):
                changes[field] = {"before": before.get(field), "after": after.get(field)}
        for nested, fields in (("impact", ("risk_tier", "risk_score", "blast_radius")), ("metrics", ("hotspot_score", "complexity", "symbol_count", "instability"))):
            before_nested, after_nested = before.get(nested) or {}, after.get(nested) or {}
            for field in fields:
                if before_nested.get(field) != after_nested.get(field):
                    changes[f"{nested}.{field}"] = {"before": before_nested.get(field), "after": after_nested.get(field)}
        before_deps, after_deps = set(before.get("internal_dependencies", [])), set(after.get("internal_dependencies", []))
        if before_deps != after_deps:
            changes["internal_dependencies"] = {"added": sorted(after_deps - before_deps), "removed": sorted(before_deps - after_deps)}
        if changes:
            changed_components.append({"path": name, "changes": changes})

    old_deps, new_deps = _dependency_set(old), _dependency_set(new)
    old_symbols, new_symbols = _symbol_set(old), _symbol_set(new)
    old_findings, new_findings = _finding_set(old), _finding_set(new)
    old_workspaces, new_workspaces = _workspace_set(old), _workspace_set(new)
    old_pattern = ((old.get("architecture") or {}).get("pattern") or {}).get("primary")
    new_pattern = ((new.get("architecture") or {}).get("pattern") or {}).get("primary")
    old_health_raw = (((old.get("quality") or {}).get("health") or {}).get("score"))
    new_health_raw = (((new.get("quality") or {}).get("health") or {}).get("score"))
    old_health = float(old_health_raw) if old_health_raw is not None else None
    new_health = float(new_health_raw) if new_health_raw is not None else None
    health_change = round(new_health - old_health, 2) if old_health is not None and new_health is not None else None

    return {
        "schema_version": "repo-perspector.diff/v0.6",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "old_project": old.get("project", {}),
        "new_project": new.get("project", {}),
        "summary": {
            "components_added": len(new_names - old_names), "components_removed": len(old_names - new_names),
            "components_changed": len(changed_components), "dependencies_added": len(new_deps - old_deps),
            "dependencies_removed": len(old_deps - new_deps), "symbols_added": len(new_symbols - old_symbols),
            "symbols_removed": len(old_symbols - new_symbols), "findings_added": len(new_findings - old_findings),
            "findings_resolved": len(old_findings - new_findings), "workspaces_added": len(new_workspaces - old_workspaces),
            "workspaces_removed": len(old_workspaces - new_workspaces), "architecture_pattern_changed": old_pattern != new_pattern,
            "health_before": old_health, "health_after": new_health, "health_change": health_change,
        },
        "architecture_pattern": {"before": old_pattern, "after": new_pattern},
        "components": {
            "added": [new_components[name] for name in sorted(new_names - old_names)],
            "removed": [old_components[name] for name in sorted(old_names - new_names)],
            "changed": changed_components,
        },
        "dependencies": {
            "added": [{"source": source, "target": target, "kind": kind} for source, target, kind in sorted(new_deps - old_deps)],
            "removed": [{"source": source, "target": target, "kind": kind} for source, target, kind in sorted(old_deps - new_deps)],
        },
        "symbols": {
            "added": [{"qualified_name": name, "kind": kind, "path": path} for name, kind, path in sorted(new_symbols - old_symbols)],
            "removed": [{"qualified_name": name, "kind": kind, "path": path} for name, kind, path in sorted(old_symbols - new_symbols)],
        },
        "workspaces": {
            "added": [{"path": path, "name": name, "ecosystem": ecosystem, "manifest": manifest} for path, name, ecosystem, manifest in sorted(new_workspaces - old_workspaces)],
            "removed": [{"path": path, "name": name, "ecosystem": ecosystem, "manifest": manifest} for path, name, ecosystem, manifest in sorted(old_workspaces - new_workspaces)],
        },
        "findings": {
            "added": [{"rule_id": rule, "severity": severity, "component": component, "message": message} for rule, severity, component, message in sorted(new_findings - old_findings)],
            "resolved": [{"rule_id": rule, "severity": severity, "component": component, "message": message} for rule, severity, component, message in sorted(old_findings - new_findings)],
        },
    }


def render_diff_markdown(diff: dict[str, Any]) -> str:
    summary = diff["summary"]
    old_name, new_name = diff.get("old_project", {}).get("name", "old"), diff.get("new_project", {}).get("name", "new")
    lines = [
        f"# 架構差分：{old_name} → {new_name}", "",
        f"- 新增／移除／變更模組：+{summary['components_added']} / -{summary['components_removed']} / Δ{summary['components_changed']}",
        f"- 新增／移除依賴：+{summary['dependencies_added']} / -{summary['dependencies_removed']}",
        f"- 新增／移除符號：+{summary['symbols_added']} / -{summary['symbols_removed']}",
        f"- 新增／已解決發現：+{summary['findings_added']} / -{summary['findings_resolved']}",
        f"- 新增／移除工作區：+{summary.get('workspaces_added', 0)} / -{summary.get('workspaces_removed', 0)}",
        f"- 架構模式變更：{'是' if summary['architecture_pattern_changed'] else '否'}",
        (f"- 架構健康：{summary.get('health_before'):.2f} → {summary.get('health_after'):.2f}（{summary.get('health_change'):+.2f}）" if summary.get("health_change") is not None else "- 架構健康：舊版或新版缺少健康指標"), "",
    ]
    if diff["architecture_pattern"].get("before") != diff["architecture_pattern"].get("after"):
        lines.extend(["## 架構模式", "", f"- 之前：`{diff['architecture_pattern'].get('before')}`", f"- 之後：`{diff['architecture_pattern'].get('after')}`", ""])
    for heading, key in (("新增模組", "added"), ("移除模組", "removed")):
        values = diff["components"][key]
        if values:
            lines.extend([f"## {heading}", ""])
            lines.extend(f"- `{item['path']}`" for item in values)
            lines.append("")
    if diff["components"]["changed"]:
        lines.extend(["## 變更模組", ""])
        for item in diff["components"]["changed"]:
            lines.extend([f"### `{item['path']}`", ""])
            for field, values in item["changes"].items():
                if "added" in values or "removed" in values:
                    lines.append(f"- **{field}**：新增 `{values.get('added', [])}`；移除 `{values.get('removed', [])}`")
                else:
                    lines.append(f"- **{field}**：`{values.get('before')}` → `{values.get('after')}`")
            lines.append("")
    for heading, group, key in (("新增依賴", "dependencies", "added"), ("移除依賴", "dependencies", "removed"), ("新增符號", "symbols", "added"), ("移除符號", "symbols", "removed"), ("新增發現", "findings", "added"), ("已解決發現", "findings", "resolved")):
        values = diff[group][key]
        if values:
            lines.extend([f"## {heading}", ""])
            for item in values[:200]:
                if group == "dependencies":
                    lines.append(f"- `{item['source']}` → `{item['target']}`（{item['kind']}）")
                elif group == "symbols":
                    lines.append(f"- `{item['qualified_name']}`（{item['kind']}，`{item['path']}`）")
                else:
                    lines.append(f"- [{item['severity']}] `{item['rule_id']}`：{item['message']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_diff_outputs(diff: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = output_dir / "architecture-diff.json", output_dir / "architecture-diff.md"
    json_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_diff_markdown(diff), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}
