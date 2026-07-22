from __future__ import annotations

from typing import Any
import time

import httpx

from app.config import Settings, get_settings


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def first(obj: dict, *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return default


class ApiError(RuntimeError):
    pass


class WBClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _page(self, offset: int) -> dict:
        if not self.settings.wb_api_token:
            raise ApiError("WB_API_TOKEN не заполнен")
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                response = httpx.post(
                    self.settings.wb_stocks_url,
                    headers={"Authorization": self.settings.wb_api_token},
                    json={"nmIds": [], "chrtIds": [], "limit": self.settings.wb_page_limit, "offset": offset},
                    timeout=self.settings.request_timeout_seconds,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise ApiError(f"WB временная ошибка HTTP {response.status_code}: {response.text[:500]}")
                response.raise_for_status()
                return response.json()
            except (httpx.TransportError, ApiError) as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(min(2 ** (attempt + 1), 20))
        raise ApiError(str(last_error))

    def fetch(self) -> tuple[list[dict], list[dict]]:
        raw_pages: list[dict] = []
        result: list[dict] = []
        offset = 0
        while True:
            page = self._page(offset)
            raw_pages.append(page)
            items = page.get("data", {}).get("items", page.get("items", []))
            if not isinstance(items, list):
                raise ApiError("Неожиданная структура ответа WB: items не является массивом")
            for item in items:
                result.append({
                    "marketplace": "wb",
                    "fulfillment_type": "WB",
                    "product_id": first(item, "nmId"),
                    "sku": first(item, "chrtId"),
                    "offer_id": first(item, "supplierArticle", "vendorCode"),
                    "vendor_code": first(item, "supplierArticle", "vendorCode"),
                    "barcode": first(item, "barcode"),
                    "product_name": first(item, "title", "subjectName"),
                    "size_name": first(item, "techSize", "size"),
                    "warehouse_id": first(item, "warehouseId"),
                    "warehouse_name": first(item, "warehouseName"),
                    "region_name": first(item, "regionName"),
                    "available": as_int(first(item, "quantity", "available")),
                    "reserved": as_int(first(item, "reserved")),
                    "in_way_to_customer": as_int(first(item, "inWayToClient", "inWayToCustomer")),
                    "in_way_from_customer": as_int(first(item, "inWayFromClient", "inWayFromCustomer")),
                    "raw": item,
                })
            if len(items) < self.settings.wb_page_limit:
                break
            offset += len(items)
        return result, raw_pages


class OzonClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @property
    def headers(self) -> dict[str, str]:
        if not self.settings.ozon_client_id or not self.settings.ozon_api_key:
            raise ApiError("OZON_CLIENT_ID или OZON_API_KEY не заполнены")
        return {
            "Client-Id": self.settings.ozon_client_id,
            "Api-Key": self.settings.ozon_api_key,
            "Content-Type": "application/json",
        }

    def _page(self, path: str, cursor: str | None, offset: int) -> dict:
        body: dict[str, Any] = {"limit": self.settings.ozon_page_limit}
        if cursor:
            body["cursor"] = cursor
        elif offset:
            body["offset"] = offset
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                response = httpx.post(
                    self.settings.ozon_api_base.rstrip("/") + "/" + path.lstrip("/"),
                    headers=self.headers,
                    json=body,
                    timeout=self.settings.request_timeout_seconds,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise ApiError(f"Ozon временная ошибка HTTP {response.status_code}: {response.text[:500]}")
                response.raise_for_status()
                return response.json()
            except (httpx.TransportError, ApiError) as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(min(2 ** (attempt + 1), 20))
        raise ApiError(str(last_error))

    @staticmethod
    def _items(page: dict) -> list[dict]:
        result = page.get("result")
        candidates = [page.get("items")]
        if isinstance(result, dict):
            candidates.extend([result.get("items"), result.get("stocks")])
        elif isinstance(result, list):
            candidates.append(result)
        for value in candidates:
            if isinstance(value, list):
                return value
        return []

    @staticmethod
    def _cursor(page: dict) -> tuple[str | None, bool | None]:
        result = page.get("result") if isinstance(page.get("result"), dict) else {}
        cursor = first(page, "cursor", "next_cursor", default=None) or first(result, "cursor", "next_cursor", default=None)
        has_next = first(page, "has_next", default=None)
        if has_next is None:
            has_next = first(result, "has_next", default=None)
        return cursor, has_next

    @staticmethod
    def normalize_item(item: dict, fulfillment: str) -> list[dict]:
        product = item.get("product") if isinstance(item.get("product"), dict) else {}
        warehouse = item.get("warehouse") if isinstance(item.get("warehouse"), dict) else {}
        stocks = item.get("stocks")
        if isinstance(stocks, list) and stocks and any(isinstance(s, dict) for s in stocks):
            rows = []
            for stock in stocks:
                if not isinstance(stock, dict):
                    continue
                merged = {**item, **stock}
                merged.pop("stocks", None)
                if isinstance(stock.get("warehouse"), dict):
                    merged["warehouse"] = stock["warehouse"]
                rows.extend(OzonClient.normalize_item(merged, fulfillment))
            return rows

        warehouse_id = first(item, "warehouse_id", "warehouseId") or first(warehouse, "id", "warehouse_id")
        warehouse_name = first(item, "warehouse_name", "warehouseName") or first(warehouse, "name", "warehouse_name")
        region_name = first(item, "region_name", "regionName") or first(warehouse, "region", "region_name")
        present = first(item, "present", "available", "free_to_sell_amount", "stock", "quantity", default=0)
        reserved = first(item, "reserved", "reserved_amount", default=0)
        row = {
            "marketplace": "ozon",
            "fulfillment_type": fulfillment,
            "product_id": first(item, "product_id", "productId") or first(product, "id", "product_id"),
            "sku": first(item, "sku", "fbo_sku", "fbs_sku") or first(product, "sku"),
            "offer_id": first(item, "offer_id", "offerId") or first(product, "offer_id", "offerId"),
            "vendor_code": first(item, "offer_id", "offerId") or first(product, "offer_id", "offerId"),
            "barcode": first(item, "barcode") or first(product, "barcode"),
            "product_name": first(item, "name", "product_name") or first(product, "name", "product_name"),
            "size_name": first(item, "size", "size_name"),
            "warehouse_id": warehouse_id,
            "warehouse_name": warehouse_name,
            "region_name": region_name,
            "available": as_int(present),
            "reserved": as_int(reserved),
            "in_way_to_customer": as_int(first(item, "in_way_to_customer", "inWayToCustomer")),
            "in_way_from_customer": as_int(first(item, "in_way_from_customer", "inWayFromCustomer")),
            "raw": item,
        }
        return [row]

    def _fetch_endpoint(self, path: str, fulfillment: str) -> tuple[list[dict], list[dict]]:
        rows: list[dict] = []
        pages: list[dict] = []
        cursor: str | None = None
        offset = 0
        seen_cursors: set[str] = set()
        while True:
            page = self._page(path, cursor, offset)
            pages.append({"path": path, "response": page})
            items = self._items(page)
            for item in items:
                if isinstance(item, dict):
                    rows.extend(self.normalize_item(item, fulfillment))
            next_cursor, has_next = self._cursor(page)
            if next_cursor and next_cursor not in seen_cursors and has_next is not False:
                seen_cursors.add(next_cursor)
                cursor = next_cursor
                continue
            if has_next is True and len(items) >= self.settings.ozon_page_limit:
                offset += len(items)
                cursor = None
                continue
            if len(items) >= self.settings.ozon_page_limit and next_cursor is None and has_next is None:
                offset += len(items)
                continue
            break
        return rows, pages

    def fetch(self) -> tuple[list[dict], list[dict]]:
        all_rows: list[dict] = []
        all_pages: list[dict] = []
        for path, fulfillment in (
            (self.settings.ozon_fbs_stocks_path, "FBS"),
            (self.settings.ozon_fbo_stocks_path, "FBO"),
        ):
            if not path.strip():
                continue
            rows, pages = self._fetch_endpoint(path, fulfillment)
            all_rows.extend(rows)
            all_pages.extend(pages)
        unique: dict[tuple, dict] = {}
        for row in all_rows:
            key = (
                row["fulfillment_type"], str(row["product_id"]), str(row["sku"]),
                str(row["offer_id"]), str(row["warehouse_id"]), str(row["warehouse_name"]),
            )
            unique[key] = row
        return list(unique.values()), all_pages
