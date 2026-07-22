from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from app.config import Settings, get_settings

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS report_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    marketplace TEXT NOT NULL CHECK (marketplace IN ('wb','ozon')),
    started_at TEXT NOT NULL,
    collected_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running','success','failed')),
    rows_count INTEGER NOT NULL DEFAULT 0,
    warehouses_count INTEGER NOT NULL DEFAULT 0,
    total_available INTEGER NOT NULL DEFAULT 0,
    total_reserved INTEGER NOT NULL DEFAULT 0,
    raw_file TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS stock_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES report_runs(id) ON DELETE CASCADE,
    marketplace TEXT NOT NULL,
    fulfillment_type TEXT NOT NULL DEFAULT '',
    product_id TEXT NOT NULL DEFAULT '',
    sku TEXT NOT NULL DEFAULT '',
    offer_id TEXT NOT NULL DEFAULT '',
    vendor_code TEXT NOT NULL DEFAULT '',
    barcode TEXT NOT NULL DEFAULT '',
    product_name TEXT NOT NULL DEFAULT '',
    size_name TEXT NOT NULL DEFAULT '',
    warehouse_id TEXT NOT NULL DEFAULT '',
    warehouse_name TEXT NOT NULL DEFAULT '',
    region_name TEXT NOT NULL DEFAULT '',
    available INTEGER NOT NULL DEFAULT 0,
    reserved INTEGER NOT NULL DEFAULT 0,
    in_way_to_customer INTEGER NOT NULL DEFAULT 0,
    in_way_from_customer INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_reports_marketplace_date ON report_runs(marketplace, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_stock_report ON stock_items(report_id);
CREATE INDEX IF NOT EXISTS idx_stock_warehouse ON stock_items(report_id, warehouse_name);
CREATE INDEX IF NOT EXISTS idx_stock_product ON stock_items(report_id, offer_id, sku, vendor_code);
"""


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    return (dt or utc_now()).isoformat(timespec="seconds")


@contextmanager
def connect(settings: Settings | None = None):
    cfg = settings or get_settings()
    cfg.ensure_directories()
    conn = sqlite3.connect(cfg.database_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(settings: Settings | None = None) -> None:
    with connect(settings) as conn:
        conn.executescript(SCHEMA)


def start_report(marketplace: str, settings: Settings | None = None) -> int:
    with connect(settings) as conn:
        cur = conn.execute(
            "INSERT INTO report_runs(marketplace, started_at, status) VALUES (?, ?, 'running')",
            (marketplace, iso()),
        )
        return int(cur.lastrowid)


def finish_report(report_id: int, rows: list[dict[str, Any]], raw_file: str | None, settings: Settings | None = None) -> None:
    warehouses = {(str(r.get('warehouse_id', '')), str(r.get('warehouse_name', ''))) for r in rows}
    total_available = sum(int(r.get("available", 0) or 0) for r in rows)
    total_reserved = sum(int(r.get("reserved", 0) or 0) for r in rows)
    values = []
    for r in rows:
        values.append((
            report_id, r.get("marketplace", ""), r.get("fulfillment_type", ""),
            str(r.get("product_id", "") or ""), str(r.get("sku", "") or ""),
            str(r.get("offer_id", "") or ""), str(r.get("vendor_code", "") or ""),
            str(r.get("barcode", "") or ""), str(r.get("product_name", "") or ""),
            str(r.get("size_name", "") or ""), str(r.get("warehouse_id", "") or ""),
            str(r.get("warehouse_name", "") or ""), str(r.get("region_name", "") or ""),
            int(r.get("available", 0) or 0), int(r.get("reserved", 0) or 0),
            int(r.get("in_way_to_customer", 0) or 0), int(r.get("in_way_from_customer", 0) or 0),
            json.dumps(r.get("raw", {}), ensure_ascii=False, separators=(",", ":")),
        ))
    with connect(settings) as conn:
        conn.executemany("""
            INSERT INTO stock_items(
                report_id, marketplace, fulfillment_type, product_id, sku, offer_id,
                vendor_code, barcode, product_name, size_name, warehouse_id, warehouse_name,
                region_name, available, reserved, in_way_to_customer, in_way_from_customer, raw_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, values)
        conn.execute("""
            UPDATE report_runs SET collected_at=?, status='success', rows_count=?, warehouses_count=?,
            total_available=?, total_reserved=?, raw_file=? WHERE id=?
        """, (iso(), len(rows), len(warehouses), total_available, total_reserved, raw_file, report_id))


def fail_report(report_id: int, error: Exception | str, settings: Settings | None = None) -> None:
    with connect(settings) as conn:
        conn.execute(
            "UPDATE report_runs SET collected_at=?, status='failed', error_message=? WHERE id=?",
            (iso(), str(error)[:4000], report_id),
        )


def list_reports(marketplace: str | None = None, limit: int = 100, settings: Settings | None = None) -> list[dict]:
    sql = "SELECT * FROM report_runs"
    params: list[Any] = []
    if marketplace:
        sql += " WHERE marketplace=?"
        params.append(marketplace)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_report(report_id: int, settings: Settings | None = None) -> dict | None:
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM report_runs WHERE id=?", (report_id,)).fetchone()
        return dict(row) if row else None


def latest_report(marketplace: str, settings: Settings | None = None) -> dict | None:
    with connect(settings) as conn:
        row = conn.execute(
            "SELECT * FROM report_runs WHERE marketplace=? AND status='success' ORDER BY id DESC LIMIT 1",
            (marketplace,),
        ).fetchone()
        return dict(row) if row else None


def report_items(report_id: int, q: str | None = None, warehouse: str | None = None,
                 limit: int = 500, offset: int = 0, settings: Settings | None = None) -> list[dict]:
    conditions = ["report_id=?"]
    params: list[Any] = [report_id]
    if q:
        conditions.append("(offer_id LIKE ? OR sku LIKE ? OR vendor_code LIKE ? OR product_name LIKE ? OR barcode LIKE ?)")
        token = f"%{q}%"
        params.extend([token] * 5)
    if warehouse:
        conditions.append("warehouse_name=?")
        params.append(warehouse)
    params.extend([limit, offset])
    with connect(settings) as conn:
        rows = conn.execute(
            f"SELECT * FROM stock_items WHERE {' AND '.join(conditions)} ORDER BY warehouse_name, product_name, offer_id LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def all_report_items(report_id: int, settings: Settings | None = None) -> list[dict]:
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM stock_items WHERE report_id=? ORDER BY warehouse_name, product_name, offer_id", (report_id,)
        ).fetchall()]


