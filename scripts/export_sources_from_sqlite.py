from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "jkeratin_kb.sqlite"
OUT = ROOT / "data_source"

# Touch this file to trigger sync_text_sources workflow when manual button is not visible.


def norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalize_date(value: Any) -> str:
    text = norm(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+(\.\d+)?", text):
        try:
            dt = datetime(1899, 12, 30) + timedelta(days=float(text))
            if 2000 <= dt.year <= 2100:
                return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return text


def clean_row(row: sqlite3.Row) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in row.keys():
        value = row[key]
        if key.lower() in {"date", "data", "created_at", "published_at"}:
            result[key] = normalize_date(value)
        else:
            result[key] = norm(value)
    return result


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def find_table(tables: list[str], *needles: str) -> str | None:
    lowered = [(t, t.lower()) for t in tables]
    for needle in needles:
        n = needle.lower()
        for original, low in lowered:
            if n in low:
                return original
    return None


def read_rows(conn: sqlite3.Connection, table: str | None) -> list[dict[str, str]]:
    if not table:
        return []
    conn.row_factory = sqlite3.Row
    return [clean_row(r) for r in conn.execute(f'SELECT * FROM "{table}"')]


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def split_questions_by_year(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        date = row.get("date") or row.get("data") or ""
        m = re.search(r"(20\d{2})", date)
        year = m.group(1) if m else "unknown"
        buckets[year].append(row)
    return dict(sorted(buckets.items()))


def main() -> int:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"SQLite database not found: {DB_PATH}")

    OUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    tables = table_names(conn)

    table_map = {
        "questions": find_table(tables, "voprosy_razmetka", "questions_enriched", "questions"),
        "questions_raw": find_table(tables, "voprosy_raw", "questions_raw"),
        "products": find_table(tables, "spravochnik_tovarov", "products"),
        "faq_templates": find_table(tables, "faq_shablony", "faq_templates"),
        "forbidden_phrases": find_table(tables, "zapreschennye", "forbidden"),
        "synonyms": find_table(tables, "sinonimy", "synonyms"),
        "prompts": find_table(tables, "promty", "prompts"),
    }

    questions = read_rows(conn, table_map["questions"])
    products = read_rows(conn, table_map["products"])
    faq = read_rows(conn, table_map["faq_templates"])
    forbidden = read_rows(conn, table_map["forbidden_phrases"])
    synonyms = read_rows(conn, table_map["synonyms"])
    prompts = read_rows(conn, table_map["prompts"])

    for year, rows in split_questions_by_year(questions).items():
        write_jsonl(OUT / "questions" / f"{year}.jsonl", rows)

    write_csv(OUT / "products.csv", products)
    write_jsonl(OUT / "faq_templates.jsonl", faq)
    write_jsonl(OUT / "forbidden_phrases.jsonl", forbidden)
    write_jsonl(OUT / "synonyms.jsonl", synonyms)
    write_jsonl(OUT / "prompts.jsonl", prompts)

    manual = OUT / "manual_updates.jsonl"
    if not manual.exists():
        manual.write_text("", encoding="utf-8")

    readme = OUT / "README.md"
    readme.write_text(
        "# data_source\n\n"
        "Это текстовый источник базы знаний. Эти файлы можно читать и обновлять через GitHub/чат.\n\n"
        "Главное правило: SQLite является сборочным артефактом, а не ручным источником данных.\n\n"
        "- `products.csv` — справочник товаров и артикулов.\n"
        "- `questions/YYYY.jsonl` — вопросы клиентов, разбитые по годам.\n"
        "- `faq_templates.jsonl` — готовые FAQ-шаблоны.\n"
        "- `forbidden_phrases.jsonl` — запрещённые и корректные формулировки.\n"
        "- `synonyms.jsonl` — синонимы для поиска.\n"
        "- `manual_updates.jsonl` — новые записи, которые можно добавлять через чат.\n",
        encoding="utf-8",
    )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_database": str(DB_PATH.relative_to(ROOT)),
        "table_map": table_map,
        "files": {
            "products.csv": len(products),
            "faq_templates.jsonl": len(faq),
            "forbidden_phrases.jsonl": len(forbidden),
            "synonyms.jsonl": len(synonyms),
            "prompts.jsonl": len(prompts),
            "manual_updates.jsonl": "append-only",
            "questions": {year: len(rows) for year, rows in split_questions_by_year(questions).items()},
        },
        "purpose": "Текстовая база знаний для чтения и обновления через ChatGPT/GitHub. SQLite пересобирается из этих файлов.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
