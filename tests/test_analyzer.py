from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from repo_perspector.analyzer import analyze_repository
from repo_perspector.change_impact import analyze_change_impact, collect_changed_files, write_change_impact_outputs
from repo_perspector.checking import check_report
from repo_perspector.diffing import compare_reports, write_diff_outputs
from repo_perspector.query import ReportIndex
from repo_perspector.models import SymbolRecord
from repo_perspector.parser_plugins import ParseResult, ParserRegistry
from repo_perspector.parsers import ImportMatch
from repo_perspector.renderers import write_outputs
from repo_perspector.source import PreparedSource
from repo_perspector.state import build_trend, load_state, record_snapshot, write_trend_outputs


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


class AnalyzerTest(unittest.TestCase):
    def _make_project(self, root: Path) -> None:
        (root / "src" / "demo").mkdir(parents=True)
        (root / "src" / "demo" / "models.py").write_text(
            "class Item:\n    def label(self):\n        return 'item'\n",
            encoding="utf-8",
        )
        (root / "src" / "demo" / "service.py").write_text(
            "from .models import Item\n\ndef load():\n    return Item()\n",
            encoding="utf-8",
        )

    def test_python_dependencies_symbols_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_project(root)
            source = PreparedSource(root, "demo", "local", None, None, None)
            report = analyze_repository(source)
            self.assertEqual(report.project["file_count"], 2)
            self.assertGreaterEqual(report.project["component_count"], 2)
            self.assertTrue(any(d.source.endswith("service") and d.target.endswith("models") for d in report.dependencies))
            self.assertTrue(any(symbol.qualified_name.endswith("service.load") for symbol in report.symbols))
            self.assertTrue(any(rel.source.endswith("service.load") and rel.target.endswith("models.Item") for rel in report.symbol_relationships))
            self.assertTrue(all(component.impact.get("risk_tier") for component in report.components))
            self.assertTrue(all("hotspot_score" in component.metrics for component in report.components))
            output = root / "report"
            files = write_outputs(report, output)
            self.assertEqual(set(files), {"json", "mermaid", "html", "mssp", "summary", "findings", "sarif", "symbols", "index"})
            for path in files.values():
                self.assertTrue(path.exists())
                self.assertGreater(path.stat().st_size, 0)
            payload = json.loads((output / "architecture.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "repo-perspector.ir/v0.6")
            sarif = json.loads((output / "architecture.sarif").read_text(encoding="utf-8"))
            self.assertEqual(sarif["version"], "2.1.0")

    def test_git_history_cochange_and_query(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _git(root, "init")
            _git(root, "config", "user.email", "test@example.com")
            _git(root, "config", "user.name", "Test User")
            self._make_project(root)
            _git(root, "add", ".")
            _git(root, "commit", "-m", "initial")
            for number in range(3):
                (root / "src" / "demo" / "service.py").write_text(
                    f"from .models import Item\n\ndef load():\n    return Item()  # {number}\n", encoding="utf-8"
                )
                (root / "src" / "demo" / "models.py").write_text(
                    f"class Item:\n    version = {number}\n", encoding="utf-8"
                )
                _git(root, "add", ".")
                _git(root, "commit", "-m", f"change both {number}")

            source = PreparedSource(root, "demo", "local", None, "main", None)
            report = analyze_repository(source, history_commits=20)
            self.assertTrue(report.history["available"])
            self.assertEqual(report.history["repository"]["commit_count_analyzed"], 4)
            self.assertTrue(report.history["cochange"])
            index = ReportIndex(report.to_dict())
            service = next(component for component in report.components if component.path.endswith("service"))
            models = next(component for component in report.components if component.path.endswith("models"))
            result = index.dependency_path(service.path, models.path)
            self.assertTrue(result["found"])
            self.assertEqual(result["hops"], 1)
            self.assertTrue(index.list_symbols(query="Item"))
            self.assertTrue(index.hotspots())
            self.assertTrue(index.cochange(component=service.path))

    def test_policy_and_ci_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src" / "domain").mkdir(parents=True)
            (root / "src" / "infra").mkdir(parents=True)
            (root / "src" / "infra" / "db.py").write_text("class DB: pass\n", encoding="utf-8")
            (root / "src" / "domain" / "service.py").write_text("from ..infra.db import DB\n", encoding="utf-8")
            (root / ".perspector.json").write_text(json.dumps({
                "version": 1,
                "layers": [
                    {"name": "domain", "match": ["src/domain/**"], "may_depend_on": ["domain"]},
                    {"name": "infra", "match": ["src/infra/**"], "may_depend_on": ["infra"]},
                ],
                "thresholds": {"max_cycles": 0},
            }), encoding="utf-8")
            report = analyze_repository(PreparedSource(root, "policy-demo", "local", None, None, None), history_commits=0)
            self.assertTrue(report.policy["loaded"])
            self.assertTrue(any(f.rule_id == "policy.layer_dependency" for f in report.findings))
            result = check_report(report.to_dict(), fail_on="error")
            self.assertFalse(result["passed"])
            result_ignore = check_report(report.to_dict(), fail_on="none", max_findings=99)
            self.assertTrue(result_ignore["passed"])

    def test_report_diff_includes_symbols_and_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_project(root)
            source = PreparedSource(root, "demo", "local", None, None, None)
            old = analyze_repository(source, history_commits=0).to_dict()
            (root / "src" / "demo" / "api.py").write_text("from .service import load\n\ndef endpoint(): return load()\n", encoding="utf-8")
            new = analyze_repository(source, history_commits=0).to_dict()
            diff = compare_reports(old, new)
            self.assertGreaterEqual(diff["summary"]["components_added"], 1)
            self.assertGreaterEqual(diff["summary"]["symbols_added"], 1)
            outputs = write_diff_outputs(diff, root / "diff")
            self.assertTrue(all(path.exists() for path in outputs.values()))

    def test_incremental_cache_reuses_unchanged_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_project(root)
            source = PreparedSource(root, "demo", "local", None, None, None)
            first = analyze_repository(source, history_commits=0)
            self.assertEqual(first.analysis["cache"]["hits"], 0)
            self.assertGreaterEqual(first.analysis["cache"]["misses"], 2)
            second = analyze_repository(source, history_commits=0)
            self.assertGreaterEqual(second.analysis["cache"]["hits"], 2)
            self.assertEqual(second.analysis["cache"]["misses"], 0)
            self.assertGreater(float(second.analysis["cache"]["hit_rate"]), 0.99)
            self.assertTrue(any(symbol.qualified_name.endswith("service.load") for symbol in second.symbols))

    def test_baseline_suppresses_legacy_debt_but_detects_new_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_project(root)
            (root / ".perspector.json").write_text(json.dumps({
                "version": 1,
                "deny_dependencies": [{
                    "id": "legacy-service-model-deny",
                    "from": ["src/demo/service"],
                    "to": ["src/demo/models"],
                    "severity": "error",
                }],
            }), encoding="utf-8")
            source = PreparedSource(root, "demo", "local", None, None, None)
            baseline = analyze_repository(source, history_commits=0).to_dict()
            unchanged = analyze_repository(source, history_commits=0).to_dict()
            legacy_only = check_report(unchanged, baseline=baseline, new_only=True, fail_on="warning")
            self.assertTrue(legacy_only["passed"])
            (root / "src" / "demo" / "models.py").write_text(
                "from .service import load\n\nclass Item: pass\n", encoding="utf-8"
            )
            current = analyze_repository(source, history_commits=0).to_dict()
            regression = check_report(
                current, baseline=baseline, new_only=True, fail_on="warning", fail_on_new_cycle=True
            )
            self.assertFalse(regression["passed"])
            self.assertGreaterEqual(regression["baseline"]["summary"]["new_cycles"], 1)

    def test_git_change_impact_maps_direct_and_transitive_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _git(root, "init")
            _git(root, "config", "user.email", "test@example.com")
            _git(root, "config", "user.name", "Test User")
            self._make_project(root)
            _git(root, "add", ".")
            _git(root, "commit", "-m", "baseline")
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, stdout=subprocess.PIPE
            ).stdout.strip()
            source = PreparedSource(root, "demo", "local", None, "main", base)
            baseline_report = analyze_repository(source, history_commits=20).to_dict()
            (root / "src" / "demo" / "api.py").write_text(
                "from .service import load\n\ndef endpoint(): return load()\n", encoding="utf-8"
            )
            _git(root, "add", ".")
            _git(root, "commit", "-m", "add api")
            current_report = analyze_repository(source, history_commits=20).to_dict()
            changes = collect_changed_files(root, base, "HEAD")
            impact = analyze_change_impact(
                current_report, changes, base_ref=base, head_ref="HEAD", baseline_report=baseline_report
            )
            self.assertEqual(impact["summary"]["changed_files"], 1)
            self.assertIn("src/demo/api", impact["changed_components"])
            self.assertGreaterEqual(impact["summary"]["impacted_components"], 1)
            outputs = write_change_impact_outputs(impact, root / "change-impact")
            self.assertTrue(all(path.exists() for path in outputs.values()))

    def test_monorepo_ignore_generated_and_parallel_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "package.json").write_text('{"name":"root-space","workspaces":["packages/*"]}', encoding="utf-8")
            (root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
            (root / ".perspectorignore").write_text("*.tmp\n", encoding="utf-8")
            (root / "monorepo_demo").mkdir()
            (root / "monorepo_demo" / "architecture.json").write_text("{}", encoding="utf-8")
            (root / "packages" / "web").mkdir(parents=True)
            (root / "packages" / "web" / "package.json").write_text('{"name":"web-space"}', encoding="utf-8")
            (root / "packages" / "web" / "index.ts").write_text("export function run() { return 1 }\n", encoding="utf-8")
            (root / "packages" / "engine" / "src" / "engine").mkdir(parents=True)
            (root / "packages" / "engine" / "pyproject.toml").write_text('[project]\nname="engine-space"\nversion="0.1"\n', encoding="utf-8")
            (root / "packages" / "engine" / "src" / "engine" / "core.py").write_text("def execute(): return 1\n", encoding="utf-8")
            (root / "packages" / "engine" / "src" / "engine" / "ignored.py").write_text("def hidden(): pass\n", encoding="utf-8")
            (root / "packages" / "engine" / "src" / "engine" / "generated.py").write_text("# Code generated; DO NOT EDIT.\ndef generated(): pass\n", encoding="utf-8")
            (root / "packages" / "engine" / "src" / "engine" / "mentions.py").write_text('MARKER = "generated file; do not edit"\ndef real(): return MARKER\n', encoding="utf-8")
            (root / "packages" / "engine" / "src" / "engine" / "ignored.tmp").write_text("ignored", encoding="utf-8")
            report = analyze_repository(
                PreparedSource(root, "mono", "local", None, None, None),
                history_commits=0,
                workers=4,
                skip_generated=True,
            )
            self.assertEqual(report.project["workspace_count"], 3)
            self.assertTrue(report.project["monorepo"])
            self.assertEqual(report.analysis["concurrency"]["workers"], 4)
            self.assertGreaterEqual(report.analysis["ignore"]["ignored_files"], 1)
            self.assertGreaterEqual(report.analysis["ignore"]["ignored_directories"], 1)
            self.assertFalse(any(item.path.startswith("monorepo_demo/") for item in report.files))
            self.assertFalse(any(item.path.endswith("ignored.py") for item in report.files))
            generated = next(item for item in report.files if item.path.endswith("generated.py"))
            self.assertTrue(generated.generated)
            self.assertEqual(generated.parse_error, "generated file skipped")
            self.assertEqual(report.analysis["parser_coverage"]["skipped_generated"], 1)
            mentions = next(item for item in report.files if item.path.endswith("mentions.py"))
            self.assertFalse(mentions.generated)
            self.assertTrue(any(symbol.name == "real" and symbol.path.endswith("mentions.py") for symbol in report.symbols))
            self.assertFalse(any(item.path.endswith("ignored.tmp") for item in report.files))
            workspace_names = {item["name"] for item in report.workspaces}
            self.assertEqual(workspace_names, {"root-space", "web-space", "engine-space"})
            queried = ReportIndex(report.to_dict()).list_workspaces(ecosystem="python")
            self.assertEqual([item["name"] for item in queried], ["engine-space"])

    def test_custom_parser_registry_extension(self) -> None:
        class DemoParser:
            name = "demo-parser"
            version = "1.0"
            extensions = {".xyz": "XLang"}

            def parse(self, path, text, module_name, relative_path, component):
                symbol = SymbolRecord(
                    id=f"{relative_path}:1:{module_name}.hello",
                    qualified_name=f"{module_name}.hello",
                    name="hello",
                    kind="function",
                    path=relative_path,
                    component=component,
                    language="XLang",
                    line_start=1,
                    line_end=1,
                    signature="hello()",
                )
                return ParseResult([ImportMatch("demo.dep", 1, "use demo.dep")], [symbol], [], 1)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "src" / "demo.xyz").write_text("hello", encoding="utf-8")
            registry = ParserRegistry(load_plugins=False)
            registry.register(DemoParser(), source="test")
            report = analyze_repository(
                PreparedSource(root, "plugin-demo", "local", None, None, None),
                history_commits=0,
                parser_registry=registry,
                workers=1,
            )
            record = next(item for item in report.files if item.path.endswith("demo.xyz"))
            self.assertEqual(record.language, "XLang")
            self.assertEqual(record.parser, "demo-parser@1.0")
            self.assertTrue(any(symbol.language == "XLang" and symbol.name == "hello" for symbol in report.symbols))
            self.assertTrue(any(item["name"] == "demo-parser" for item in report.analysis["parser_registry"]["loaded"]))

            class DemoParserV2(DemoParser):
                version = "2.0"

            registry_v2 = ParserRegistry(load_plugins=False)
            registry_v2.register(DemoParserV2(), source="test")
            reparsed = analyze_repository(
                PreparedSource(root, "plugin-demo", "local", None, None, None),
                history_commits=0,
                parser_registry=registry_v2,
                workers=1,
            )
            self.assertEqual(reparsed.analysis["cache"]["hits"], 0)
            self.assertEqual(reparsed.analysis["cache"]["misses"], 1)

    def test_max_files_marks_partial_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_project(root)
            report = analyze_repository(
                PreparedSource(root, "partial", "local", None, None, None),
                history_commits=0,
                max_files=1,
            )
            self.assertTrue(report.project["partial"])
            self.assertTrue(report.analysis["partial"])
            self.assertEqual(report.project["file_count"], 1)

    def test_time_budget_marks_partial_and_forces_sequential_workers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            for number in range(30):
                (root / "src" / f"module_{number}.py").write_text(f"def value(): return {number}\n", encoding="utf-8")
            report = analyze_repository(
                PreparedSource(root, "budget", "local", None, None, None),
                history_commits=0,
                workers=8,
                max_analysis_seconds=0.000001,
            )
            self.assertTrue(report.analysis["partial"])
            self.assertEqual(report.analysis["concurrency"]["workers"], 1)
            self.assertTrue(any("max_analysis_seconds" in warning for warning in report.warnings))

    def test_workspace_diff_detects_package_boundary_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "src" / "module.py").write_text("def run(): pass\n", encoding="utf-8")
            source = PreparedSource(root, "workspace-diff", "local", None, None, None)
            old = analyze_repository(source, history_commits=0).to_dict()
            (root / "package.json").write_text('{"name":"workspace-root"}', encoding="utf-8")
            new = analyze_repository(source, history_commits=0).to_dict()
            diff = compare_reports(old, new)
            self.assertEqual(diff["summary"]["workspaces_added"], 1)
            self.assertEqual(diff["summary"]["workspaces_removed"], 1)

    def test_health_rule_pack_and_compact_search_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_project(root)
            report = analyze_repository(
                PreparedSource(root, "health-demo", "local", None, None, None),
                history_commits=0,
                rule_packs=["strict"],
            )
            health = report.quality["health"]
            self.assertGreaterEqual(health["score"], 0)
            self.assertLessEqual(health["score"], 100)
            self.assertEqual(report.policy["rule_packs"], ["strict"])
            output = root / "report"
            write_outputs(report, output)
            index_payload = json.loads((output / "architecture.index.json").read_text(encoding="utf-8"))
            self.assertEqual(index_payload["schema_version"], "repo-perspector.index/v0.6")
            self.assertTrue(ReportIndex(report.to_dict()).search("service", kind="component"))

    def test_state_snapshots_deduplicate_and_render_trend(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_project(root)
            source = PreparedSource(root, "state-demo", "local", None, "main", "abc123")
            first_report = analyze_repository(source, history_commits=0).to_dict()
            state_dir = root / "state"
            first = record_snapshot(first_report, state_dir, label="baseline", retention=10)
            self.assertTrue(first["recorded"])
            duplicate = record_snapshot(first_report, state_dir, label="same", retention=10)
            self.assertFalse(duplicate["recorded"])
            (root / "src" / "demo" / "models.py").write_text(
                "from .service import load\nclass Item: pass\n", encoding="utf-8"
            )
            second_report = analyze_repository(source, history_commits=0).to_dict()
            second = record_snapshot(second_report, state_dir, label="regression", retention=10)
            self.assertTrue(second["recorded"])
            trend = build_trend(load_state(state_dir))
            self.assertEqual(trend["summary"]["snapshot_count"], 2)
            outputs = write_trend_outputs(trend, root / "trend")
            self.assertTrue(all(path.exists() and path.stat().st_size > 0 for path in outputs.values()))

    def test_state_rejects_mixed_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_project(root)
            state_dir = root / "state"
            first = analyze_repository(PreparedSource(root, "project-a", "local", None, None, None), history_commits=0).to_dict()
            second = analyze_repository(PreparedSource(root, "project-b", "local", None, None, None), history_commits=0).to_dict()
            record_snapshot(first, state_dir)
            with self.assertRaises(ValueError):
                record_snapshot(second, state_dir)

    def test_ci_health_threshold_and_baseline_drop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_project(root)
            source = PreparedSource(root, "health-gate", "local", None, None, None)
            baseline = analyze_repository(source, history_commits=0).to_dict()
            (root / "src" / "demo" / "models.py").write_text(
                "from .service import load\nclass Item: pass\n", encoding="utf-8"
            )
            current = analyze_repository(source, history_commits=0).to_dict()
            result = check_report(current, baseline=baseline, fail_on="none", max_health_drop=1.0)
            self.assertFalse(result["passed"])
            self.assertTrue(result["failed_by_health_drop"])
            floor = check_report(current, fail_on="none", min_health=99.9)
            self.assertFalse(floor["passed"])
            self.assertTrue(floor["failed_by_health"])


if __name__ == "__main__":
    unittest.main()
