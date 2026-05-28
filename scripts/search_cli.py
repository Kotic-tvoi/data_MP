import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "jkeratin_kb.sqlite"


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python scripts/search_cli.py "search text"')
        return 1

    query = " ".join(sys.argv[1:])
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT source_table, source_id, title,
               snippet(kb_search, 3, '[', ']', '...', 24) AS snippet,
               tags,
               bm25(kb_search) AS rank
        FROM kb_search
        WHERE kb_search MATCH ?
        ORDER BY rank
        LIMIT 10
        """,
        (query,),
    ).fetchall()

    for i, row in enumerate(rows, start=1):
        print(f"\n#{i} [{row['source_table']}:{row['source_id']}] {row['title']}")
        if row["tags"]:
            print(f"tags: {row['tags']}")
        print(row["snippet"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
