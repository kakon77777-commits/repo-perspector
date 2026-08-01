from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .baseline import compare_baseline


def _git(root: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
        return completed.stdout
    except FileNotFoundError as exc:
        raise RuntimeError("Git executable is unavailable") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise RuntimeError(f"Git command failed: {message}") from exc


def collect_changed_files(root: Path, base_ref: str, head_ref: str = "HEAD") -> list[dict[str, Any]]:
    root = root.resolve()
    if not (root / ".git").exists():
        try:
            repository_root = Path(_git(root, ["rev-parse", "--show-toplevel"]).strip())
        except RuntimeError as exc:
            raise RuntimeError(f"Not a Git repository: {root}") from exc
    else:
        repository_root = root
    output = _git(repository_root, ["diff", "--name-status", "--find-renames", f"{base_ref}...{head_ref}", "--", "."])
    changes: list[dict[str, Any]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            changes.append({
                "status": "renamed",
                "similarity": int(status[1:]) if status[1:].isdigit() else None,
                "old_path": parts[1].replace("\\", "/"),
                "path": parts[2].replace("\\", "/"),
            })
        elif status.startswith("C") and len(parts) >= 3:
            changes.append({
                "status": "copied",
                "similarity": int(status[1:]) if status[1:].isdigit() else None,
                "old_path": parts[1].replace("\\", "/"),
                "path": parts[2].replace("\\", "/"),
            })
        elif len(parts) >= 2:
            mapping = {"A": "added", "M": "modified", "D": "deleted", "T": "type_changed", "U": "unmerged"}
            changes.append({
                "status": mapping.get(status[:1], status),
                "path": parts[1].replace("\\", "/"),
            })
    return changes


def _component_maps(report: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    file_map = {
        str(item.get("path")): str(item.get("component"))
        for item in report.get("files", [])
        if isinstance(item, dict) and item.get("path") and item.get("component")
    }
    components = {
        str(item.get("path")): item
        for item in report.get("components", [])
        if isinstance(item, dict) and item.get("path")
    }
    return file_map, components


def analyze_change_impact(
    report: dict[str, Any],
    changes: list[dict[str, Any]],
    *,
    base_ref: str,
    head_ref: str,
    baseline_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_file_map, components = _component_maps(report)
    baseline_file_map, _ = _component_maps(baseline_report or {})
    changed_components: set[str] = set()
    unmapped_files: list[str] = []
    normalized_changes: list[dict[str, Any]] = []

    for change in changes:
        path = str(change.get("path", ""))
        old_path = str(change.get("old_path", ""))
        component = current_file_map.get(path) or baseline_file_map.get(path)
        old_component = baseline_file_map.get(old_path) or current_file_map.get(old_path)
        selected = component or old_component
        if selected:
            changed_components.add(selected)
        elif path:
            unmapped_files.append(path)
        normalized_changes.append({**change, "component": selected, "old_component": old_component})

    impacted: dict[str, dict[str, Any]] = {}
    for component_path in sorted(changed_components):
        component = components.get(component_path, {})
        impacted[component_path] = {
            "component": component_path,
            "distance": 0,
            "source_components": [component_path],
            "risk_tier": (component.get("impact") or {}).get("risk_tier", "unknown"),
            "risk_score": float((component.get("impact") or {}).get("risk_score", 0.0)),
            "hotspot_score": float((component.get("metrics") or {}).get("hotspot_score", 0.0)),
        }
        distances = (component.get("impact") or {}).get("distance_by_component", {})
        if isinstance(distances, dict):
            for target, raw_distance in distances.items():
                distance = int(raw_distance)
                target_component = components.get(str(target), {})
                existing = impacted.get(str(target))
                if existing is None or distance < int(existing["distance"]):
                    impacted[str(target)] = {
                        "component": str(target),
                        "distance": distance,
                        "source_components": [component_path],
                        "risk_tier": (target_component.get("impact") or {}).get("risk_tier", "unknown"),
                        "risk_score": float((target_component.get("impact") or {}).get("risk_score", 0.0)),
                        "hotspot_score": float((target_component.get("metrics") or {}).get("hotspot_score", 0.0)),
                    }
                elif distance == int(existing["distance"]) and component_path not in existing["source_components"]:
                    existing["source_components"].append(component_path)

    impacted_values = sorted(
        impacted.values(),
        key=lambda item: (int(item["distance"]), -float(item["risk_score"]), str(item["component"])),
    )
    direct_risk = max(
        (float((components.get(path, {}).get("impact") or {}).get("risk_score", 0.0)) for path in changed_components),
        default=0.0,
    )
    impact_ratio = len(impacted) / max(1, len(components))
    change_volume = min(1.0, len(changes) / max(1, int(report.get("project", {}).get("file_count", 1))))
    score = min(1.0, 0.55 * direct_risk + 0.30 * impact_ratio + 0.15 * change_volume)
    if score >= 0.70:
        tier = "critical"
    elif score >= 0.45:
        tier = "high"
    elif score >= 0.20:
        tier = "medium"
    else:
        tier = "low"

    component_tokens = {path.rsplit("/", 1)[-1].lower() for path in changed_components}
    test_candidates: list[str] = []
    for item in report.get("files", []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        lowered = path.lower()
        if not any(token in lowered for token in ("test", "spec")):
            continue
        imported = " ".join(str(value).lower() for value in item.get("imports", []))
        if any(token and (token in lowered or token in imported) for token in component_tokens):
            test_candidates.append(path)
    test_candidates = sorted(set(test_candidates))[:100]

    baseline = compare_baseline(baseline_report, report) if baseline_report is not None else None
    return {
        "schema_version": "repo-perspector.change-impact/v0.6",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": report.get("project", {}),
        "git_range": {"base": base_ref, "head": head_ref},
        "summary": {
            "changed_files": len(changes),
            "changed_components": len(changed_components),
            "impacted_components": len(impacted),
            "unmapped_files": len(unmapped_files),
            "risk_score": round(score, 4),
            "risk_tier": tier,
        },
        "changes": normalized_changes,
        "changed_components": sorted(changed_components),
        "impacted_components": impacted_values,
        "unmapped_files": sorted(set(unmapped_files)),
        "recommended_tests": test_candidates,
        "baseline": baseline,
        "guidance": [
            "Review distance-0 components first; they contain direct file changes.",
            "Review high/critical impacted components before merging.",
            "Run targeted tests when listed; otherwise run the repository's full test suite.",
            "Treat the score as an explainable triage estimate, not a defect probability.",
        ],
    }


def render_change_impact_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        f"# PR／變更影響：{result.get('project', {}).get('name', 'repository')}",
        "",
        f"- Git 範圍：`{result['git_range']['base']}...{result['git_range']['head']}`",
        f"- 變更檔案：{summary['changed_files']}",
        f"- 直接變更模組：{summary['changed_components']}",
        f"- 傳遞影響模組：{summary['impacted_components']}",
        f"- 風險：{summary['risk_tier']}（{summary['risk_score']:.4f}）",
        "",
        "## 直接變更模組",
        "",
    ]
    if result["changed_components"]:
        lines.extend(f"- `{item}`" for item in result["changed_components"])
    else:
        lines.append("- 未映射到已知架構模組。")
    lines.extend([
        "",
        "## 影響排序",
        "",
        "| 距離 | 模組 | 風險 | 分數 | 熱點 | 來源 |",
        "|---:|---|---|---:|---:|---|",
    ])
    for item in result["impacted_components"][:100]:
        lines.append(
            f"| {item['distance']} | `{item['component']}` | {item['risk_tier']} | "
            f"{item['risk_score']:.4f} | {item['hotspot_score']:.4f} | "
            f"{', '.join(f'`{value}`' for value in item['source_components'])} |"
        )
    lines.extend(["", "## 建議測試", ""])
    if result["recommended_tests"]:
        lines.extend(f"- `{item}`" for item in result["recommended_tests"])
    else:
        lines.append("- 未找到可靠的定向測試映射；建議執行完整測試套件。")
    if result.get("unmapped_files"):
        lines.extend(["", "## 未映射檔案", ""])
        lines.extend(f"- `{item}`" for item in result["unmapped_files"])
    baseline = result.get("baseline")
    if baseline:
        lines.extend([
            "",
            "## 基準線回歸",
            "",
            f"- 新增發現：{baseline['summary']['new_findings']}",
            f"- 風險升級：{baseline['summary']['risk_regressions']}",
            f"- 新增循環：{baseline['summary']['new_cycles']}",
        ])
    return "\n".join(lines).rstrip() + "\n"


def write_change_impact_outputs(result: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "change-impact.json"
    markdown_path = output_dir / "change-impact.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_change_impact_markdown(result), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
