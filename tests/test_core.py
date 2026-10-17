import time
from backend.services.mastery import score_concept, pick_difficulty
from backend.services.recommend import diagnose
from backend.services.grounding import quote_in_doc
from backend.services.quiz import validate
from backend.services.concepts import _break_cycles

NOW = time.time()


def att(correct, diff="medium", hints=0, conf=2, age=0):
    return {"correct": correct, "difficulty": diff, "hints": hints, "confidence": conf, "created": NOW - age * 86400}


def test_unknown_is_not_weak():
    assert score_concept([])["status"] == "unknown"


def test_single_wrong_is_uncertain_not_weak():
    assert score_concept([att(0)], NOW)["status"] == "uncertain"


def test_repeated_wrong_is_weak():
    assert score_concept([att(0), att(0), att(0), att(1)], NOW)["status"] == "weak"


def test_hints_reduce_credit_and_recency_decays():
    assert score_concept([att(1, hints=2)] * 4, NOW)["mastery"] < score_concept([att(1)] * 4, NOW)["mastery"]
    old = score_concept([att(0, age=60)] * 3 + [att(1)] * 2, NOW)["mastery"]
    new = score_concept([att(0)] * 3 + [att(1, age=60)] * 2, NOW)["mastery"]
    assert old > new


def test_confident_error_hurts_more():
    assert score_concept([att(0, conf=3)] * 3, NOW)["mastery"] < score_concept([att(0, conf=1)] * 3, NOW)["mastery"]


def test_difficulty_adapts():
    assert pick_difficulty({"mastery": None}) == "easy" and pick_difficulty({"mastery": 90}) == "hard"


def test_root_cause_recommendation():
    cs = [{"id": 1, "name": "Binary Search", "prereqs": []}, {"id": 2, "name": "BST", "prereqs": [1]}]
    weak = score_concept([att(0)] * 4, NOW)
    recs = diagnose(cs, {1: weak, 2: weak})
    assert recs[0]["concept"] == "Binary Search" and recs[0]["action"] == "review_prerequisite"


def test_grounding_checks():
    doc = "A binary search tree keeps smaller keys on the left. [Page 2] Larger keys go right."
    assert quote_in_doc("smaller keys on the left", doc) and not quote_in_doc("balanced by definition always", doc)
    q = {"question": "x?", "options": ["a", "b", "c", "d"], "answer_index": 1, "evidence_quote": "keeps smaller keys on the left"}
    assert validate(q, doc) and not validate({**q, "evidence_quote": "made up sentence not present"}, doc)


def test_cycle_break():
    g = _break_cycles({"A": ["B"], "B": ["A"]})
    assert not (g["A"] and g["B"])
