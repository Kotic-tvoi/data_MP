# Marketplace Stock History

Сервис каждый час получает остатки Wildberries и Ozon, сохраняет полный снимок в SQLite и показывает историю на сайте.

## Что сохраняется

Каждая строка отчёта — конкретный товар на конкретном складе:

- маркетплейс и схема поставки;
- SKU / offer ID / артикул;
- ID и название склада;
- регион склада;
- доступное количество;
- резерв;
- товары в пути к покупателю и от покупателя.

В XLSX есть два листа: `Товары по складам` и `Сводка по складам`.

## Хранение

- снимки БД, исходные `.json.gz` и сформированные выгрузки хранятся **10 суток**;
- всё более старое удаляется ежедневной задачей;
- если каталог данных превышает `MAX_DATA_SIZE_GB` или свободного места меньше `MIN_FREE_SPACE_GB`, запускается дополнительное удаление самых старых отчётов;
- последний успешный отчёт WB и Ozon сохраняется даже при аварийной очистке.

## Быстрый запуск Docker

```bash
cp .env.example .env
# заполнить токены и WEB_PASSWORD
docker compose up -d --build
```

Сайт: `http://SERVER_IP:8000`

## Запуск без Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.cli init-db
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Ручной сбор:

```bash
python -m app.cli collect all
python -m app.cli collect wb
python -m app.cli collect ozon
```

Очистка:

```bash
python -m app.cli cleanup
```

## Почасовой запуск через cron

```cron
5 * * * * cd /opt/marketplace-stock-history && /opt/marketplace-stock-history/.venv/bin/python -m app.cli collect all >> /var/log/stock-collector.log 2>&1
20 3 * * * cd /opt/marketplace-stock-history && /opt/marketplace-stock-history/.venv/bin/python -m app.cli cleanup >> /var/log/stock-cleanup.log 2>&1
```

## API

Все маршруты, кроме `/health`, защищены HTTP Basic.

- `GET /api/reports?marketplace=wb`
- `GET /api/reports/latest/wb`
- `GET /api/reports/latest/ozon`
- `GET /api/reports/{report_id}`
- `GET /api/reports/{report_id}/items`
- `GET /api/reports/{report_id}/download?format=xlsx`
- `POST /api/admin/collect/all`
- `POST /api/admin/cleanup`

## Настройка Ozon

Сервис использует отдельные складские методы:

- FBS/rFBS: `OZON_FBS_STOCKS_PATH`;
- FBO: `OZON_FBO_STOCKS_PATH`.

Пути вынесены в `.env`, чтобы их можно было заменить без изменения кода при обновлении Seller API. Ответы Ozon нормализуются из распространённых структур `items`, `result.items`, `result` и вложенных `stocks`.

## Проверка

```bash
pytest -q
```

Для полноценного интеграционного теста нужны действующие токены WB и Ozon. Секреты не коммитятся в Git.
