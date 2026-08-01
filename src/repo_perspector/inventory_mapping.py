from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .heuristics import SOURCE_ROOT_NAMES
from .parser_plugins import ParserRegistry
from .parsers import module_name_for
from .workspaces import Workspace, discover_workspaces, workspace_for

CONFIG_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile",
    "package.json", "tsconfig.json", "pnpm-workspace.yaml", "yarn.lock",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Makefile",
    ".github/workflows", "README.md", "README.rst", "LICENSE", "LICENSE.md",
    ".perspector.yml", ".perspector.yaml", ".perspector.json", ".perspectorignore",
}
NON_CODE_LANGUAGES = {"Other", "Markdown", "JSON", "YAML", "TOML", "HTML", "CSS", "SCSS", "SQL"}


@dataclass(slots=True)
class MappingResult:
    source_roots: list[Path]
    workspaces: list[Workspace]
    file_component: dict[str, str]
    file_workspace: dict[str, str]
    file_language: dict[str, str]
    module_component: dict[str, str]
    module_name_by_file: dict[str, str]
    config_files: list[str]
    sizes: dict[str, int]
    parse_candidates: list[Path]


def component_for(relative: Path, language: str) -> str:
    parts = list(relative.parts)
    if not parts:
        return "repository"
    first = parts[0]
    stem = relative.stem
    if first in {"tests", "test", "docs", "examples", "scripts", "tools", ".github"}:
        return first
    if first in SOURCE_ROOT_NAMES and len(parts) >= 2:
        if len(parts) == 2:
            return f"{first}/{stem}"
        package = parts[1]
        if len(parts) == 3 and relative.suffix:
            return f"{first}/{package}/{stem}"
        return f"{first}/{package}/{parts[2]}"
    if len(parts) == 1:
        return stem if language not in NON_CODE_LANGUAGES else "repository"
    if len(parts) == 2 and relative.suffix:
        return f"{first}/{stem}"
    return "/".join(parts[:2])


def build_mapping(root: Path, paths: list[Path], registry: ParserRegistry) -> MappingResult:
    workspaces = discover_workspaces(root, paths)
    source_roots = [root]
    for workspace in workspaces:
        workspace_root = root if workspace.path == "." else root / workspace.path
        for name in SOURCE_ROOT_NAMES:
            candidate = workspace_root / name
            if candidate.is_dir() and candidate not in source_roots:
                source_roots.append(candidate)
    source_roots.sort(key=lambda path: (len(path.parts), str(path)))

    file_component: dict[str, str] = {}
    file_workspace: dict[str, str] = {}
    file_language: dict[str, str] = {}
    module_component: dict[str, str] = {}
    module_name_by_file: dict[str, str] = {}
    config_files: list[str] = []
    sizes: dict[str, int] = {}
    parse_candidates: list[Path] = []

    for relative in paths:
        absolute = root / relative
        rel_string = relative.as_posix()
        language = registry.language_for(absolute)
        component = component_for(relative, language)
        workspace = workspace_for(relative, workspaces)
        module_name = module_name_for(absolute, root, source_roots)
        file_component[rel_string] = component
        file_workspace[rel_string] = workspace.id
        file_language[rel_string] = language
        module_name_by_file[rel_string] = module_name
        if module_name:
            module_component[module_name] = component
        if relative.name in CONFIG_NAMES or rel_string.startswith(".github/workflows/"):
            config_files.append(rel_string)
        try:
            sizes[rel_string] = absolute.stat().st_size
        except OSError:
            sizes[rel_string] = 0
        if registry.supports(absolute) and language not in NON_CODE_LANGUAGES:
            parse_candidates.append(relative)

    return MappingResult(
        source_roots=source_roots,
        workspaces=workspaces,
        file_component=file_component,
        file_workspace=file_workspace,
        file_language=file_language,
        module_component=module_component,
        module_name_by_file=module_name_by_file,
        config_files=sorted(config_files),
        sizes=sizes,
        parse_candidates=parse_candidates,
    )
