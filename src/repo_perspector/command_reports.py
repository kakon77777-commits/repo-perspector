from __future__ import annotations

import json
from pathlib import Path

from .change_impact import analyze_change_impact, collect_changed_files, write_change_impact_outputs
from .checking import check_report
from .diffing import compare_reports, load_report_path, write_diff_outputs
from .state import build_trend, load_state, record_snapshot, write_trend_outputs


def run_diff(args) -> int:
    old = load_report_path(args.old)
    new = load_report_path(args.new)
    diff = compare_reports(old, new)
    outputs = write_diff_outputs(diff, Path(args.output).expanduser().resolve())
    summary = diff["summary"]
    print(
        f"Diff: +{summary['components_added']} / -{summary['components_removed']} components; "
        f"{summary['components_changed']} changed; +{summary.get('findings_added', 0)} findings"
    )
    for name, path in outputs.items():
        print(f"{name:10}: {path}")
    return 0


def run_check(args) -> int:
    report = load_report_path(args.report)
    baseline = load_report_path(args.baseline) if args.baseline else None
    if (args.new_only or args.fail_on_risk_regression or args.fail_on_new_cycle) and baseline is None:
        raise ValueError("baseline-aware check options require --baseline")
    result = check_report(
        report,
        fail_on=args.fail_on,
        max_cycles=args.max_cycles,
        max_critical=args.max_critical,
        max_high=args.max_high,
        max_findings=args.max_findings,
        max_hotspots=args.max_hotspots,
        min_health=args.min_health,
        max_health_drop=args.max_health_drop,
        baseline=baseline,
        new_only=args.new_only,
        fail_on_risk_regression=args.fail_on_risk_regression,
        fail_on_new_cycle=args.fail_on_new_cycle,
    )
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("PASS" if result["passed"] else "FAIL")
        print(f"Scope: {result['scope']}")
        print(f"Findings by severity: {result['severity_counts']}")
        print(f"Risk tiers: {result['risk_counts']}")
        for item in result["checks"]:
            print(f"{'PASS' if item['passed'] else 'FAIL'} {item['name']}: {item['actual']} <= {item['maximum']}")
        if result["failed_by_severity"]:
            print(f"FAIL finding severity threshold: {args.fail_on}")
        if result["failed_by_risk_regression"]:
            print("FAIL component risk tier regression")
        if result["failed_by_new_cycle"]:
            print("FAIL new dependency cycle")
        if result.get("failed_by_health"):
            print("FAIL minimum architecture health")
        if result.get("failed_by_health_drop"):
            print("FAIL architecture health regression")
        if result.get("baseline"):
            print(f"Baseline delta: {result['baseline']['summary']}")
    return 0 if result["passed"] else 1


def run_change_impact(args) -> int:
    report = load_report_path(args.report)
    baseline = load_report_path(args.baseline) if args.baseline else None
    changes = collect_changed_files(Path(args.repo).expanduser(), args.base, args.head)
    result = analyze_change_impact(
        report,
        changes,
        base_ref=args.base,
        head_ref=args.head,
        baseline_report=baseline,
    )
    outputs = write_change_impact_outputs(result, Path(args.output).expanduser().resolve())
    summary = result["summary"]
    print(
        f"Change impact: {summary['changed_files']} files / "
        f"{summary['changed_components']} direct components / "
        f"{summary['impacted_components']} impacted components"
    )
    print(f"Risk: {summary['risk_tier']} ({summary['risk_score']:.4f})")
    for name, path in outputs.items():
        print(f"{name:10}: {path}")
    return 0


def run_record(args) -> int:
    report = load_report_path(args.report)
    result = record_snapshot(
        report, args.state_dir, label=args.label, retention=max(1, args.retention)
    )
    snapshot = result["snapshot"]
    print("Recorded" if result["recorded"] else "Skipped duplicate")
    print(f"Snapshot: {snapshot.get('id')}")
    print(f"Health: {float(snapshot.get('health_score', 0)):.2f} ({snapshot.get('health_grade') or '?'})")
    print(f"State: {result['state_dir']}")
    return 0


def run_trend(args) -> int:
    state = load_state(args.state_dir)
    trend = build_trend(state)
    outputs = write_trend_outputs(trend, args.output)
    print(f"Snapshots: {trend['summary']['snapshot_count']}")
    print(f"Health change: {trend['summary']['health_change']:+.2f}")
    for name, path in outputs.items():
        print(f"{name:10}: {path}")
    return 0
