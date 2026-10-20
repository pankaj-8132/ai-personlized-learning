"""PageIndex cloud client: submit, poll, fetch tree, content-hash cache."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from pageindex import PageIndexClient as _PageIndexClient

from learnloop.config import OUTPUT_DIR, Settings
from learnloop.schemas import TreeNode

logger = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    """SHA-256 of file content for dedup."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_tree(nodes: list[dict], path: str = "root") -> list[TreeNode]:
    """Validate tree nodes with pydantic, log any issues."""
    validated: list[TreeNode] = []
    for i, raw in enumerate(nodes):
        loc = f"{path}[{i}]"
        missing = [f for f in ("node_id", "title") if f not in raw]
        if missing:
            logger.warning("Node at %s missing fields: %s — skipping", loc, missing)
            continue
        children = raw.get("nodes", [])
        if children:
            raw["nodes"] = [n.model_dump() for n in _validate_tree(children, f"{loc}.nodes")]
        try:
            validated.append(TreeNode.model_validate(raw))
        except Exception as e:
            logger.warning("Validation error at %s: %s", loc, e)
    return validated


class PageIndexService:
    """Wraps the PageIndex cloud SDK with caching."""

    def __init__(self, settings: Settings) -> None:
        self._client = _PageIndexClient(api_key=settings.pageindex_api_key)
        self._hash_index = self._load_hash_index()

    @staticmethod
    def _hash_index_path() -> Path:
        return OUTPUT_DIR / "_hash_index.json"

    def _load_hash_index(self) -> dict[str, str]:
        p = self._hash_index_path()
        if p.exists():
            return json.loads(p.read_text())
        return {}

    def _save_hash_index(self) -> None:
        self._hash_index_path().write_text(json.dumps(self._hash_index, indent=2))

    def _doc_dir(self, doc_id: str) -> Path:
        d = OUTPUT_DIR / doc_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def ingest(self, pdf_path: Path) -> tuple[str, list[TreeNode]]:
        """Submit PDF, poll, fetch tree. Returns (doc_id, tree_nodes).
        
        Skips upload if the same content hash was already processed.
        """
        content_hash = _file_hash(pdf_path)

        # Check content-hash cache
        if content_hash in self._hash_index:
            doc_id = self._hash_index[content_hash]
            cached_tree = self._doc_dir(doc_id) / "page_index.json"
            if cached_tree.exists():
                logger.info("Cache hit for %s (doc_id=%s)", pdf_path.name, doc_id)
                raw = json.loads(cached_tree.read_text())
                nodes = _validate_tree(raw if isinstance(raw, list) else raw.get("nodes", raw.get("result", [])))
                return doc_id, nodes

        # Submit document
        logger.info("Submitting %s to PageIndex cloud...", pdf_path.name)
        result = self._client.submit_document(str(pdf_path))
        doc_id = result["doc_id"]
        logger.info("Document submitted, doc_id=%s. Polling...", doc_id)

        # Poll until completed
        while True:
            doc_info = self._client.get_document(doc_id)
            status = doc_info.get("status", "unknown")
            logger.info("  status: %s", status)
            if status == "completed":
                break
            if status == "failed":
                raise RuntimeError(f"PageIndex processing failed for {pdf_path.name}")
            time.sleep(2)

        # Fetch tree with summaries
        logger.info("Fetching tree with summaries...")
        tree_resp = self._client.get_tree(doc_id, node_summary=True)
        raw_tree = tree_resp.get("result", tree_resp) if isinstance(tree_resp, dict) else tree_resp

        # Save raw tree as-is
        doc_dir = self._doc_dir(doc_id)
        tree_path = doc_dir / "page_index.json"
        tree_path.write_text(json.dumps(raw_tree, indent=2, default=str))

        # Update hash index
        self._hash_index[content_hash] = doc_id
        self._save_hash_index()

        # Validate
        nodes = _validate_tree(raw_tree if isinstance(raw_tree, list) else [raw_tree])
        logger.info("Tree loaded: %d top-level nodes", len(nodes))
        return doc_id, nodes


def load_tree(doc_id: str) -> list[TreeNode]:
    """Load a previously cached tree from disk."""
    tree_path = OUTPUT_DIR / doc_id / "page_index.json"
    if not tree_path.exists():
        raise FileNotFoundError(f"No cached tree for doc_id={doc_id}")
    raw = json.loads(tree_path.read_text())
    return _validate_tree(raw if isinstance(raw, list) else raw.get("nodes", raw.get("result", [raw])))
