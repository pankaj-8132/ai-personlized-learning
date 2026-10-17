import os
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DB_PATH", "learnloop.db")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
MAX_DOC_CHARS = int(os.getenv("MAX_DOC_CHARS", "60000"))  # whole doc goes in the prompt (no RAG)
MAX_UPLOAD_MB = 10
ALLOWED_EXT = {".pdf", ".txt", ".md"}
