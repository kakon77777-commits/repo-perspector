from __future__ import annotations

import json
import re
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility
    tomllib = None  # type: ignore[assignment]
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


MANIFEST_ECOSYSTEM = {
    "package.json": "node",
    "pyproject.toml": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "pom.xml": "java-maven",
    "build.gradle": "java-gradle",
    "build.gradle.kts": "kotlin-gradle",
}


@dataclass(slots=True)
class Workspace:
    id: str
    path: str
    name: str
    ecosystem: str
    manifest: str
    files: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)


def _package_name(path: Path, ecosystem: str) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if ecosystem == "node":
            value = json.loads(text).get("name")
            return str(value) if value else None
        if ecosystem == "python":
            if tomllib is not None:
                data = tomllib.loads(text)
                value = data.get("project", {}).get("name") or data.get("tool", {}).get("poetry", {}).get("name")
                return str(value) if value else None
            match = re.search(r"""^\s*name\s*=\s*['"]([^'"]+)['"]""", text, re.MULTILINE)
            return match.group(1) if match else None
        if ecosystem == "rust":
            if tomllib is not None:
                value = tomllib.loads(text).get("package", {}).get("name")
                return str(value) if value else None
            package = re.search(r"^\s*\[package\]\s*$([\s\S]*?)(?=^\s*\[|\Z)", text, re.MULTILINE)
            match = re.search(r"""^\s*name\s*=\s*['"]([^'"]+)['"]""", package.group(1), re.MULTILINE) if package else None
            return match.group(1) if match else None
        if ecosystem == "go":
            match = re.search(r"^module\s+([^\s]+)", text, re.MULTILINE)
            return match.group(1) if match else None
        if ecosystem == "java-maven":
            match = re.search(r"<artifactId>\s*([^<]+)\s*</artifactId>", text)
            return match.group(1).strip() if match else None
        if ecosystem.endswith("gradle"):
            match = re.search(r"(?:rootProject\.name\s*=|archivesBaseName\s*=)\s*['\"]([^'\"]+)", text)
            return match.group(1) if match else None
    except (OSError, ValueError, TypeError):
        return None
    return None


def discover_workspaces(root: Path, paths: Iterable[Path]) -> list[Workspace]:
    root = root.resolve()
    candidates: dict[Path, tuple[Path, str]] = {}
    for relative in paths:
        if relative.name not in MANIFEST_ECOSYSTEM:
            continue
        manifest = root / relative
        directory = manifest.parent
        ecosystem = MANIFEST_ECOSYSTEM[relative.name]
        # Prefer the strongest package manifest when several live together.
        current = candidates.get(directory)
        priority = {"node": 7, "python": 6, "rust": 5, "go": 4, "java-maven": 3, "java-gradle": 2, "kotlin-gradle": 1}
        if current is None or priority[ecosystem] > priority[current[1]]:
            candidates[directory] = (manifest, ecosystem)

    if not candidates:
        return [Workspace("repository", ".", root.name, "generic", "")]

    workspaces: list[Workspace] = []
    if root not in candidates:
        workspaces.append(Workspace("repository", ".", root.name, "generic", ""))
    for directory, (manifest, ecosystem) in sorted(candidates.items(), key=lambda item: (len(item[0].parts), str(item[0]))):
        relative_dir = directory.relative_to(root).as_posix() if directory != root else "."
        relative_manifest = manifest.relative_to(root).as_posix()
        name = _package_name(manifest, ecosystem) or (directory.name if directory != root else root.name)
        identifier = relative_dir if relative_dir != "." else "repository"
        workspaces.append(Workspace(identifier, relative_dir, name, ecosystem, relative_manifest))
    return workspaces


def workspace_for(relative: Path, workspaces: list[Workspace]) -> Workspace:
    path = relative.as_posix()
    matches: list[Workspace] = []
    for workspace in workspaces:
        if workspace.path == "." or path == workspace.path or path.startswith(workspace.path.rstrip("/") + "/"):
            matches.append(workspace)
    return max(matches, key=lambda item: len(Path(item.path).parts)) if matches else workspaces[0]


def finalize_workspaces(
    workspaces: list[Workspace],
    file_workspace: dict[str, str],
    file_component: dict[str, str],
    file_language: dict[str, str],
) -> list[Workspace]:
    by_id = {workspace.id: workspace for workspace in workspaces}
    files: dict[str, list[str]] = defaultdict(list)
    components: dict[str, set[str]] = defaultdict(set)
    languages: dict[str, Counter[str]] = defaultdict(Counter)
    for path, workspace_id in file_workspace.items():
        if workspace_id not in by_id:
            continue
        files[workspace_id].append(path)
        components[workspace_id].add(file_component[path])
        languages[workspace_id][file_language[path]] += 1
    for workspace in workspaces:
        workspace.files = sorted(files[workspace.id])
        workspace.components = sorted(components[workspace.id])
        workspace.languages = dict(sorted(languages[workspace.id].items(), key=lambda item: (-item[1], item[0])))
    return workspaces
