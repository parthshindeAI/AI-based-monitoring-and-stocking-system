from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from config.settings import settings

INVENTORY_COLUMNS = [
    "item_name",
    "category",
    "current_stock",
    "reorder_point",
    "daily_demand",
    "lead_time_days",
    "unit_price",
    "supplier",
]
NUMERIC_COLUMNS = [
    "current_stock",
    "reorder_point",
    "daily_demand",
    "lead_time_days",
    "unit_price",
]
SALES_COLUMNS = ["date", "item_name", "quantity_sold"]


def _connect() -> sqlite3.Connection:
    db_path: Path = settings.DATABASE_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def normalize_inventory(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(INVENTORY_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Inventory data is missing columns: {', '.join(sorted(missing))}")

    normalized = frame[INVENTORY_COLUMNS].copy()
    normalized["item_name"] = normalized["item_name"].fillna("").astype(str).str.strip()
    normalized["category"] = normalized["category"].fillna("General").astype(str).str.strip()
    normalized["supplier"] = normalized["supplier"].fillna("").astype(str).str.strip()
    if normalized["item_name"].eq("").any():
        raise ValueError("Every inventory item must have a name.")
    if normalized["item_name"].duplicated(keep=False).any():
        duplicates = normalized.loc[normalized["item_name"].duplicated(keep=False), "item_name"].unique()
        raise ValueError(f"Duplicate item names are not allowed: {', '.join(duplicates)}")

    for column in NUMERIC_COLUMNS:
        normalized[column] = pd.to_numeric(normalized[column], errors="raise")
        if (
            normalized[column].isna().any()
            or not np.isfinite(normalized[column]).all()
            or (normalized[column] < 0).any()
        ):
            raise ValueError(f"{column} must contain non-negative numbers.")
    if (normalized["lead_time_days"] < 0).any():
        raise ValueError("lead_time_days must be non-negative.")
    return normalized


def initialize_database() -> None:
    is_new_database = not settings.DATABASE_PATH.exists()
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory (
                item_name TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                current_stock REAL NOT NULL CHECK (current_stock >= 0),
                reorder_point REAL NOT NULL CHECK (reorder_point >= 0),
                daily_demand REAL NOT NULL CHECK (daily_demand >= 0),
                lead_time_days REAL NOT NULL CHECK (lead_time_days >= 0),
                unit_price REAL NOT NULL CHECK (unit_price >= 0),
                supplier TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sales_history (
                date TEXT NOT NULL,
                item_name TEXT NOT NULL,
                quantity_sold REAL NOT NULL CHECK (quantity_sold >= 0),
                PRIMARY KEY (date, item_name)
            )
            """
        )
        if is_new_database and settings.SAMPLE_DATA_PATH.exists():
            sample = pd.read_csv(settings.SAMPLE_DATA_PATH)
            if not sample.empty:
                upsert_inventory(sample, connection=connection)


def get_inventory() -> pd.DataFrame:
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            f"SELECT {', '.join(INVENTORY_COLUMNS)} FROM inventory ORDER BY item_name"
        ).fetchall()
    return pd.DataFrame(rows, columns=INVENTORY_COLUMNS)


def upsert_inventory(frame: pd.DataFrame, connection: sqlite3.Connection | None = None) -> None:
    normalized = normalize_inventory(frame)
    if connection is None:
        initialize_database()
        with _connect() as active_connection:
            _upsert_inventory(active_connection, normalized)
        return
    _upsert_inventory(connection, normalized)


def _upsert_inventory(connection: sqlite3.Connection, normalized: pd.DataFrame) -> None:
    values = [tuple(row) for row in normalized.itertuples(index=False, name=None)]
    connection.executemany(
        """
        INSERT INTO inventory
            (item_name, category, current_stock, reorder_point, daily_demand,
             lead_time_days, unit_price, supplier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_name) DO UPDATE SET
            category = excluded.category,
            current_stock = excluded.current_stock,
            reorder_point = excluded.reorder_point,
            daily_demand = excluded.daily_demand,
            lead_time_days = excluded.lead_time_days,
            unit_price = excluded.unit_price,
            supplier = excluded.supplier
        """,
        values,
    )


def delete_inventory_item(item_name: str) -> None:
    initialize_database()
    with _connect() as connection:
        connection.execute("DELETE FROM inventory WHERE item_name = ?", (item_name,))


def get_sales_history() -> pd.DataFrame:
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT date, item_name, quantity_sold FROM sales_history ORDER BY date, item_name"
        ).fetchall()
    return pd.DataFrame(rows, columns=SALES_COLUMNS)


def upsert_sales_history(frame: pd.DataFrame) -> int:
    missing = set(SALES_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Sales data is missing columns: {', '.join(sorted(missing))}")
    normalized = frame[SALES_COLUMNS].copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="raise").dt.strftime("%Y-%m-%d")
    normalized["item_name"] = normalized["item_name"].fillna("").astype(str).str.strip()
    normalized["quantity_sold"] = pd.to_numeric(normalized["quantity_sold"], errors="raise")
    if normalized["item_name"].eq("").any():
        raise ValueError("Every sales record must have an item name.")
    if (
        normalized["quantity_sold"].isna().any()
        or not np.isfinite(normalized["quantity_sold"]).all()
        or (normalized["quantity_sold"] < 0).any()
    ):
        raise ValueError("quantity_sold must contain non-negative numbers.")
    if normalized.duplicated(["date", "item_name"], keep=False).any():
        raise ValueError("Sales data may contain only one record per item per date.")

    initialize_database()
    values = [tuple(row) for row in normalized.itertuples(index=False, name=None)]
    with _connect() as connection:
        connection.executemany(
            """
            INSERT INTO sales_history (date, item_name, quantity_sold)
            VALUES (?, ?, ?)
            ON CONFLICT(date, item_name) DO UPDATE SET quantity_sold = excluded.quantity_sold
            """,
            values,
        )
    return len(values)
