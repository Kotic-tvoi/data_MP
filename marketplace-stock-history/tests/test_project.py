from pathlib import Path

from app.clients import OzonClient
from app.config import Settings
from app.db import all_report_items, finish_report, init_db, latest_report, start_report, warehouse_summary
from app.services import export_report


def test_ozon_nested_stocks_are_split_by_warehouse():
    item = {
        "product_id": 10, "offer_id": "A-1", "sku": 99,
        "stocks": [
            {"warehouse_id": 1, "warehouse_name": "Москва", "present": 7, "reserved": 2},
            {"warehouse_id": 2, "warehouse_name": "Санкт-Петербург", "present": 4, "reserved": 1},
        ],
    }
    rows = OzonClient.normalize_item(item, "FBS")
    assert [(r["warehouse_name"], r["available"]) for r in rows] == [("Москва", 7), ("Санкт-Петербург", 4)]


def test_database_and_xlsx_warehouse_summary(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "stocks.sqlite3", data_dir=tmp_path, web_password="test")
    init_db(settings)
    report_id = start_report("wb", settings)
    rows = [
        {"marketplace":"wb","fulfillment_type":"WB","product_id":"1","sku":"11","offer_id":"A","warehouse_id":"101","warehouse_name":"Коледино","available":5,"reserved":1,"raw":{}},
        {"marketplace":"wb","fulfillment_type":"WB","product_id":"2","sku":"22","offer_id":"B","warehouse_id":"101","warehouse_name":"Коледино","available":8,"reserved":0,"raw":{}},
        {"marketplace":"wb","fulfillment_type":"WB","product_id":"1","sku":"11","offer_id":"A","warehouse_id":"202","warehouse_name":"Казань","available":3,"reserved":0,"raw":{}},
    ]
    finish_report(report_id, rows, None, settings)
    assert latest_report("wb", settings)["rows_count"] == 3
    assert len(all_report_items(report_id, settings)) == 3
    summary = warehouse_summary(report_id, settings)
    assert {r["warehouse_name"]: r["available"] for r in summary} == {"Казань": 3, "Коледино": 13}
    path = export_report(report_id, "xlsx", settings)
    assert path.exists() and path.stat().st_size > 0
