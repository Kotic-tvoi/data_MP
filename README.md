# JKeratin Knowledge Base

Проект базы знаний для вопросов/ответов маркетплейсов JKeratin.

Основные части проекта:

- `data/jkeratin_kb.sqlite` — SQLite-база знаний.
- `data/schema.sql` — схема базы данных.
- `data/schema_metadata.json` — метаданные по импортированным листам Excel.
- `scripts/import_xlsx_to_sqlite.py` — импорт Excel-файла в SQLite.
- `scripts/search_cli.py` — консольный поиск по базе.
- `app/main.py` — FastAPI API для поиска и получения данных.

## Быстрый старт

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Запуск API:

```bash
uvicorn app.main:app --reload
```

Консольный поиск:

```bash
python scripts/search_cli.py "когда будет в наличии"
```

Импорт нового Excel-файла:

```bash
python scripts/import_xlsx_to_sqlite.py path/to/file.xlsx --db data/jkeratin_kb.sqlite
```
