"""Concept extraction and synonym normalization."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from learnloop.config import OUTPUT_DIR
from learnloop.llm import GeminiLLM
from learnloop.schemas import Concept, RawConcept, TreeNode

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """\
You are a concept-extraction expert for educational materials.

Given the following section from a textbook, extract ALL key concepts.
For each concept return:
- "name": the primary name
- "aliases": list of alternative names, abbreviations, or synonyms
- "definition": a one-line definition
- "pages": list of page numbers where this concept appears (from the metadata)

Section title: {title}
Page: {page}

Text:
{text}

Return a JSON array of objects. Example:
[{{"name": "Binary Search Tree", "aliases": ["BST", "binary search tree"], "definition": "A sorted binary tree enabling O(log n) search", "pages": [12]}}]
"""

MERGE_PROMPT = """\
You are a synonym-resolution expert. Below is a list of concept names extracted from different sections of the same document. Many are synonyms, abbreviations, or alternate spellings of the same concept.

Group them into canonical concepts. For each group return:
- "canonical": the best full-form name (prefer the most descriptive, expanded form)
- "members": list of all names that refer to this concept

Concept names:
{names_json}

Return a JSON array. Example:
[{{"canonical": "binary search tree", "members": ["BST", "binary search tree", "Binary Search Tree"]}}]
"""


def _slugify(name: str) -> str:
    """Convert name to a clean concept_id slug."""
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


def _collect_leaves(nodes: list[TreeNode]) -> list[TreeNode]:
    """Recursively collect leaf nodes (those with text but no children)."""
    leaves: list[TreeNode] = []
    for node in nodes:
        if node.nodes:
            leaves.extend(_collect_leaves(node.nodes))
        else:
            if node.text:
                leaves.append(node)
    return leaves


def _collect_all_nodes_with_text(nodes: list[TreeNode]) -> list[TreeNode]:
    """Recursively collect all nodes that have text content."""
    result: list[TreeNode] = []
    for node in nodes:
        if node.text:
            result.append(node)
        if node.nodes:
            result.extend(_collect_all_nodes_with_text(node.nodes))
    return result


def extract_and_normalize(
    tree: list[TreeNode],
    doc_id: str,
    llm: GeminiLLM,
) -> list[Concept]:
    """Full pipeline: extract concepts from leaves, merge synonyms, output concepts.json."""
    out_dir = OUTPUT_DIR / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    concepts_path = out_dir / "concepts.json"

    # Check cache
    if concepts_path.exists():
        logger.info("Concepts already cached at %s", concepts_path)
        raw = json.loads(concepts_path.read_text())
        return [Concept.model_validate(c) for c in raw]

    # Step 1: Extract raw concepts from each text-bearing node
    text_nodes = _collect_all_nodes_with_text(tree)
    if not text_nodes:
        text_nodes = _collect_leaves(tree)
    logger.info("Extracting concepts from %d text-bearing nodes...", len(text_nodes))

    all_raw: list[tuple[str, RawConcept]] = []  # (node_id, concept)
    for node in text_nodes:
        text = (node.text or "")[:3000]  # cap to keep prompt small
        if len(text.strip()) < 20:
            continue
        prompt = EXTRACT_PROMPT.format(
            title=node.title,
            page=node.page_index or 0,
            text=text,
        )
        try:
            concepts_raw = llm.generate_json(
                prompt, schema=RawConcept, list_mode=True,
            )
            for c in concepts_raw:
                all_raw.append((node.node_id, c))
        except Exception as e:
            logger.warning("Concept extraction failed for node %s: %s", node.node_id, e)

    if not all_raw:
        logger.warning("No concepts extracted")
        return []

    logger.info("Extracted %d raw concepts from %d nodes", len(all_raw), len(text_nodes))

    # Step 2: Cross-section synonym merge via LLM
    unique_names = sorted({c.name for _, c in all_raw})
    # Batch names to keep prompt small
    batch_size = 80
    merge_groups: list[dict] = []
    for i in range(0, len(unique_names), batch_size):
        batch = unique_names[i : i + batch_size]
        prompt = MERGE_PROMPT.format(names_json=json.dumps(batch))
        try:
            groups = llm.generate_json(prompt)
            if isinstance(groups, list):
                merge_groups.extend(groups)
        except Exception as e:
            logger.warning("Synonym merge batch failed: %s", e)

    # Build name -> canonical mapping
    name_to_canonical: dict[str, str] = {}
    for group in merge_groups:
        canonical = group.get("canonical", "").lower().strip()
        for member in group.get("members", []):
            name_to_canonical[member.lower().strip()] = canonical

    # Step 3: Deterministic cleanup + build final concepts
    concept_map: dict[str, Concept] = {}
    for node_id, raw in all_raw:
        raw_name = raw.name.lower().strip()
        canonical = name_to_canonical.get(raw_name, raw_name)
        canonical = re.sub(r"[^\w\s-]", "", canonical).strip()
        cid = _slugify(canonical)
        if not cid:
            continue

        if cid not in concept_map:
            concept_map[cid] = Concept(
                concept_id=cid,
                canonical_name=canonical,
                aliases=[],
                definition=raw.definition,
                node_ids=[],
                pages=[],
            )

        c = concept_map[cid]
        if node_id not in c.node_ids:
            c.node_ids.append(node_id)
        # Merge aliases
        all_names = {raw.name.lower().strip()} | {a.lower().strip() for a in raw.aliases}
        for alias in all_names:
            if alias != c.canonical_name and alias not in c.aliases:
                c.aliases.append(alias)
        # Merge pages
        for p in raw.pages:
            if p not in c.pages:
                c.pages.append(p)

    concepts = sorted(concept_map.values(), key=lambda c: c.concept_id)
    logger.info("Final concepts: %d (after merging)", len(concepts))

    # Save
    concepts_path.write_text(
        json.dumps([c.model_dump() for c in concepts], indent=2)
    )
    return concepts
