"""MSSP set membership must be read from the repository, not inferred over it.

Before this, render_mssp mapped `stability in {core, stable}` to SMS and
`{evolving, experimental}` to TMS. That is a stability classification wearing
MSSP's labels: a project that declares src/TMS/ had its TMS modules reported as
SMS whenever they scored high on centrality, and FMS, SCL and DMS were never
emitted at all.
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


def _sections(config: str) -> list[str]:
    return [name for name in ("FMS", "SCL", "SMS", "TMS", "DMS") if f"\n  {name}:" in config]


def _detection(config: str) -> str:
    match = re.search(r'^  source: "(\w+)"', config, re.M)
    return match.group(1) if match else ""


def _module_names_under(config: str, section: str) -> list[str]:
    block = re.search(rf"^  {section}:\n((?:    .*\n)*)", config, re.M)
    if not block:
        return []
    return re.findall(r'(?:module|subset): "([^"]+)"', block.group(1))


class TestDeclaredMsspDetection(unittest.TestCase):
    def _mssp_project(self, root: Path) -> None:
        """A project where a declared TMS is also depended upon.

        That is the shape the old mapping got wrong in the wild: high centrality
        pushed a TMS into `core`, and `core` was reported as SMS. `TMS/alpha` is
        imported by the entry point here so it scores as central rather than as
        a leaf — without that, the defect happens to land on FMS/SCL/DMS instead
        and a TMS-only assertion sails past it.
        """
        _write(root / "src" / "FMS" / "manifest.py", "MANIFEST = {'name': 'demo'}\n")
        _write(root / "src" / "SCL" / "permissions.py", "def permits(task):\n    return True\n")
        _write(root / "src" / "SMS" / "model.py", "class Result:\n    pass\n")
        _write(root / "src" / "TMS" / "alpha.py", "from ..SMS.model import Result\n\ndef alpha():\n    return Result()\n")
        _write(root / "src" / "TMS" / "beta.py", "from ..SMS.model import Result\nfrom .alpha import alpha\n\ndef beta():\n    return alpha()\n")
        _write(root / "src" / "DMS" / "trace.py", "EVENTS = []\n")
        _write(root / "src" / "main.py", "from .TMS.alpha import alpha\nfrom .TMS.beta import beta\nfrom .DMS.trace import EVENTS\n\ndef run():\n    return alpha(), beta(), EVENTS\n")

    def _plain_project(self, root: Path) -> None:
        _write(root / "src" / "demo" / "models.py", "class Item:\n    pass\n")
        _write(root / "src" / "demo" / "service.py", "from .models import Item\n\ndef load():\n    return Item()\n")

    def test_declared_sets_are_read_not_inferred(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._mssp_project(root)
            report = analyze_repository(PreparedSource(root, "mssp-demo", "local", None, None, None), history_commits=0)
            config = render_mssp(report)

            self.assertEqual(_detection(config), "declared")
            # All five sets appear, not only SMS and TMS.
            self.assertEqual(_sections(config), ["FMS", "SCL", "SMS", "TMS", "DMS"])

    def test_no_module_is_reported_under_a_set_it_does_not_declare(self) -> None:
        """The invariant, across all five sets rather than just SMS and TMS.

        Checking only the SMS/TMS pair is not enough: with the fix removed, this
        project's FMS, SCL and DMS modules are all classified `stable` and land
        under SMS, while its TMS modules happen to land correctly. A two-set
        assertion passes on that and reports a guard that cannot fail.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._mssp_project(root)
            report = analyze_repository(PreparedSource(root, "mssp-demo", "local", None, None, None), history_commits=0)
            config = render_mssp(report)

            misplaced = []
            for section in ("FMS", "SCL", "SMS", "TMS", "DMS"):
                for module in _module_names_under(config, section):
                    segments = module.replace("\\", "/").split("/")
                    declared = next((name for name in ("FMS", "SCL", "SMS", "TMS", "DMS") if name in segments), None)
                    if declared and declared != section:
                        misplaced.append(f"{module} declares {declared} but was reported under {section}")

            self.assertTrue(_module_names_under(config, "SMS"), "SMS section should not be empty")
            self.assertTrue(_module_names_under(config, "TMS"), "TMS section should not be empty")
            self.assertEqual(misplaced, [], "; ".join(misplaced))

    def test_a_project_without_mssp_directories_falls_back_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._plain_project(root)
            report = analyze_repository(PreparedSource(root, "plain-demo", "local", None, None, None), history_commits=0)
            config = render_mssp(report)

            self.assertEqual(_detection(config), "inferred")
            self.assertIn("not declared by the project", config)
            # Sets the project never declared must not be invented for it.
            self.assertNotIn("\n  FMS:", config)
            self.assertNotIn("\n  SCL:", config)
            self.assertNotIn("\n  DMS:", config)

    def test_one_matching_directory_is_not_enough_to_claim_a_structure(self) -> None:
        """A lone directory named DMS could be anything — a data management
        service, an initialism that happens to collide. Two is a structure."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._plain_project(root)
            _write(root / "src" / "DMS" / "client.py", "TOKEN = 'x'\n")
            report = analyze_repository(PreparedSource(root, "collide-demo", "local", None, None, None), history_commits=0)
            config = render_mssp(report)
            self.assertEqual(_detection(config), "inferred")


if __name__ == "__main__":
    unittest.main()
