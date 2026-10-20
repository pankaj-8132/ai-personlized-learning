"""Prerequisite concept graph builder."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import networkx as nx

from learnloop.config import OUTPUT_DIR
from learnloop.llm import GeminiLLM
from learnloop.schemas import Concept, PrereqEdge

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """\
You are an expert at determining prerequisite relationships between concepts in educational material.

For each pair below, determine if concept A is a prerequisite of concept B (meaning: a student must understand A before they can understand B).

Only return pairs where you are confident there is a real prerequisite relationship.

Concept pairs to judge:
{pairs_json}

For context, here are brief definitions:
{definitions_json}

Return a JSON array of objects, each with:
- "source": concept_id of the prerequisite
- "target": concept_id of the dependent concept
- "confidence": float 0-1 (how confident you are)
- "evidence": short reason why A is prerequisite of B
- "source_pages": pages where this relationship is evidenced

Only include pairs where confidence >= 0.5. If none qualify, return an empty array [].
"""


def _generate_candidate_pairs(
    concepts: list[Concept],
) -> list[tuple[str, str]]:
    """Generate candidate prerequisite pairs from document order and shared sections."""
    pairs: set[tuple[str, str]] = set()
    concept_map = {c.concept_id: c for c in concepts}

    # From document order: earlier concepts might be prerequisites of later ones
    for i, c1 in enumerate(concepts):
        for c2 in concepts[i + 1 : i + 8]:  # window of 7 following concepts
            if c1.concept_id != c2.concept_id:
                pairs.add((c1.concept_id, c2.concept_id))

    # From shared sections: concepts in the same section might be related
    section_concepts: dict[str, list[str]] = {}
    for c in concepts:
        for nid in c.node_ids:
            section_concepts.setdefault(nid, []).append(c.concept_id)

    for nid, cids in section_concepts.items():
        for i, a in enumerate(cids):
            for b in cids[i + 1 :]:
                if a != b:
                    pairs.add((a, b))

    return list(pairs)


def build_prereq_graph(
    concepts: list[Concept],
    doc_id: str,
    llm: GeminiLLM,
) -> tuple[list[PrereqEdge], nx.DiGraph]:
    """Build the prerequisite concept graph."""
    out_dir = OUTPUT_DIR / doc_id
    graph_json_path = out_dir / "prereq_graph.json"
    graph_ml_path = out_dir / "prereq_graph.graphml"

    # Check cache
    if graph_json_path.exists():
        logger.info("Prereq graph already cached at %s", graph_json_path)
        raw = json.loads(graph_json_path.read_text())
        edges = [PrereqEdge.model_validate(e) for e in raw]
        G = _build_nx_graph(concepts, edges)
        return edges, G

    concept_map = {c.concept_id: c for c in concepts}
    candidates = _generate_candidate_pairs(concepts)
    logger.info("Generated %d candidate prerequisite pairs", len(candidates))

    if not candidates:
        logger.warning("No candidate pairs to judge")
        edges: list[PrereqEdge] = []
        G = _build_nx_graph(concepts, edges)
        _save_graph(edges, G, graph_json_path, graph_ml_path)
        return edges, G

    # Build definitions map for context
    definitions = {c.concept_id: f"{c.canonical_name}: {c.definition}" for c in concepts}

    # Judge in batches
    all_edges: list[PrereqEdge] = []
    batch_size = 25
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i : i + batch_size]
        pairs_json = json.dumps([
            {
                "source": concept_map[a].canonical_name,
                "source_id": a,
                "target": concept_map[b].canonical_name,
                "target_id": b,
            }
            for a, b in batch
            if a in concept_map and b in concept_map
        ])
        batch_def_ids = set()
        for a, b in batch:
            batch_def_ids.add(a)
            batch_def_ids.add(b)
        definitions_json = json.dumps({k: definitions[k] for k in batch_def_ids if k in definitions})

        prompt = JUDGE_PROMPT.format(pairs_json=pairs_json, definitions_json=definitions_json)
        try:
            result = llm.generate_json(prompt)
            if isinstance(result, list):
                for item in result:
                    try:
                        edge = PrereqEdge.model_validate(item)
                        all_edges.append(edge)
                    except Exception as e:
                        logger.debug("Skipping invalid edge: %s", e)
        except Exception as e:
            logger.warning("Prereq judging batch failed: %s", e)

    logger.info("LLM judged %d prerequisite edges", len(all_edges))

    # Validate: drop self-loops and unknown concept ids
    valid_ids = set(concept_map.keys())
    all_edges = [
        e for e in all_edges
        if e.source != e.target and e.source in valid_ids and e.target in valid_ids
    ]

    # Build graph and break cycles
    G = _build_nx_graph(concepts, all_edges)
    all_edges = _break_cycles(G, all_edges)

    # Rebuild clean graph
    G = _build_nx_graph(concepts, all_edges)
    _save_graph(all_edges, G, graph_json_path, graph_ml_path)

    logger.info("Final prereq graph: %d nodes, %d edges (DAG: %s)",
                G.number_of_nodes(), G.number_of_edges(), nx.is_directed_acyclic_graph(G))
    return all_edges, G


def _build_nx_graph(concepts: list[Concept], edges: list[PrereqEdge]) -> nx.DiGraph:
    """Build a networkx DiGraph from concepts and edges."""
    G = nx.DiGraph()
    for c in concepts:
        G.add_node(c.concept_id, label=c.canonical_name, definition=c.definition)
    for e in edges:
        G.add_edge(e.source, e.target, confidence=e.confidence,
                   evidence=e.evidence, source_pages=e.source_pages)
    return G


def _break_cycles(G: nx.DiGraph, edges: list[PrereqEdge]) -> list[PrereqEdge]:
    """Detect cycles and break each by removing the lowest-confidence edge."""
    edge_map = {(e.source, e.target): e for e in edges}
    removed = []

    while True:
        try:
            cycle = nx.find_cycle(G, orientation="original")
        except nx.NetworkXNoCycle:
            break

        # Find the weakest edge in this cycle
        cycle_edges = [(u, v) for u, v, _ in cycle]
        weakest = min(cycle_edges, key=lambda uv: edge_map.get(uv, PrereqEdge(source="", target="", confidence=1.0)).confidence)
        G.remove_edge(*weakest)
        if weakest in edge_map:
            removed.append(edge_map.pop(weakest))
            logger.info("Broke cycle by removing edge %s -> %s (confidence=%.2f)",
                        weakest[0], weakest[1], removed[-1].confidence)

    if removed:
        logger.info("Removed %d edges to make DAG", len(removed))

    return [e for e in edges if (e.source, e.target) in edge_map]


def _save_graph(
    edges: list[PrereqEdge],
    G: nx.DiGraph,
    json_path: Path,
    graphml_path: Path,
) -> None:
    """Save graph to JSON and GraphML."""
    json_path.write_text(json.dumps([e.model_dump() for e in edges], indent=2))
    # GraphML needs string attributes
    G_export = G.copy()
    for u, v, data in G_export.edges(data=True):
        data["source_pages"] = json.dumps(data.get("source_pages", []))
    nx.write_graphml(G_export, str(graphml_path))
    logger.info("Saved prereq graph to %s and %s", json_path.name, graphml_path.name)


def prerequisites_of(
    concept_id: str,
    G: nx.DiGraph,
    depth: int = 2,
) -> list[dict]:
    """Get prerequisites of a concept up to a given depth."""
    if concept_id not in G:
        return []

    result = []
    visited = set()
    queue = [(concept_id, 0)]

    while queue:
        current, d = queue.pop(0)
        if d > depth:
            continue
        for pred in G.predecessors(current):
            if pred not in visited:
                visited.add(pred)
                edge_data = G.edges[pred, current]
                result.append({
                    "concept_id": pred,
                    "name": G.nodes[pred].get("label", pred),
                    "depth": d + 1,
                    "confidence": edge_data.get("confidence", 0),
                    "evidence": edge_data.get("evidence", ""),
                })
                if d + 1 < depth:
                    queue.append((pred, d + 1))

    return sorted(result, key=lambda x: (x["depth"], -x["confidence"]))
