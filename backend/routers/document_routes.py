import time
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from ..auth import current_user
from ..db import get_db
from ..documents import extract_text
from ..services import doc_qa

router = APIRouter(prefix="/api/documents", tags=["documents"])


def get_doc(db, doc_id: int, user_id: int):
    d = db.execute("SELECT * FROM documents WHERE id=? AND user_id=?", (doc_id, user_id)).fetchone()
    if not d:
        raise HTTPException(404, "Document not found")
    return d


@router.post("")
async def upload(file: UploadFile = File(...), user=Depends(current_user)):
    text = extract_text(file.filename or "", await file.read())
    with get_db() as db:
        cur = db.execute("INSERT INTO documents(user_id,name,text,created) VALUES(?,?,?,?)",
                         (user["id"], file.filename, text, time.time()))
    return {"id": cur.lastrowid, "name": file.filename, "chars": len(text)}


@router.get("")
def list_docs(user=Depends(current_user)):
    with get_db() as db:
        rows = db.execute("SELECT id,name,length(text) AS chars FROM documents WHERE user_id=? ORDER BY id DESC",
                          (user["id"],)).fetchall()
    return [dict(r) for r in rows]


@router.delete("/{doc_id}")
def delete(doc_id: int, user=Depends(current_user)):  # privacy: full deletion of a doc and derived data
    with get_db() as db:
        get_doc(db, doc_id, user["id"])
        cids = [r["id"] for r in db.execute("SELECT id FROM concepts WHERE doc_id=?", (doc_id,))]
        for cid in cids:
            db.execute("DELETE FROM attempts WHERE concept_id=?", (cid,))
            db.execute("DELETE FROM misconceptions WHERE concept_id=?", (cid,))
        db.execute("DELETE FROM questions WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM concepts WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    return {"deleted": True}


class Ask(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


@router.post("/{doc_id}/ask")
def ask(doc_id: int, body: Ask, user=Depends(current_user)):
    with get_db() as db:
        doc = get_doc(db, doc_id, user["id"])
    return doc_qa.ask(doc["text"], body.question)
