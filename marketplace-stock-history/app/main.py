from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import get_report, init_db, latest_report, list_reports, report_items, warehouse_summary
from app.services import cleanup, collect_all, collect_marketplace, export_report

settings = get_settings()
init_db(settings)
app = FastAPI(title=settings.app_name, version="1.0.0")
security = HTTPBasic()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    username_ok = secrets.compare_digest(credentials.username.encode(), settings.web_username.encode())
    password_ok = secrets.compare_digest(credentials.password.encode(), settings.web_password.encode())
    if not (username_ok and password_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверные данные", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


@app.get("/health")
def health():
    return {"status": "ok", "database": str(settings.database_path), "retention_days": settings.retention_days}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _: str = Depends(auth)):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "reports": list_reports(limit=200, settings=settings),
        "wb": latest_report("wb", settings),
        "ozon": latest_report("ozon", settings),
    })


@app.get("/reports/{report_id}", response_class=HTMLResponse)
def report_page(request: Request, report_id: int, q: str | None = None, warehouse: str | None = None, _: str = Depends(auth)):
    report = get_report(report_id, settings)
    if not report:
        raise HTTPException(404, "Отчёт не найден")
    summary = warehouse_summary(report_id, settings)
    rows = report_items(report_id, q=q, warehouse=warehouse, limit=2000, settings=settings)
    return templates.TemplateResponse("report.html", {
        "request": request, "report": report, "summary": summary, "items": rows,
        "q": q or "", "warehouse": warehouse or "",
    })


@app.get("/api/reports")
def api_reports(marketplace: str | None = Query(None, pattern="^(wb|ozon)$"), limit: int = Query(100, ge=1, le=1000), _: str = Depends(auth)):
    return {"items": list_reports(marketplace, limit, settings)}


@app.get("/api/reports/latest/{marketplace}")
def api_latest(marketplace: str, _: str = Depends(auth)):
    if marketplace not in {"wb", "ozon"}:
        raise HTTPException(400, "marketplace должен быть wb или ozon")
    report = latest_report(marketplace, settings)
    if not report:
        raise HTTPException(404, "Успешный отчёт не найден")
    return {"report": report, "warehouse_summary": warehouse_summary(report["id"], settings), "items": report_items(report["id"], limit=250000, settings=settings)}


@app.get("/api/reports/{report_id}")
def api_report(report_id: int, _: str = Depends(auth)):
    report = get_report(report_id, settings)
    if not report:
        raise HTTPException(404, "Отчёт не найден")
    return {"report": report, "warehouse_summary": warehouse_summary(report_id, settings)}


@app.get("/api/reports/{report_id}/items")
def api_items(report_id: int, q: str | None = None, warehouse: str | None = None,
              limit: int = Query(500, ge=1, le=250000), offset: int = Query(0, ge=0), _: str = Depends(auth)):
    if not get_report(report_id, settings):
        raise HTTPException(404, "Отчёт не найден")
    return {"items": report_items(report_id, q, warehouse, limit, offset, settings)}


@app.get("/api/reports/{report_id}/download")
def download(report_id: int, format: str = Query("xlsx", pattern="^(xlsx|csv|json)$"), _: str = Depends(auth)):
    try:
        path = export_report(report_id, format, settings)
    except KeyError:
        raise HTTPException(404, "Отчёт не найден")
    return FileResponse(path, filename=path.name)


@app.post("/api/admin/collect/{marketplace}")
def admin_collect(marketplace: str, _: str = Depends(auth)):
    if marketplace == "all":
        return collect_all(settings)
    if marketplace not in {"wb", "ozon"}:
        raise HTTPException(400, "marketplace должен быть wb, ozon или all")
    return collect_marketplace(marketplace, settings)


@app.post("/api/admin/cleanup")
def admin_cleanup(_: str = Depends(auth)):
    return cleanup(settings)
