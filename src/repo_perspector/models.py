from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class FileRecord:
    path: str
    language: str
    size: int
    component: str
    line_count: int = 0
    complexity: int = 0
    imports: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    parse_error: str | None = None
    workspace: str = "repository"
    parser: str = "unsupported"
    generated: bool = False


@dataclass(slots=True)
class Dependency:
    source: str
    target: str
    evidence: list[str] = field(default_factory=list)
    count: int = 1
    kind: str = "static_import"


@dataclass(slots=True)
class SymbolRecord:
    id: str
    qualified_name: str
    name: str
    kind: str
    path: str
    component: str
    language: str
    line_start: int
    line_end: int
    signature: str = ""
    visibility: str = "public"
    parent: str | None = None
    complexity: int = 1
    docstring: str | None = None


@dataclass(slots=True)
class SymbolRelationship:
    source: str
    target: str
    kind: str
    evidence: list[str] = field(default_factory=list)
    count: int = 1


@dataclass(slots=True)
class Finding:
    rule_id: str
    severity: str
    title: str
    message: str
    component: str | None = None
    path: str | None = None
    line: int | None = None
    evidence: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Component:
    id: str
    path: str
    name: str
    role: str
    description: str
    stability: str
    classification_reason: list[str]
    files: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    incoming: int = 0
    outgoing: int = 0
    centrality: float = 0.0
    internal_dependencies: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)
    history: dict[str, Any] = field(default_factory=dict)
    impact: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ArchitectureReport:
    schema_version: str
    generated_at: str
    project: dict[str, Any]
    analysis: dict[str, Any]
    evidence: dict[str, Any]
    history: dict[str, Any]
    architecture: dict[str, Any]
    quality: dict[str, Any]
    policy: dict[str, Any]
    files: list[FileRecord]
    components: list[Component]
    dependencies: list[Dependency]
    symbols: list[SymbolRecord]
    symbol_relationships: list[SymbolRelationship]
    findings: list[Finding]
    cycles: list[list[str]]
    workspaces: list[dict[str, Any]]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
