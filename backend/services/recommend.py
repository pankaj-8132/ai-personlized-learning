"""Prerequisite-aware gap diagnosis + explainable recommendations (Feature 2)."""


def diagnose(concepts: list[dict], scores: dict) -> list[dict]:
    """concepts: {id,name,prereqs:[ids]}; scores: id -> score_concept() output."""
    by = {c["id"]: c for c in concepts}
    recs: dict[int, dict] = {}

    def add(cid, priority, action, reason):
        if cid not in recs or priority < recs[cid]["priority"]:
            recs[cid] = {"concept_id": cid, "concept": by[cid]["name"], "priority": priority,
                         "action": action, "reason": reason}

    for c in concepts:
        s = scores[c["id"]]
        weak_pre = [p for p in c["prereqs"] if scores[p]["status"] == "weak"]
        if s["status"] == "weak":
            if weak_pre:
                for p in weak_pre:
                    add(p, 0, "review_prerequisite",
                        f"Root cause: '{c['name']}' is weak ({s['correct']}/{s['attempts']} correct) "
                        f"and it depends on '{by[p]['name']}', which is also weak.")
            else:
                add(c["id"], 1, "re_teach",
                    f"You answered {s['correct']} of {s['attempts']} related questions correctly "
                    f"(mastery {s['mastery']}).")
        elif s["status"] == "uncertain":
            add(c["id"], 2, "practice", "Not enough evidence yet: answer a few more questions to get a reliable estimate.")
        elif s["status"] == "unknown":
            if all(scores[p]["status"] in ("strong", "developing") for p in c["prereqs"]):
                add(c["id"], 3, "explore", "Not attempted yet, and its prerequisites look ready." if c["prereqs"]
                    else "Not attempted yet.")
        elif s["status"] == "developing":
            add(c["id"], 4, "practice", f"Developing (mastery {s['mastery']}); a harder quiz would solidify it.")
    return sorted(recs.values(), key=lambda r: r["priority"])
