from __future__ import annotations

from collections import deque
from typing import Iterable

from .models import Component


def _transitive_dependents(start: str, reverse_edges: dict[str, set[str]]) -> tuple[list[str], dict[str, int]]:
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    visited = {start}
    distances: dict[str, int] = {}
    while queue:
        node, depth = queue.popleft()
        for dependent in sorted(reverse_edges.get(node, set())):
            if dependent in visited:
                continue
            visited.add(dependent)
            distances[dependent] = depth + 1
            queue.append((dependent, depth + 1))
    return sorted(distances, key=lambda name: (distances[name], name)), distances


def apply_impact_analysis(components: list[Component], cycles: Iterable[Iterable[str]]) -> None:
    """Attach change blast-radius and explainable risk estimates to components."""
    by_name = {component.path: component for component in components}
    reverse_edges: dict[str, set[str]] = {name: set() for name in by_name}
    for component in components:
        for target in component.internal_dependencies:
            if target in reverse_edges:
                reverse_edges[target].add(component.path)

    cycle_nodes = {node for cycle in cycles for node in cycle}
    denominator = max(1, len(components) - 1)
    for component in components:
        transitive, distances = _transitive_dependents(component.path, reverse_edges)
        blast_radius = len(transitive) / denominator
        volatility = float(component.history.get("normalized_churn", 0.0) or 0.0)
        core_bonus = 1.0 if component.stability == "core" else 0.0
        cycle_bonus = 1.0 if component.path in cycle_nodes else 0.0
        risk_score = min(
            1.0,
            0.45 * blast_radius
            + 0.20 * component.centrality
            + 0.15 * volatility
            + 0.10 * cycle_bonus
            + 0.10 * core_bonus,
        )
        if risk_score >= 0.70:
            tier = "critical"
        elif risk_score >= 0.45:
            tier = "high"
        elif risk_score >= 0.20:
            tier = "medium"
        else:
            tier = "low"
        component.impact = {
            "direct_dependents": sorted(reverse_edges.get(component.path, set())),
            "transitive_dependents": transitive,
            "distance_by_component": distances,
            "blast_radius": round(blast_radius, 4),
            "risk_score": round(risk_score, 4),
            "risk_tier": tier,
            "cycle_member": component.path in cycle_nodes,
            "reason": [
                f"transitive dependents: {len(transitive)}/{denominator}",
                f"structural centrality: {component.centrality:.4f}",
                f"normalized Git churn: {volatility:.4f}",
                f"cycle member: {component.path in cycle_nodes}",
                f"classified core: {component.stability == 'core'}",
            ],
        }
