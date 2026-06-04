from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data_source"
DB_PATH = ROOT / "data" / "jkeratin_kb.sqlite"


def to_text(value: Any) -> str:
    """Convert any source value to SQLite-safe text."""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_json_files(folder: Path) -> list[dict[str, Any]]:
    if not folder.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            row = json.load(f)
        if isinstance(row, dict):
            row.setdefault("source_file", str(path.relative_to(ROOT)))
            rows.append(row)
    return rows


def read_markdown_files(folder: Path) -> list[dict[str, Any]]:
    if not folder.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.md")):
        rows.append(
            {
                "id": path.stem,
                "source_file": str(path.relative_to(ROOT)),
                "title": path.stem.replace("_", " "),
                "body": path.read_text(encoding="utf-8"),
            }
        )
    return rows


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def columns(rows: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for row in rows:
        for key in row:
            if key not in result:
                result.append(key)
    return result or ["value"]


def sql_col(name: str) -> str:
    if name.lower() in {"_pk", "rowid", "oid"}:
        return "source_" + name
    return name


def create_table(conn: sqlite3.Connection, name: str, rows: list[dict[str, Any]]) -> None:
    original_cols = columns(rows)
    cols = [sql_col(c) for c in original_cols]
    conn.execute(f'DROP TABLE IF EXISTS "{name}"')
    conn.execute(
        f'CREATE TABLE "{name}" (_pk INTEGER PRIMARY KEY AUTOINCREMENT, '
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
            [to_text(row.get(c, "")) for c in original_cols],
        )


def row_text(row: dict[str, Any]) -> str:
    return " | ".join(to_text(v) for v in row.values())


def first_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return to_text(value)
    return ""


def main() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    questions: list[dict[str, Any]] = []
    for path in sorted((SOURCE / "questions").glob("*.jsonl")):
        questions.extend(read_jsonl(path))

    manual_updates = read_jsonl(SOURCE / "manual_updates.jsonl")
    approved_answers = read_json_files(SOURCE / "approved_answers")
    reference_materials = read_markdown_files(SOURCE / "reference_materials")
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
    create_table(conn, "approved_answers", approved_answers)
    create_table(conn, "reference_materials", reference_materials)
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
            (to_text(source_table), to_text(source_id), to_text(title), to_text(body), to_text(tags)),
        )

    for row in questions:
        insert_search(
            "questions",
            first_value(row, "question_id", "id_voprosa", "id"),
            first_value(row, "nazvanie_tovara", "product_name", "artikul_prodavca", "seller_sku", "artikul_wb", "wb_sku"),
            row_text(row),
            " | ".join([first_value(row, "tema", "theme"), first_value(row, "podtema", "subtheme"), first_value(row, "keywords", "klyuchevye_slova")]),
        )
    for row in manual_updates:
        insert_search(
            "manual_updates",
            first_value(row, "id"),
            first_value(row, "product_name", "product", "product_alias", "seller_sku", "wb_sku"),
            row_text(row),
            " | ".join([first_value(row, "theme"), first_value(row, "subtheme"), first_value(row, "keywords")]),
        )
    for row in approved_answers:
        insert_search(
            "approved_answers",
            first_value(row, "id"),
            first_value(row, "product_name", "product_alias", "seller_sku", "wb_sku"),
            row_text(row),
            " | ".join([first_value(row, "theme"), first_value(row, "subtheme"), first_value(row, "keywords")]),
        )
    for row in reference_materials:
        insert_search("reference_materials", first_value(row, "id"), first_value(row, "title"), first_value(row, "body"), first_value(row, "source_file"))
    for row in products:
        insert_search("products", first_value(row, "artikul_wb", "wb_sku"), first_value(row, "nazvanie_tovara", "nazvanie_kratkoe", "product_name"), row_text(row), first_value(row, "kategoriya", "category"))
    for row in faq:
        insert_search("faq_templates", first_value(row, "faq_id", "id"), first_value(row, "tema", "theme"), row_text(row), first_value(row, "kategoriya_tovara", "product_category"))
    for row in forbidden:
        insert_search("forbidden_phrases", "", first_value(row, "situaciya", "situation"), row_text(row), "")
    for row in synonyms:
        insert_search("synonyms", "", first_value(row, "klient_pishet", "client_phrase"), row_text(row), "")

    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