def warehouse_summary(report_id: int, settings: Settings | None = None) -> list[dict]:
    with connect(settings) as conn:
        rows = conn.execute("""
            SELECT warehouse_id, warehouse_name, region_name, fulfillment_type,
                   COUNT(*) AS positions_count,
                   SUM(available) AS available,
                   SUM(reserved) AS reserved,
                   SUM(in_way_to_customer) AS in_way_to_customer,
                   SUM(in_way_from_customer) AS in_way_from_customer
            FROM stock_items WHERE report_id=?
            GROUP BY warehouse_id, warehouse_name, region_name, fulfillment_type
            ORDER BY warehouse_name, fulfillment_type
        """, (report_id,)).fetchall()
        return [dict(r) for r in rows]


def delete_expired_reports(cutoff: datetime, settings: Settings | None = None) -> list[str]:
    removed_files: list[str] = []
    with connect(settings) as conn:
        rows = conn.execute(
            "SELECT id, raw_file FROM report_runs WHERE COALESCE(collected_at, started_at) < ?",
            (iso(cutoff),),
        ).fetchall()
        ids = [r["id"] for r in rows]
        removed_files = [r["raw_file"] for r in rows if r["raw_file"]]
        if ids:
            conn.executemany("DELETE FROM report_runs WHERE id=?", [(i,) for i in ids])
    return removed_files


def oldest_deletable_report(settings: Settings | None = None) -> dict | None:
    with connect(settings) as conn:
        row = conn.execute("""
            SELECT * FROM report_runs
            WHERE id NOT IN (
                SELECT MAX(id) FROM report_runs WHERE marketplace='wb' AND status='success'
                UNION ALL
                SELECT MAX(id) FROM report_runs WHERE marketplace='ozon' AND status='success'
            )
            ORDER BY COALESCE(collected_at, started_at), id LIMIT 1
        """).fetchone()
        return dict(row) if row else None


def delete_report(report_id: int, settings: Settings | None = None) -> str | None:
    with connect(settings) as conn:
        row = conn.execute("SELECT raw_file FROM report_runs WHERE id=?", (report_id,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM report_runs WHERE id=?", (report_id,))
        return row["raw_file"]


def checkpoint(settings: Settings | None = None) -> None:
    with connect(settings) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA optimize")
