from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data_source"
DB_PATH = ROOT / "data" / "jkeratin_kb.sqlite"


def read_jsonl(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def columns(rows: list[dict[str, str]]) -> list[str]:
    result: list[str] = []
    for row in rows:
        for key in row:
            if key not in result:
                result.append(key)
    return result or ["value"]


def create_table(conn: sqlite3.Connection, name: str, rows: list[dict[str, str]]) -> None:
    cols = columns(rows)
    conn.execute(f'DROP TABLE IF EXISTS "{name}"')
    conn.execute(
        f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY AUTOINCREMENT, '
        + ", ".join(f'"{c}" TEXT' for c in cols)
        + ")"
    )
    if not rows:
        return
    placeholders = ",".join("?" for _ in cols)
    col_sql = ",".join(f'"{c}"' for c in cols)
    for row in rows:
        conn.execute(
            f'INSERT INTO "{name}" ({col_sql}) VALUES ({placeholders})',
            [row.get(c, "") for c in cols],
        )


def main() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    questions = []
    for path in sorted((SOURCE / "questions").glob("*.jsonl")):
        questions.extend(read_jsonl(path))
    manual_updates = read_jsonl(SOURCE / "manual_updates.jsonl")
    products = read_csv(SOURCE / "products.csv")
    faq = read_jsonl(SOURCE / "faq_templates.jsonl")
    forbidden = read_jsonl(SOURCE / "forbidden_phrases.jsonl")
    synonyms = read_jsonl(SOURCE / "synonyms.jsonl")
    prompts = read_jsonl(SOURCE / "prompts.jsonl")

    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    create_table(conn, "questions", questions)
    create_table(conn, "manual_updates", manual_updates)
    create_table(conn, "products", products)
    create_table(conn, "faq_templates", faq)
    create_table(conn, "forbidden_phrases", forbidden)
    create_table(conn, "synonyms", synonyms)
    create_table(conn, "prompts", prompts)

    conn.execute("DROP TABLE IF EXISTS kb_search")
    conn.execute("CREATE VIRTUAL TABLE kb_search USING fts5(source_table, source_id, title, body, tags)")

    def insert_search(source_table: str, source_id: str, title: str, body: str, tags: str = "") -> None:
        conn.execute(
            "INSERT INTO kb_search(source_table, source_id, title, body, tags) VALUES (?, ?, ?, ?, ?)",
            (source_table, source_id, title, body, tags),
        )

    for row in questions:
        insert_search(
            "questions",
            row.get("question_id") or row.get("id") or "",
            row.get("product_name") or row.get("seller_sku") or row.get("wb_sku") or "",
            " | ".join(str(v) for v in row.values()),
            " | ".join([row.get("theme", ""), row.get("subtheme", ""), row.get("keywords", "")]),
        )
    for row in manual_updates:
        insert_search("manual_updates", row.get("id", ""), row.get("product", ""), " | ".join(str(v) for v in row.values()), row.get("theme", ""))
    for row in products:
        insert_search("products", row.get("wb_sku", ""), row.get("nazvanie_kratkoe") or row.get("product_name", ""), " | ".join(str(v) for v in row.values()), row.get("category", ""))
    for row in faq:
        insert_search("faq_templates", row.get("faq_id", ""), row.get("theme", ""), " | ".join(str(v) for v in row.values()), row.get("product_category", ""))
    for row in forbidden:
        insert_search("forbidden_phrases", "", row.get("situation", ""), " | ".join(str(v) for v in row.values()), "")
    for row in synonyms:
        insert_search("synonyms", "", row.get("client_phrase", ""), " | ".join(str(v) for v in row.values()), "")

    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
