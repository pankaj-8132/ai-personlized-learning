"""Pydantic models for tree nodes, concepts, and prerequisite edges."""
from __future__ import annotations

from pydantic import BaseModel, Field


# ── PageIndex tree ──────────────────────────────────────────────────────────

class TreeNode(BaseModel):
    """A node in the PageIndex hierarchical tree."""
    node_id: str
    title: str
    page_index: int | None = None
    text: str | None = None
    summary: str | None = None
    nodes: list[TreeNode] = Field(default_factory=list)


# ── Concept normalizer ──────────────────────────────────────────────────────

class RawConcept(BaseModel):
    """Single concept extracted from one leaf node (pre-merge)."""
    name: str
    aliases: list[str] = Field(default_factory=list)
    definition: str = ""
    pages: list[int] = Field(default_factory=list)


class Concept(BaseModel):
    """Canonical concept after synonym merging."""
    concept_id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    definition: str = ""
    node_ids: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)


# ── Prerequisite graph ──────────────────────────────────────────────────────

class PrereqEdge(BaseModel):
    """Directed edge: source is a prerequisite of target."""
    source: str
    target: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = ""
    source_pages: list[int] = Field(default_factory=list)


# ── Retriever ───────────────────────────────────────────────────────────────

class RetrievedNode(BaseModel):
    """A node selected by the reasoning retriever."""
    node_id: str
    title: str
    page: int | None = None
    text: str | None = None
    reason: str = ""
