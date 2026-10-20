"""Vectorless reasoning-based tree search and answer generation."""
from __future__ import annotations

import json
import logging
from typing import Any

from learnloop.llm import GeminiLLM
from learnloop.schemas import RetrievedNode, TreeNode

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 15000  # cap total retrieved text


def _compress_tree(nodes: list[TreeNode], depth: int = 0) -> list[dict[str, Any]]:
    """Compress tree to titles + page + short summary for the LLM prompt."""
    result = []
    for node in nodes:
        entry: dict[str, Any] = {
            "node_id": node.node_id,
            "title": node.title,
        }
        if node.page_index is not None:
            entry["page"] = node.page_index
        if node.summary:
            entry["summary"] = node.summary[:120]
        if node.nodes:
            entry["children"] = _compress_tree(node.nodes, depth + 1)
        result.append(entry)
    return result


def _find_node(nodes: list[TreeNode], node_id: str) -> TreeNode | None:
    """Recursively find a node by id."""
    for node in nodes:
        if node.node_id == node_id:
            return node
        if node.nodes:
            found = _find_node(node.nodes, node_id)
            if found:
                return found
    return None


SEARCH_PROMPT = """\
You are a document search expert. Given a question and a document's table-of-contents tree, select the sections most likely to contain the answer.

Question: {question}

Document tree (node_id, title, page, summary):
{tree_json}

Return a JSON object with:
- "thinking": your step-by-step reasoning about which sections are relevant
- "node_list": array of objects with "node_id" and "reason" (why this section is relevant)

Select 2-5 most relevant sections. Be precise.
"""

EXPAND_PROMPT = """\
You are a document search expert. Given a question and the children of a relevant section, pick the most relevant subsections.

Question: {question}

Parent section: {parent_title}
Children:
{children_json}

Return a JSON object with:
- "thinking": your reasoning
- "node_list": array of objects with "node_id" and "reason"

Select the 1-3 most relevant children.
"""

ANSWER_PROMPT = """\
Answer the question using ONLY the provided source material. 
Cite each claim with [Section Title, p.X].
If the material doesn't contain enough information, say "Insufficient evidence in the material."

Question: {question}

Source material:
{context}
"""


def retrieve(
    question: str,
    tree: list[TreeNode],
    llm: GeminiLLM,
) -> list[RetrievedNode]:
    """Reasoning-based retrieval: LLM navigates the tree to find relevant sections."""
    compressed = _compress_tree(tree)
    tree_json = json.dumps(compressed, indent=1)

    # Top-level search
    prompt = SEARCH_PROMPT.format(question=question, tree_json=tree_json)
    try:
        result = llm.generate_json(prompt)
    except Exception as e:
        logger.error("Tree search failed: %s", e)
        return []

    node_list = result.get("node_list", []) if isinstance(result, dict) else []
    thinking = result.get("thinking", "") if isinstance(result, dict) else ""
    if thinking:
        logger.info("Search reasoning: %s", thinking[:200])

    # Expand children for nodes that have them
    expanded_ids: list[tuple[str, str]] = []  # (node_id, reason)
    for item in node_list:
        nid = item.get("node_id", "")
        reason = item.get("reason", "")
        node = _find_node(tree, nid)
        if not node:
            continue
        if node.nodes:
            # Try to narrow down to specific children
            children_compressed = _compress_tree(node.nodes)
            expand_prompt = EXPAND_PROMPT.format(
                question=question,
                parent_title=node.title,
                children_json=json.dumps(children_compressed, indent=1),
            )
            try:
                expand_result = llm.generate_json(expand_prompt)
                child_list = expand_result.get("node_list", []) if isinstance(expand_result, dict) else []
                for child_item in child_list:
                    expanded_ids.append((child_item.get("node_id", ""), child_item.get("reason", reason)))
            except Exception:
                expanded_ids.append((nid, reason))
        else:
            expanded_ids.append((nid, reason))

    # Collect full text from chosen nodes, cap context size
    retrieved: list[RetrievedNode] = []
    total_chars = 0
    for nid, reason in expanded_ids:
        node = _find_node(tree, nid)
        if not node:
            continue
        text = node.text or ""
        if total_chars + len(text) > MAX_CONTEXT_CHARS:
            text = text[: MAX_CONTEXT_CHARS - total_chars]
        total_chars += len(text)
        retrieved.append(RetrievedNode(
            node_id=node.node_id,
            title=node.title,
            page=node.page_index,
            text=text,
            reason=reason,
        ))
        if total_chars >= MAX_CONTEXT_CHARS:
            break

    logger.info("Retrieved %d sections (%d chars)", len(retrieved), total_chars)
    return retrieved


def answer(
    question: str,
    tree: list[TreeNode],
    llm: GeminiLLM,
) -> tuple[list[RetrievedNode], str]:
    """Retrieve relevant sections, then generate a cited answer."""
    sections = retrieve(question, tree, llm)
    if not sections:
        return sections, "Insufficient evidence in the material."

    context_parts = []
    for s in sections:
        header = f"[{s.title}, p.{s.page or '?'}]"
        context_parts.append(f"{header}\n{s.text or '(no text)'}\n")

    context = "\n---\n".join(context_parts)
    prompt = ANSWER_PROMPT.format(question=question, context=context)

    answer_text = llm.generate(
        prompt,
        model=llm._settings.gemini_model_answer,
        temperature=0.2,
        system_instruction="You are a precise academic tutor. Answer only from the provided material with page citations.",
    )
    return sections, answer_text
