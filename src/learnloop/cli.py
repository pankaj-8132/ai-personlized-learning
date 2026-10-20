"""CLI entry point for LearnLoop pipeline."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from learnloop import llm as llm_module
from learnloop.config import OUTPUT_DIR, get_settings
from learnloop.llm import GeminiLLM, stats
from learnloop.normalizer import extract_and_normalize
from learnloop.pageindex_client import PageIndexService, load_tree
from learnloop.prereq_graph import build_prereq_graph, prerequisites_of
from learnloop.retriever import answer

logger = logging.getLogger(__name__)


def _count_nodes(tree) -> int:
    """Count total nodes in tree."""
    count = 0
    for node in tree:
        count += 1
        if node.nodes:
            count += _count_nodes(node.nodes)
    return count


def cmd_ingest(args: argparse.Namespace) -> None:
    """Ingest a PDF: build tree, extract concepts, build prereq graph."""
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        print(f"Error: {pdf_path} not found")
        sys.exit(1)

    settings = get_settings()
    llm = GeminiLLM(settings)
    pi = PageIndexService(settings)

    # Step 1: PageIndex tree
    print(f"📄 Ingesting {pdf_path.name}...")
    doc_id, tree = pi.ingest(pdf_path)
    total_nodes = _count_nodes(tree)
    print(f"  ✓ Tree loaded: {total_nodes} nodes (doc_id={doc_id})")

    # Step 2: Concept extraction + normalization
    print("🔍 Extracting and normalizing concepts...")
    concepts = extract_and_normalize(tree, doc_id, llm)
    synonym_pairs = sum(1 for c in concepts if len(c.aliases) > 0)
    print(f"  ✓ {len(concepts)} canonical concepts ({synonym_pairs} with aliases)")

    # Step 3: Prerequisite graph
    print("🔗 Building prerequisite graph...")
    edges, G = build_prereq_graph(concepts, doc_id, llm)
    print(f"  ✓ {len(edges)} prerequisite edges (DAG: {__import__('networkx').is_directed_acyclic_graph(G)})")

    # Summary
    print("\n" + "=" * 50)
    print("📊 INGEST SUMMARY")
    print(f"  doc_id:     {doc_id}")
    print(f"  nodes:      {total_nodes}")
    print(f"  concepts:   {len(concepts)}")
    print(f"  edges:      {len(edges)}")
    print(f"  API calls:  {stats.api_calls}")
    print(f"  cache hits: {stats.cache_hits}")
    print(f"  output dir: {OUTPUT_DIR / doc_id}")
    print("=" * 50)


def cmd_ask(args: argparse.Namespace) -> None:
    """Ask a question against an ingested document."""
    doc_id = args.doc
    question = args.question

    settings = get_settings()
    llm = GeminiLLM(settings)
    tree = load_tree(doc_id)

    print(f"❓ Question: {question}")
    print(f"📖 Document: {doc_id}\n")

    sections, answer_text = answer(question, tree, llm)

    print("📑 Retrieved Sections:")
    for s in sections:
        print(f"  • [{s.title}, p.{s.page or '?'}] — {s.reason}")
    print()
    print("💡 Answer:")
    print(answer_text)
    print(f"\n(API calls: {stats.api_calls}, cache hits: {stats.cache_hits})")


def cmd_prereqs(args: argparse.Namespace) -> None:
    """Show prerequisites of a concept."""
    doc_id = args.doc
    concept = args.concept.lower().strip()
    depth = args.depth

    graph_path = OUTPUT_DIR / doc_id / "prereq_graph.json"
    concepts_path = OUTPUT_DIR / doc_id / "concepts.json"

    if not graph_path.exists() or not concepts_path.exists():
        print(f"Error: No graph found for doc_id={doc_id}. Run ingest first.")
        sys.exit(1)

    from learnloop.schemas import Concept, PrereqEdge
    concepts_data = json.loads(concepts_path.read_text())
    concepts = [Concept.model_validate(c) for c in concepts_data]
    edges_data = json.loads(graph_path.read_text())
    edges = [PrereqEdge.model_validate(e) for e in edges_data]

    import networkx as nx
    from learnloop.prereq_graph import _build_nx_graph
    G = _build_nx_graph(concepts, edges)

    # Fuzzy match concept name to concept_id
    concept_id = None
    for c in concepts:
        if concept in c.canonical_name or concept in c.concept_id:
            concept_id = c.concept_id
            break
        if any(concept in a for a in c.aliases):
            concept_id = c.concept_id
            break

    if not concept_id:
        print(f"Concept '{concept}' not found. Available concepts:")
        for c in concepts[:20]:
            print(f"  • {c.canonical_name} ({c.concept_id})")
        if len(concepts) > 20:
            print(f"  ... and {len(concepts) - 20} more")
        sys.exit(1)

    prereqs = prerequisites_of(concept_id, G, depth=depth)
    concept_name = G.nodes[concept_id].get("label", concept_id)
    print(f"🔗 Prerequisites of '{concept_name}' (depth={depth}):\n")

    if not prereqs:
        print("  (no prerequisites found)")
    else:
        for p in prereqs:
            indent = "  " * p["depth"]
            print(f"{indent}← {p['name']} (confidence={p['confidence']:.2f})")
            if p["evidence"]:
                print(f"{indent}  reason: {p['evidence']}")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        prog="learnloop",
        description="LearnLoop: Vectorless reasoning-based RAG pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ingest
    p_ingest = sub.add_parser("ingest", help="Ingest a PDF into the pipeline")
    p_ingest.add_argument("pdf", help="Path to the PDF file")

    # ask
    p_ask = sub.add_parser("ask", help="Ask a question against an ingested document")
    p_ask.add_argument("question", help="The question to ask")
    p_ask.add_argument("--doc", required=True, help="Document ID from ingest")

    # prereqs
    p_prereqs = sub.add_parser("prereqs", help="Show prerequisites of a concept")
    p_prereqs.add_argument("concept", help="Concept name to query")
    p_prereqs.add_argument("--doc", required=True, help="Document ID from ingest")
    p_prereqs.add_argument("--depth", type=int, default=2, help="Max depth (default: 2)")

    args = parser.parse_args()

    if args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "ask":
        cmd_ask(args)
    elif args.command == "prereqs":
        cmd_prereqs(args)


if __name__ == "__main__":
    main()
