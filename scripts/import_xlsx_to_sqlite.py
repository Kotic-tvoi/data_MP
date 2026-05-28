"""
Импортирует Excel-файл .xlsx в SQLite без pandas/openpyxl-зависимостей в рантайме.

Скрипт использует стандартные библиотеки zipfile/xml/sqlite3 и подходит для
регулярного обновления базы новыми выгрузками.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def slugify(value: str) -> str:
    table = str.maketrans(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        "abvgdeejzijklmnoprstufhzcss_y_eua",
    )
    value = (value or "column").strip().lower().translate(table)
    value = re.sub(r"[^a-z0-9а-яё]+", "_", value, flags=re.I).strip("_")
    return value or "column"


def read_shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings = []
    for si in root.findall(f"{NS_MAIN}si"):
        texts = []
        for t in si.iter(f"{NS_MAIN}t"):
            texts.append(t.text or "")
        strings.append("".join(texts))
    return strings


def workbook_sheets(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall(f"{NS_PKG_REL}Relationship")}
    result = []
    for sheet in wb.findall(f"{NS_MAIN}sheets/{NS_MAIN}sheet"):
        name = sheet.attrib["name"]
        rid = sheet.attrib[f"{NS_REL}id"]
        target = rel_map[rid]
        path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
        result.append((name, path))
    return result


def cell_value(cell: ET.Element, shared: list[str]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        texts = [t.text or "" for t in cell.iter(f"{NS_MAIN}t")]
        return "".join(texts)
    v = cell.find(f"{NS_MAIN}v")
    if v is None:
        return None
    text = v.text or ""
    if cell_type == "s":
        try:
            return shared[int(text)]
        except Exception:
            return text
    return text


def column_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def read_sheet(z: zipfile.ZipFile, path: str, shared: list[str]) -> list[list[Any]]:
    root = ET.fromstring(z.read(path))
    rows = []
    for row in root.findall(f"{NS_MAIN}sheetData/{NS_MAIN}row"):
        values = []
        for cell in row.findall(f"{NS_MAIN}c"):
            idx = column_index(cell.attrib.get("r", "A1"))
            while len(values) <= idx:
                values.append(None)
            values[idx] = cell_value(cell, shared)
        rows.append(values)
    return rows


def unique_columns(headers: list[Any]) -> list[str]:
    used: dict[str, int] = {}
    columns = []
    for i, header in enumerate(headers, start=1):
        base = slugify(str(header or f"column_{i}"))
        count = used.get(base, 0) + 1
        used[base] = count
        columns.append(base if count == 1 else f"{base}_{count}")
    return columns


def import_workbook(xlsx_path: Path, db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    metadata = {}
    with zipfile.ZipFile(xlsx_path) as z:
        shared = read_shared_strings(z)
        sheets = workbook_sheets(z)
        for sheet_idx, (sheet_name, sheet_path) in enumerate(sheets):
            rows = read_sheet(z, sheet_path, shared)
            non_empty = [r for r in rows if any(v not in (None, "") for v in r)]
            if not non_empty:
                continue
            headers = unique_columns(non_empty[0])
            table_name = f"c_{sheet_idx:02d}_{slugify(sheet_name)}"
            conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            cols_sql = ", ".join([f'"{c}" TEXT' for c in headers])
            conn.execute(f'CREATE TABLE "{table_name}" (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols_sql})')
            placeholders = ", ".join(["?"] * len(headers))
            col_names = ", ".join([f'"{c}"' for c in headers])
            for row in non_empty[1:]:
                row = list(row) + [None] * (len(headers) - len(row))
                conn.execute(
                    f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})',
                    row[: len(headers)],
                )
            metadata[sheet_name] = {"table": table_name, "columns": headers, "rows": max(0, len(non_empty) - 1)}
    conn.commit()
    conn.close()
    db_path.with_suffix(".metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("xlsx")
    parser.add_argument("--db", default="data/jkeratin_kb.sqlite")
    args = parser.parse_args()
    import_workbook(Path(args.xlsx), Path(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
