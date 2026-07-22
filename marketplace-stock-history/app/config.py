from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Marketplace Stock History"
    database_path: Path = Path("./data/stocks.sqlite3")
    data_dir: Path = Path("./data")
    retention_days: int = 10
    max_data_size_gb: float = 10
    min_free_space_gb: float = 3
    request_timeout_seconds: float = 60

    web_username: str = "admin"
    web_password: str = "change-me"

    wb_api_token: str = ""
    wb_stocks_url: str = "https://seller-analytics-api.wildberries.ru/api/analytics/v1/stocks-report/wb-warehouses"
    wb_page_limit: int = 250_000

    ozon_client_id: str = ""
    ozon_api_key: str = ""
    ozon_api_base: str = "https://api-seller.ozon.ru"
    ozon_fbs_stocks_path: str = "/v2/product/info/stocks-by-warehouse/fbs"
    ozon_fbo_stocks_path: str = "/v1/product/info/stocks-by-warehouse/fbo"
    ozon_page_limit: int = 1_000

    collect_interval_seconds: int = 3_600

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
