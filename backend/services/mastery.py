"""Interpretable concept-mastery model (Feature 1). Pure functions, fully unit-testable."""
import math, time

DIFF_W = {"easy": 0.7, "medium": 1.0, "hard": 1.3}
HALF_LIFE_DAYS = 14.0   # evidence loses half its weight every 14 days
HINT_CREDIT = 0.6       # a correct answer after hints counts 60%
CONFIDENT_ERROR_BOOST = 1.3  # wrong while "sure" (confidence 3) is stronger evidence of a gap
PRIOR = 1.0


def score_concept(attempts: list[dict], now: float | None = None) -> dict:
    """attempts: dicts with correct, hints, confidence(1-3), difficulty, created(ts)."""
    now = now or time.time()
    sw = sc = 0.0
    n = len(attempts)
    right = sum(1 for a in attempts if a["correct"])
    for a in attempts:
        age = max(0.0, (now - a["created"]) / 86400)
        w = DIFF_W.get(a["difficulty"], 1.0) * math.exp(-math.log(2) * age / HALF_LIFE_DAYS)
        if a["correct"]:
            credit = HINT_CREDIT if a.get("hints", 0) > 0 else 1.0
        else:
            credit = 0.0
            if a.get("confidence", 2) == 3:
                w *= CONFIDENT_ERROR_BOOST
        sw += w
        sc += w * credit
    if n == 0:
        return {"mastery": None, "confidence": 0.0, "status": "unknown", "attempts": 0, "correct": 0}
    mastery = 100 * (sc + 0.5 * PRIOR) / (sw + PRIOR)
    confidence = 1 - math.exp(-sw / 3)
    if confidence < 0.45:
        status = "uncertain"   # not enough evidence to call it weak OR strong
    elif mastery < 50:
        status = "weak"
    elif mastery >= 75:
        status = "strong"
    else:
        status = "developing"
    return {"mastery": round(mastery, 1), "confidence": round(confidence, 2),
            "status": status, "attempts": n, "correct": right}


def pick_difficulty(score: dict) -> str:
    m = score["mastery"]
    if m is None or m < 40:
        return "easy"
    return "medium" if m < 70 else "hard"
