import sqlite3
from contextlib import contextmanager
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, salt TEXT, pw_hash TEXT, token TEXT);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, text TEXT, created REAL);
CREATE TABLE IF NOT EXISTS concepts(id INTEGER PRIMARY KEY, doc_id INTEGER, name TEXT, description TEXT, prereqs TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, doc_id INTEGER, concept_id INTEGER, text TEXT,
  options TEXT, answer_idx INTEGER, difficulty TEXT, evidence TEXT, explanation TEXT);
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, user_id INTEGER, question_id INTEGER, concept_id INTEGER,
  chosen INTEGER, correct INTEGER, hints INTEGER, confidence INTEGER, created REAL);
CREATE TABLE IF NOT EXISTS misconceptions(id INTEGER PRIMARY KEY, user_id INTEGER, concept_id INTEGER,
  description TEXT, count INTEGER DEFAULT 1, last_seen REAL);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)
