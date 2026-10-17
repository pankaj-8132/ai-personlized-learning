import re


def normalize(s: str) -> str:
    s = re.sub(r"\[Page \d+\]", " ", s)
    s = re.sub(r"[\"'“”‘’]", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def quote_in_doc(quote: str, doc_text: str, min_len: int = 15) -> bool:
    """Programmatic check that an LLM 'evidence quote' really exists in the document."""
    q = normalize(quote or "")
    return len(q) >= min_len and q in normalize(doc_text)


def wrap_doc(text: str, limit: int) -> str:
    return f"<document>\n{text[:limit]}\n</document>"
