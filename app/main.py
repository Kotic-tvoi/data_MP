from pathlib import Path
import sqlite3
from fastapi import FastAPI, Query

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "jkeratin_kb.sqlite"

app = FastAPI(title="JKeratin Knowledge Base API", version="0.1.0")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/health")
def health():
    return {"status": "ok", "database": str(DB_PATH), "exists": DB_PATH.exists()}


@app.get("/tables")
def tables():
    with connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
        ).fetchall()
    return {"tables": [row["name"] for row in rows]}


@app.get("/search")
def search(q: str = Query(..., min_length=2), limit: int = Query(10, ge=1, le=50)):
    sql = """
    SELECT
        source_table,
        source_id,
        title,
        snippet(kb_search, 3, '<b>', '</b>', '...', 18) AS snippet,
        tags,
        bm25(kb_search) AS rank
    FROM kb_search
    WHERE kb_search MATCH ?
    ORDER BY rank
    LIMIT ?
    """
    with connect() as conn:
        rows = conn.execute(sql, (q, limit)).fetchall()
    return {"query": q, "results": [dict(row) for row in rows]}


@app.get("/faq")
def faq(limit: int = Query(50, ge=1, le=200)):
    with connect() as conn:
        rows = conn.execute(
            'SELECT * FROM "05_faq_shablony" LIMIT ?',
            (limit,),
        ).fetchall()
    return {"results": [dict(row) for row in rows]}
