"""Declared structure and measured structure are reported side by side.

The previous behaviour picked one: where a project declared MSSP directories the
declaration was reported and the measurements were discarded. That was the right
correction to a real defect — a stability heuristic was wearing MSSP's labels —
but it left the tool answering "it says TMS in the directory name, so it is TMS",
which is the failure Dynamic MSSP is aimed at. Both layers are kept now, and a
disagreement between them is emitted as a governance event.

Severity has to track what the evidence can carry, so these tests assert on the
severity as much as on the event: an import read off the dependency graph is an
ERROR with no confidence field, a role hypothesis built from counts is ADVISORY,
and an ambiguous signal is an OBSERVATION.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from repo_perspector.analyzer import analyze_repository
from repo_perspector.renderers import render_mssp
from repo_perspector.source import PreparedSource


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _events(config: str) -> list[dict[str, str]]:
    block = config[config.index("\ngovernance_events:"):config.index("\narchitecture:")]
    events = []
    for chunk in block.split("  - type: ")[1:]:
        entry = {"type": chunk.split("\n", 1)[0].strip('"')}
        for key in ("rule", "severity", "subject", "confidence", "action"):
            match = re.search(rf'^\s+{key}: "([^"]+)"', chunk, re.M)
            if match:
                entry[key] = match.group(1)
        entry["_raw"] = chunk
        events.append(entry)
    return events


def _render(root: Path, name: str) -> str:
    report = analyze_repository(PreparedSource(root, name, "local", None, None, None), history_commits=0)
    return render_mssp(report)


class TestGovernanceEvents(unittest.TestCase):
    def _breaking_project(self, root: Path) -> None:
        """A project that breaks every rule this file checks, one per directory."""
        _write(root / "src" / "FMS" / "intent.py", "PURPOSE = 'demo'\n")
        _write(root / "src" / "SCL" / "limits.py", "WRITABLE = ()\n")
        _write(root / "src" / "DMS" / "trace.py", "EVENTS = []\n")
        # declared core reaching for declared-optional
        _write(root / "src" / "SMS" / "core.py", "from TMS.logger import log\n\n\ndef run():\n    return log('x')\n")
        # declared core nothing depends on
        _write(root / "src" / "SMS" / "orphan.py", "def unused():\n    return None\n")
        # declared optional depended on more widely than any declared core
        _write(root / "src" / "TMS" / "logger.py", "def log(message):\n    return message\n")
        _write(root / "src" / "TMS" / "exporter.py", "from TMS.logger import log\n\n\ndef export(rows):\n    return log(rows)\n")

    def _clean_project(self, root: Path) -> None:
        _write(root / "src" / "FMS" / "intent.py", "PURPOSE = 'demo'\n")
        _write(root / "src" / "SCL" / "limits.py", "WRITABLE = ()\n")
        _write(root / "src" / "DMS" / "trace.py", "EVENTS = []\n")
        _write(root / "src" / "SMS" / "core.py", "def run():\n    return 1\n")
        _write(root / "src" / "TMS" / "alpha.py", "from SMS.core import run\n\n\ndef alpha():\n    return run()\n")
        _write(root / "src" / "TMS" / "beta.py", "from SMS.core import run\n\n\ndef beta():\n    return run()\n")
        _write(root / "src" / "main.py", "from SMS.core import run\n\n\ndef go():\n    return run()\n")

    def test_every_severity_can_be_reached(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._breaking_project(root)
            events = _events(_render(root, "breaking"))

            severities = {event["severity"] for event in events}
            self.assertEqual(severities, {"ERROR", "ADVISORY", "OBSERVATION"}, [e["type"] for e in events])
            rules = {event.get("rule") for event in events}
            self.assertIn("dependency.sms_to_tms", rules)
            self.assertIn("ROLE_DIVERGENCE", {event["type"] for event in events})
            self.assertIn("DECLARED_ENTITY_UNUSED", {event["type"] for event in events})

    def test_a_project_that_follows_the_rules_produces_no_events(self) -> None:
        """Silence has to mean the checks ran and found nothing.

        Asserting only "no events" would also pass if detection never ran at all,
        so the detection source and the declared sets are asserted alongside it.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._clean_project(root)
            config = _render(root, "clean")

            self.assertIn('source: "declared"', config)
            self.assertIn('declared_sets: ["FMS", "SCL", "SMS", "TMS", "DMS"]', config)
            self.assertEqual(_events(config), [])

    def test_a_deterministic_violation_carries_no_confidence(self) -> None:
        """An import is in the graph or it is not.

        Printing `confidence: high` next to a fact would spend the word where it
        costs nothing, and it is needed two events further down, on a hypothesis.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._breaking_project(root)
            events = _events(_render(root, "breaking"))

            for event in events:
                if event["severity"] == "ERROR":
                    self.assertNotIn("confidence", event, event["type"])
                else:
                    self.assertIn("confidence", event, event["type"])

    def test_a_role_divergence_never_rewrites_the_declared_role(self) -> None:
        """The tool reports; it does not decide. The declared role stands."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._breaking_project(root)
            config = _render(root, "breaking")

            divergent = [e for e in _events(config) if e["type"] == "ROLE_DIVERGENCE"]
            self.assertTrue(divergent, "expected the depended-upon TMS to diverge")
            for event in divergent:
                self.assertEqual(event["declared" if "declared" in event else "action"], "ROLE_REVIEW_REQUIRED")
                self.assertIn("not a reclassification", event["_raw"])
                # the subject is still published under the set it declares
                block = re.search(r"^  TMS:\n((?:    .*\n)*)", config, re.M)
                self.assertIn(event["subject"], block.group(1))

    def test_the_measurements_are_kept_next_to_the_declared_role(self) -> None:
        """The observed layer has to be on the page, not just consulted.

        Every event above is derived from these numbers, so a reader who
        disagrees with an event needs to see what it was derived from. Deleting
        the observed block left all the other tests passing — they assert on
        events, and events survive without ever being shown their inputs.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._breaking_project(root)
            config = _render(root, "breaking")

            self.assertGreaterEqual(config.count("observed:"), 4)
            for field in ("dependents", "depends_on", "centrality", "instability", "churn"):
                self.assertIn(f"        {field}: ", config, field)

            # Declared and observed are both present for the same module, and the
            # declared one is unchanged by what was measured.
            core = re.search(r'^    - module: "src/SMS/core"\n((?:      .*\n)*)', config, re.M)
            self.assertIsNotNone(core, "expected src/SMS/core under its declared set")
            self.assertIn("observed:", core.group(1))
            self.assertIn('role: "core"', core.group(1))

    def test_sibling_units_inside_one_component_are_still_checked(self) -> None:
        """The granularity the dependency graph cannot see.

        graph_builder keeps only edges where target != source, and a directory
        one level below a set collapses into a single component. Two units inside
        `TMS/reporters/` importing each other therefore produce no graph edge at
        all — the rule has to be recovered from the file records instead.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._clean_project(root)
            _write(root / "src" / "TMS" / "reporters" / "text.py", "def render(rows):\n    return str(rows)\n")
            _write(
                root / "src" / "TMS" / "reporters" / "json.py",
                "from .text import render\n\n\ndef dump(rows):\n    return render(rows)\n",
            )
            report = analyze_repository(PreparedSource(root, "nested", "local", None, None, None), history_commits=0)

            # Precondition: the two units really are one component, and the graph
            # really has no edge between them. Without this the test could pass
            # for the wrong reason.
            components = {c.path for c in report.components}
            self.assertIn("src/TMS/reporters", components)
            self.assertNotIn("src/TMS/reporters/json", components)
            self.assertEqual(
                [d for d in report.dependencies if d.source == "src/TMS/reporters" and d.target == "src/TMS/reporters"],
                [],
            )

            sibling = [
                event for event in _events(render_mssp(report))
                if event.get("rule") == "dependency.tms_to_tms"
            ]
            self.assertTrue(sibling, "sibling import inside one component went unreported")
            self.assertEqual(sibling[0]["severity"], "ERROR")


if __name__ == "__main__":
    unittest.main()
