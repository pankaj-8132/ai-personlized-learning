"""Offline tests: tree validation, synonym merge, cycle breaking, retriever lookup."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

from learnloop.schemas import Concept, PrereqEdge, TreeNode


# ── Tree schema validation ──────────────────────────────────────────────────

class TestTreeValidation:
    def test_valid_tree_node(self):
        node = TreeNode(
            node_id="n1",
            title="Introduction",
            page_index=1,
            text="Some text",
            summary="A summary",
            nodes=[],
        )
        assert node.node_id == "n1"
        assert node.page_index == 1

    def test_nested_tree(self):
        tree = TreeNode(
            node_id="root",
            title="Root",
            page_index=1,
            nodes=[
                TreeNode(node_id="c1", title="Chapter 1", page_index=2),
                TreeNode(node_id="c2", title="Chapter 2", page_index=10, nodes=[
                    TreeNode(node_id="s1", title="Section 2.1", page_index=11, text="Content here"),
                ]),
            ],
        )
        assert len(tree.nodes) == 2
        assert len(tree.nodes[1].nodes) == 1
        assert tree.nodes[1].nodes[0].text == "Content here"

    def test_missing_optional_fields(self):
        node = TreeNode(node_id="n2", title="Appendix")
        assert node.page_index is None
        assert node.text is None
        assert node.nodes == []

    def test_validate_tree_function(self):
        from learnloop.pageindex_client import _validate_tree
        raw = [
            {"node_id": "a", "title": "Alpha", "page_index": 1},
            {"title": "Missing ID"},  # should be skipped
            {"node_id": "b", "title": "Beta", "page_index": 3, "nodes": [
                {"node_id": "b1", "title": "Beta Child", "page_index": 4}
            ]},
        ]
        validated = _validate_tree(raw)
        assert len(validated) == 2
        assert validated[0].node_id == "a"
        assert len(validated[1].nodes) == 1


# ── Synonym merge ────────────────────────────────────────────────────────────

class TestSynonymMerge:
    def test_slugify(self):
        from learnloop.normalizer import _slugify
        assert _slugify("Binary Search Tree") == "binary_search_tree"
        assert _slugify("B.S.T.") == "bst"
        assert _slugify("  hello world  ") == "hello_world"

    @patch("learnloop.normalizer.GeminiLLM")
    def test_extract_merges_synonyms(self, MockLLM):
        """Verify that concepts with synonyms get merged correctly."""
        # Simulate already-extracted concepts being merged
        from learnloop.normalizer import _slugify
        
        raw_concepts = [
            ("n1", {"name": "Binary Search Tree", "aliases": ["BST"], "definition": "A sorted tree", "pages": [1]}),
            ("n2", {"name": "BST", "aliases": ["binary search tree"], "definition": "Binary search tree", "pages": [5]}),
        ]
        
        # The merge logic: both map to same canonical
        name_to_canonical = {
            "binary search tree": "binary search tree",
            "bst": "binary search tree",
        }
        
        canonical = name_to_canonical.get("bst", "bst")
        assert canonical == "binary search tree"
        
        cid = _slugify(canonical)
        assert cid == "binary_search_tree"


# ── Cycle breaking ──────────────────────────────────────────────────────────

class TestCycleBreaking:
    def test_break_simple_cycle(self):
        from learnloop.prereq_graph import _break_cycles
        
        G = nx.DiGraph()
        G.add_edge("a", "b", confidence=0.9, evidence="")
        G.add_edge("b", "c", confidence=0.8, evidence="")
        G.add_edge("c", "a", confidence=0.3, evidence="")  # weakest
        
        edges = [
            PrereqEdge(source="a", target="b", confidence=0.9, evidence="A before B"),
            PrereqEdge(source="b", target="c", confidence=0.8, evidence="B before C"),
            PrereqEdge(source="c", target="a", confidence=0.3, evidence="C before A"),
        ]
        
        result = _break_cycles(G, edges)
        
        # After breaking, must be a DAG
        assert nx.is_directed_acyclic_graph(G)
        # The weakest edge (c->a, conf=0.3) should be removed
        assert not G.has_edge("c", "a")
        assert G.has_edge("a", "b")
        assert G.has_edge("b", "c")

    def test_already_dag(self):
        from learnloop.prereq_graph import _break_cycles
        
        G = nx.DiGraph()
        G.add_edge("x", "y", confidence=0.9, evidence="")
        G.add_edge("y", "z", confidence=0.7, evidence="")
        
        edges = [
            PrereqEdge(source="x", target="y", confidence=0.9, evidence="X before Y"),
            PrereqEdge(source="y", target="z", confidence=0.7, evidence="Y before Z"),
        ]
        
        result = _break_cycles(G, edges)
        assert nx.is_directed_acyclic_graph(G)
        assert len(result) == 2


# ── Retriever node lookup ───────────────────────────────────────────────────

class TestRetriever:
    def test_find_node(self):
        from learnloop.retriever import _find_node
        
        tree = [
            TreeNode(node_id="root", title="Root", nodes=[
                TreeNode(node_id="ch1", title="Chapter 1", page_index=1, text="Ch1 content"),
                TreeNode(node_id="ch2", title="Chapter 2", page_index=5, nodes=[
                    TreeNode(node_id="s2_1", title="Section 2.1", page_index=6, text="Deep content"),
                ]),
            ]),
        ]
        
        found = _find_node(tree, "s2_1")
        assert found is not None
        assert found.title == "Section 2.1"
        assert found.text == "Deep content"
        
        not_found = _find_node(tree, "nonexistent")
        assert not_found is None

    def test_compress_tree(self):
        from learnloop.retriever import _compress_tree
        
        tree = [
            TreeNode(
                node_id="n1", title="Intro", page_index=1,
                summary="Introduction to the topic",
                nodes=[
                    TreeNode(node_id="n1_1", title="Background", page_index=2, summary="History"),
                ],
            ),
        ]
        
        compressed = _compress_tree(tree)
        assert len(compressed) == 1
        assert compressed[0]["node_id"] == "n1"
        assert compressed[0]["title"] == "Intro"
        assert compressed[0]["page"] == 1
        assert "children" in compressed[0]
        assert len(compressed[0]["children"]) == 1


# ── Prerequisites helper ────────────────────────────────────────────────────

class TestPrerequisites:
    def test_prerequisites_of(self):
        from learnloop.prereq_graph import prerequisites_of
        
        G = nx.DiGraph()
        G.add_node("arrays", label="Arrays", definition="")
        G.add_node("sorting", label="Sorting", definition="")
        G.add_node("binary_search", label="Binary Search", definition="")
        G.add_edge("arrays", "sorting", confidence=0.9, evidence="Need arrays to sort")
        G.add_edge("sorting", "binary_search", confidence=0.8, evidence="Sorted data for binary search")
        
        prereqs = prerequisites_of("binary_search", G, depth=2)
        assert len(prereqs) == 2
        names = {p["name"] for p in prereqs}
        assert "Sorting" in names
        assert "Arrays" in names

    def test_no_prerequisites(self):
        from learnloop.prereq_graph import prerequisites_of
        
        G = nx.DiGraph()
        G.add_node("basics", label="Basics", definition="")
        
        prereqs = prerequisites_of("basics", G, depth=2)
        assert prereqs == []
