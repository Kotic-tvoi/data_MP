from __future__ import annotations

import argparse
import json
import time

from app.config import get_settings
from app.db import init_db
from app.services import cleanup, collect_all, collect_marketplace


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("marketplace", choices=["wb", "ozon", "all"])
    sub.add_parser("cleanup")
    sub.add_parser("loop")
    args = parser.parse_args()
    settings = get_settings()

    if args.command == "init-db":
        init_db(settings)
        print(settings.database_path)
    elif args.command == "cleanup":
        print(json.dumps(cleanup(settings), ensure_ascii=False, indent=2))
    elif args.command == "collect":
        result = collect_all(settings) if args.marketplace == "all" else collect_marketplace(args.marketplace, settings)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "loop":
        init_db(settings)
        while True:
            started = time.monotonic()
            print(json.dumps(collect_all(settings), ensure_ascii=False), flush=True)
            elapsed = time.monotonic() - started
            time.sleep(max(60, settings.collect_interval_seconds - elapsed))


if __name__ == "__main__":
    main()
