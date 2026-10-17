import io, re
from pypdf import PdfReader
from fastapi import HTTPException
from .config import ALLOWED_EXT, MAX_UPLOAD_MB


def extract_text(filename: str, data: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXT))}")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"File larger than {MAX_UPLOAD_MB} MB")
    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(f"[Page {i+1}]\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages))
    else:
        text = data.decode("utf-8", errors="ignore")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) < 200:
        raise HTTPException(400, "Could not extract enough text (scanned PDF? OCR is not supported yet).")
    return text
