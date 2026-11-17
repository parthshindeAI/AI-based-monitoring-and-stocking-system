from __future__ import annotations

import os
from pathlib import Path


class Settings:
    APP_NAME = "AI Monitoring and Stocking System"
    ROOT_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = ROOT_DIR / "data"
    SAMPLE_DATA_PATH = DATA_DIR / "sample_data.csv"
    DATABASE_PATH = Path(os.getenv("INVENTORY_DATABASE_PATH", DATA_DIR / "inventory.db"))
    FORECAST_DAYS = 7
    DEFAULT_REORDER_BUFFER = 5


settings = Settings()
