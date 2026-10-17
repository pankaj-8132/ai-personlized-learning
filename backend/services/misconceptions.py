"""Misconception memory (Feature 3): remember *why* a student is wrong, across sessions."""
import time
from difflib import SequenceMatcher
from ..llm import complete_json

SYSTEM = ('A student answered a multiple-choice question wrongly. In ONE short sentence, state the underlying '
          'misconception (the false belief), not just "chose wrong option". '
          'Return {"misconception": str}.')


def label(question: str, correct: str, chosen: str) -> str:
    out = complete_json(SYSTEM, f"Question: {question}\nCorrect answer: {correct}\nStudent chose: {chosen}", 300)
    return out.get("misconception", "").strip()


def record(db, user_id: int, concept_id: int, text: str) -> dict:
    """Merge with an existing similar misconception for this concept, else create."""
    rows = db.execute("SELECT * FROM misconceptions WHERE user_id=? AND concept_id=?", (user_id, concept_id)).fetchall()
    for r in rows:
        if SequenceMatcher(None, r["description"].lower(), text.lower()).ratio() > 0.6:
            db.execute("UPDATE misconceptions SET count=count+1,last_seen=? WHERE id=?", (time.time(), r["id"]))
            return {"description": r["description"], "count": r["count"] + 1}
    db.execute("INSERT INTO misconceptions(user_id,concept_id,description,count,last_seen) VALUES(?,?,?,1,?)",
               (user_id, concept_id, text, time.time()))
    return {"description": text, "count": 1}


def recurring(db, user_id: int, concept_id: int | None = None, min_count: int = 2) -> list[dict]:
    q = "SELECT * FROM misconceptions WHERE user_id=? AND count>=?"
    args: list = [user_id, min_count]
    if concept_id:
        q += " AND concept_id=?"
        args.append(concept_id)
    return [dict(r) for r in db.execute(q + " ORDER BY count DESC", args).fetchall()]
