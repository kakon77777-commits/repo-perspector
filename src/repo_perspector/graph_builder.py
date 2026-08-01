from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from .heuristics import infer_role, infer_stability
from .impact import apply_impact_analysis
from .inventory import InventoryResult
from .models import Component, Dependency
from .symbols import resolve_symbol_relationships


def _resolve_relative_js(
    source_path: Path,
    import_value: str,
    root: Path,
    file_component: dict[str, str],
) -> str | None:
    if not import_value.startswith("."):
        return None
    base = (source_path.parent / import_value).resolve()
    candidates = [
        base,
        *[base.with_suffix(ext) for ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")],
        *[(base / f"index{ext}") for ext in (".js", ".jsx", ".ts", ".tsx")],
    ]
    for candidate in candidates:
        try:
            relative = candidate.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        if relative in file_component:
            return file_component[relative]
    return None


def _longest_prefix_component(import_name: str, module_component: dict[str, str]) -> str | None:
    candidate = import_name.replace("/", ".").replace("::", ".").strip(".")
    while candidate:
        if candidate in module_component:
            return module_component[candidate]
        candidate = candidate.rsplit(".", 1)[0] if "." in candidate else ""
    return None


def detect_cycles(nodes: set[str], edges: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    cycles: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in edges.get(node, set()):
            if target not in indices:
                strongconnect(target)
                lowlink[node] = min(lowlink[node], lowlink[target])
            elif target in on_stack:
                lowlink[node] = min(lowlink[node], indices[target])
        if lowlink[node] == indices[node]:
            group: list[str] = []
            while stack:
                member = stack.pop()
                on_stack.remove(member)
                group.append(member)
                if member == node:
                    break
            if len(group) > 1 or (len(group) == 1 and group[0] in edges.get(group[0], set())):
                cycles.append(sorted(group))

    for node in sorted(nodes):
        if node not in indices:
            strongconnect(node)
    return sorted(cycles, key=lambda group: (-len(group), group))


def build_dependency_graph(
    root: Path,
    inventory: InventoryResult,
    component_history: dict[str, dict[str, object]],
) -> tuple[list[Dependency], list[Component], list[list[str]], list[object]]:
    dep_evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
    for record in inventory.records:
        source_component = record.component
        source_path = root / Path(record.path)
        for imported in inventory.import_matches_by_file.get(record.path, []):
            target_component: str | None = None
            if record.language in {"JavaScript", "TypeScript", "Vue", "Svelte"}:
                target_component = _resolve_relative_js(source_path, imported.value, root, inventory.file_component)
            if target_component is None:
                target_component = _longest_prefix_component(imported.value, inventory.module_component)
            if target_component and target_component != source_component:
                key = (source_component, target_component)
                evidence = f"{record.path}:{imported.line}: {imported.excerpt or ('import ' + imported.value)}"
                if evidence not in dep_evidence[key] and len(dep_evidence[key]) < 20:
                    dep_evidence[key].append(evidence)

    dependencies = [
        Dependency(source=source, target=target, evidence=evidence, count=len(evidence))
        for (source, target), evidence in sorted(dep_evidence.items())
    ]
    symbol_relationships = resolve_symbol_relationships(inventory.symbols, inventory.raw_calls)

    component_files: dict[str, list[object]] = defaultdict(list)
    for record in inventory.records:
        component_files[record.component].append(record)
    incoming_counter: Counter[str] = Counter()
    outgoing_counter: Counter[str] = Counter()
    edges: dict[str, set[str]] = defaultdict(set)
    for dependency in dependencies:
        outgoing_counter[dependency.source] += dependency.count
        incoming_counter[dependency.target] += dependency.count
        edges[dependency.source].add(dependency.target)

    max_incoming = max(incoming_counter.values(), default=0)
    max_degree = max(1, max(
        (incoming_counter[name] + outgoing_counter[name] for name in component_files),
        default=0,
    ))
    components: list[Component] = []
    for name, files in sorted(component_files.items()):
        role, description, role_reasons = infer_role(name)
        incoming = incoming_counter[name]
        outgoing = outgoing_counter[name]
        history_metrics = dict(component_history.get(name, {}))
        stability, stability_reasons = infer_stability(
            name,
            incoming,
            outgoing,
            max_incoming,
            history_metrics,
        )
        languages = Counter(record.language for record in files)
        components.append(Component(
            id=name.replace("/", "__").replace(".", "_"),
            path=name,
            name=PurePosixPath(name).name,
            role=role,
            description=description,
            stability=stability,
            classification_reason=[*role_reasons, *stability_reasons],
            files=[record.path for record in files],
            languages=dict(sorted(languages.items(), key=lambda item: (-item[1], item[0]))),
            incoming=incoming,
            outgoing=outgoing,
            centrality=round((incoming + outgoing) / max_degree, 4),
            internal_dependencies=sorted(edges.get(name, set())),
            dependents=sorted(source for source, targets in edges.items() if name in targets),
            history=history_metrics,
        ))

    cycles = detect_cycles(set(component_files), edges)
    apply_impact_analysis(components, cycles)
    return dependencies, components, cycles, symbol_relationships
