from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _fingerprint_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(payload, ensure_ascii=False))
    normalized.pop("generated_at", None)
    analysis = normalized.get("analysis")
    if isinstance(analysis, dict):
        analysis.pop("timing_seconds", None)
        analysis.pop("cache", None)
        analysis.pop("incremental", None)
    project = normalized.get("project")
    if isinstance(project, dict):
        project.pop("root", None)
    evidence = normalized.get("evidence")
    if isinstance(evidence, dict):
        evidence.pop("file_history", None)
    return normalized


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(_fingerprint_payload(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _project_identity(report: dict[str, Any]) -> dict[str, str | None]:
    project = report.get("project", {}) if isinstance(report.get("project"), dict) else {}
    origin = project.get("origin_url")
    name = str(project.get("name") or "unknown")
    key = str(origin or name)
    return {"key": key, "name": name, "origin_url": str(origin) if origin else None}


def _snapshot_summary(report: dict[str, Any], *, snapshot_id: str, label: str | None, fingerprint: str, file_name: str) -> dict[str, Any]:
    project = report.get("project", {})
    quality = report.get("quality", {})
    health = quality.get("health", {})
    findings = quality.get("finding_summary", {})
    risk_counts: dict[str, int] = {}
    hotspot_count = 0
    for component in report.get("components", []):
        tier = str((component.get("impact") or {}).get("risk_tier", "unknown"))
        risk_counts[tier] = risk_counts.get(tier, 0) + 1
        if float((component.get("metrics") or {}).get("hotspot_score", 0.0)) >= 0.72:
            hotspot_count += 1
    return {
        "id": snapshot_id,
        "generated_at": report.get("generated_at"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "fingerprint": fingerprint,
        "file": file_name,
        "project": project.get("name"),
        "commit": project.get("commit"),
        "branch": project.get("branch"),
        "partial": bool((report.get("analysis") or {}).get("partial")),
        "health_score": float(health.get("score", 0.0)),
        "health_grade": health.get("grade"),
        "health_status": health.get("status"),
        "components": int(project.get("component_count", 0)),
        "dependencies": int(project.get("dependency_count", 0)),
        "symbols": int(project.get("symbol_count", 0)),
        "workspaces": int(project.get("workspace_count", 0)),
        "cycles": len(report.get("cycles", [])),
        "findings": {key: int(findings.get(key, 0)) for key in ("error", "warning", "note")},
        "risk_tiers": risk_counts,
        "hotspots": hotspot_count,
    }


def record_snapshot(report: dict[str, Any], state_dir: str | Path, *, label: str | None = None, retention: int = 100) -> dict[str, Any]:
    root = Path(state_dir).expanduser().resolve()
    snapshots = root / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "history.json"
    manifest = {"schema_version": "repo-perspector.state/v0.6", "project": None, "snapshots": []}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("snapshots"), list):
                manifest = loaded
        except (OSError, json.JSONDecodeError):
            pass

    identity = _project_identity(report)
    existing_identity = manifest.get("project")
    if isinstance(existing_identity, dict) and existing_identity.get("key") and existing_identity.get("key") != identity["key"]:
        raise ValueError(
            f"State directory belongs to project {existing_identity.get('name') or existing_identity.get('key')}; "
            f"refusing snapshot from {identity['name']}. Use a separate --state-dir."
        )
    manifest["project"] = identity

    fingerprint = hashlib.sha256(_canonical_bytes(report)).hexdigest()
    for item in manifest["snapshots"]:
        if item.get("fingerprint") == fingerprint:
            return {"recorded": False, "reason": "duplicate", "snapshot": item, "state_dir": str(root)}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    commit = str((report.get("project") or {}).get("commit") or "working-tree")[:12]
    snapshot_id = f"{stamp}-{commit}"
    file_name = f"{snapshot_id}.json.gz"
    target = snapshots / file_name
    temporary = target.with_suffix(target.suffix + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, separators=(",", ":"))
    os.replace(temporary, target)
    summary = _snapshot_summary(report, snapshot_id=snapshot_id, label=label, fingerprint=fingerprint, file_name=file_name)
    manifest["snapshots"].append(summary)
    manifest["snapshots"].sort(key=lambda item: str(item.get("recorded_at", "")))

    retention = max(1, retention)
    while len(manifest["snapshots"]) > retention:
        removed = manifest["snapshots"].pop(0)
        old_path = snapshots / str(removed.get("file", ""))
        if old_path.is_file():
            old_path.unlink()

    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    temp_manifest = manifest_path.with_suffix(".json.tmp")
    temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_manifest, manifest_path)
    return {"recorded": True, "snapshot": summary, "state_dir": str(root), "history": str(manifest_path)}


def load_state(state_dir: str | Path) -> dict[str, Any]:
    root = Path(state_dir).expanduser().resolve()
    path = root / "history.json"
    if not path.is_file():
        raise ValueError(f"State history not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("snapshots"), list):
        raise ValueError(f"Invalid state history: {path}")
    return payload


def build_trend(state: dict[str, Any]) -> dict[str, Any]:
    snapshots = list(state.get("snapshots", []))
    snapshots.sort(key=lambda item: str(item.get("recorded_at", "")))
    points: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for item in snapshots:
        point = dict(item)
        point["delta"] = {}
        if previous is not None:
            for key in ("health_score", "components", "dependencies", "symbols", "cycles", "hotspots"):
                point["delta"][key] = round(float(item.get(key, 0)) - float(previous.get(key, 0)), 2)
            point["delta"]["errors"] = int((item.get("findings") or {}).get("error", 0)) - int((previous.get("findings") or {}).get("error", 0))
            point["delta"]["warnings"] = int((item.get("findings") or {}).get("warning", 0)) - int((previous.get("findings") or {}).get("warning", 0))
        points.append(point)
        previous = item
    latest = points[-1] if points else None
    first = points[0] if points else None
    health_change = round(float(latest.get("health_score", 0)) - float(first.get("health_score", 0)), 2) if latest and first else 0.0
    return {
        "schema_version": "repo-perspector.trend/v0.6",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "snapshot_count": len(points),
            "first_recorded_at": first.get("recorded_at") if first else None,
            "latest_recorded_at": latest.get("recorded_at") if latest else None,
            "health_change": health_change,
            "best_health": max((float(item.get("health_score", 0)) for item in points), default=0.0),
            "worst_health": min((float(item.get("health_score", 0)) for item in points), default=0.0),
        },
        "points": points,
    }


def render_trend_markdown(trend: dict[str, Any]) -> str:
    summary = trend["summary"]
    lines = [
        "# Repository Architecture Trend", "",
        f"- Snapshots: {summary['snapshot_count']}",
        f"- Health change: {summary['health_change']:+.2f}",
        f"- Best / worst health: {summary['best_health']:.2f} / {summary['worst_health']:.2f}", "",
        "| Recorded | Label | Commit | Health | Δ Health | Components | Cycles | Errors | Warnings | Hotspots |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for point in trend["points"]:
        delta = point.get("delta", {})
        lines.append(
            f"| {point.get('recorded_at', '')} | {point.get('label') or ''} | `{point.get('commit') or ''}` | "
            f"{float(point.get('health_score', 0)):.2f} ({point.get('health_grade') or '?'}) | "
            f"{float(delta.get('health_score', 0)):+.2f} | {point.get('components', 0)} | {point.get('cycles', 0)} | "
            f"{(point.get('findings') or {}).get('error', 0)} | {(point.get('findings') or {}).get('warning', 0)} | {point.get('hotspots', 0)} |"
        )
    return "\n".join(lines) + "\n"


def render_trend_html(trend: dict[str, Any]) -> str:
    payload = json.dumps(trend, ensure_ascii=False).replace("</", "<\\/")
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Architecture Trend</title><style>body{{font:14px system-ui;margin:24px;background:#f5f6fa;color:#182033}}.panel{{background:white;border:1px solid #d9deea;border-radius:12px;padding:18px;max-width:1100px;margin:auto}}svg{{width:100%;height:360px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #e3e6ee;text-align:left}}.muted{{color:#687083}}</style></head><body><div class="panel"><h1>Repository Architecture Trend</h1><p id="summary" class="muted"></p><svg id="chart" viewBox="0 0 1000 320"></svg><table><thead><tr><th>Recorded</th><th>Label</th><th>Commit</th><th>Health</th><th>Cycles</th><th>Errors</th><th>Warnings</th></tr></thead><tbody id="rows"></tbody></table></div><script type="application/json" id="data">{payload}</script><script>const T=JSON.parse(document.getElementById('data').textContent),P=T.points||[];document.getElementById('summary').textContent=`${{P.length}} snapshots · health change ${{T.summary.health_change>=0?'+':''}}${{T.summary.health_change}}`;const S=document.getElementById('chart'),ns='http://www.w3.org/2000/svg';if(P.length){{const pts=P.map((p,i)=>[50+(900*i/Math.max(1,P.length-1)),280-(240*(Number(p.health_score)||0)/100)]);const path=document.createElementNS(ns,'polyline');path.setAttribute('points',pts.map(p=>p.join(',')).join(' '));path.setAttribute('fill','none');path.setAttribute('stroke','currentColor');path.setAttribute('stroke-width','3');S.append(path);pts.forEach((p,i)=>{{const c=document.createElementNS(ns,'circle');c.setAttribute('cx',p[0]);c.setAttribute('cy',p[1]);c.setAttribute('r','5');c.setAttribute('fill','currentColor');S.append(c)}})}}document.getElementById('rows').innerHTML=P.slice().reverse().map(p=>`<tr><td>${{p.recorded_at||''}}</td><td>${{p.label||''}}</td><td><code>${{p.commit||''}}</code></td><td>${{p.health_score}} (${{p.health_grade||'?'}})</td><td>${{p.cycles}}</td><td>${{p.findings?.error||0}}</td><td>${{p.findings?.warning||0}}</td></tr>`).join('');</script></body></html>'''


def write_trend_outputs(trend: dict[str, Any], output_dir: str | Path) -> dict[str, Path]:
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    outputs = {"json": root / "architecture-trend.json", "markdown": root / "architecture-trend.md", "html": root / "architecture-trend.html"}
    outputs["json"].write_text(json.dumps(trend, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["markdown"].write_text(render_trend_markdown(trend), encoding="utf-8")
    outputs["html"].write_text(render_trend_html(trend), encoding="utf-8")
    return outputs
