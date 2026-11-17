from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from config.settings import settings
from database.inventory_store import (
    INVENTORY_COLUMNS,
    delete_inventory_item,
    get_inventory,
    get_sales_history,
    upsert_inventory,
    upsert_sales_history,
)
from models.predictor import build_inventory_forecast
from utils.notifications import EmailSettings, get_email_settings, send_restock_alert


class InventoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = settings.DATABASE_PATH
        settings.DATABASE_PATH = Path(self.temp_dir.name) / "test.db"

    def tearDown(self) -> None:
        settings.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_inventory_upsert_persists_updates_and_delete(self) -> None:
        item = pd.DataFrame(
            [["Test Item", "Test", 10, 4, 2, 3, 5, "Supplier"]],
            columns=INVENTORY_COLUMNS,
        )
        upsert_inventory(item)
        item.loc[0, "current_stock"] = 7
        upsert_inventory(item)
        inventory = get_inventory()
        self.assertEqual(
            inventory.loc[inventory["item_name"] == "Test Item", "current_stock"].iloc[0],
            7,
        )
        delete_inventory_item("Test Item")
        self.assertNotIn("Test Item", get_inventory()["item_name"].tolist())

    def test_empty_inventory_does_not_reseed_sample_data(self) -> None:
        for item_name in get_inventory()["item_name"].tolist():
            delete_inventory_item(item_name)
        self.assertTrue(get_inventory().empty)
        self.assertTrue(get_inventory().empty)

    def test_inventory_validation_rejects_negative_stock(self) -> None:
        item = pd.DataFrame(
            [["Test Item", "Test", -1, 4, 2, 3, 5, "Supplier"]],
            columns=INVENTORY_COLUMNS,
        )
        with self.assertRaisesRegex(ValueError, "current_stock"):
            upsert_inventory(item)

    def test_sales_import_persists_and_updates_records(self) -> None:
        sales = pd.DataFrame(
            [["2026-01-01", "Test Item", 4], ["2026-01-02", "Test Item", 3]],
            columns=["date", "item_name", "quantity_sold"],
        )
        self.assertEqual(upsert_sales_history(sales), 2)
        sales.loc[0, "quantity_sold"] = 6
        self.assertEqual(upsert_sales_history(sales.iloc[[0]]), 1)
        self.assertEqual(get_sales_history().iloc[0]["quantity_sold"], 6)

    def test_ml_forecast_trains_with_28_days_of_sales(self) -> None:
        dates = pd.date_range("2026-01-01", periods=42, freq="D")
        sales = pd.DataFrame(
            {
                "date": dates,
                "item_name": "Test Item",
                "quantity_sold": [float(3 + date.dayofweek % 3) for date in dates],
            }
        )
        inventory = pd.DataFrame(
            [["Test Item", "Test", 20, 10, 4, 4, 5, "Supplier"]],
            columns=INVENTORY_COLUMNS,
        )
        result = build_inventory_forecast(inventory, sales)
        self.assertTrue(result.loc[0, "forecast_method"].startswith("ML: Random Forest"))
        self.assertGreater(result.loc[0, "forecasted_daily_demand"], 0)
        self.assertGreaterEqual(result.loc[0, "recommended_order_quantity"], 0)

    def test_short_history_is_labeled_as_baseline(self) -> None:
        sales = pd.DataFrame(
            [["2026-01-01", "Test Item", 5], ["2026-01-02", "Test Item", 3]],
            columns=["date", "item_name", "quantity_sold"],
        )
        inventory = pd.DataFrame(
            [["Test Item", "Test", 20, 10, 4, 4, 5, "Supplier"]],
            columns=INVENTORY_COLUMNS,
        )
        result = build_inventory_forecast(inventory, sales)
        self.assertIn("insufficient history", result.loc[0, "forecast_method"])
        self.assertEqual(result.loc[0, "forecasted_daily_demand"], 4)


class EmailNotificationTests(unittest.TestCase):
    def test_email_settings_require_host_sender_and_recipient(self) -> None:
        self.assertIsNone(get_email_settings({}))
        config = {
            "email": {
                "smtp_host": "smtp.example.com",
                "sender": "inventory@example.com",
                "recipient": "owner@example.com",
                "smtp_port": 465,
            }
        }
        result = get_email_settings(config)
        self.assertIsNotNone(result)
        self.assertEqual(result.port, 465)

    def test_email_settings_reject_partial_credentials(self) -> None:
        config = {
            "email": {
                "smtp_host": "smtp.example.com",
                "sender": "inventory@example.com",
                "recipient": "owner@example.com",
                "smtp_username": "inventory",
            }
        }
        with self.assertRaisesRegex(ValueError, "both smtp_username and smtp_password"):
            get_email_settings(config)

    @patch("utils.notifications.smtplib.SMTP_SSL")
    def test_restock_email_uses_tls_and_contains_recommendation(self, smtp_ssl) -> None:
        settings = EmailSettings(
            host="smtp.example.com",
            port=465,
            username="",
            password="",
            sender="inventory@example.com",
            recipient="owner@example.com",
        )
        send_restock_alert(
            settings,
            [
                {
                    "item_name": "Widget",
                    "risk_level": "High",
                    "current_stock": 2,
                    "recommended_order_quantity": 10,
                }
            ],
        )
        smtp_ssl.assert_called_once_with("smtp.example.com", 465, timeout=15)
        server = smtp_ssl.return_value.__enter__.return_value
        server.send_message.assert_called_once()
        self.assertIn("Widget", server.send_message.call_args.args[0].get_content())
        self.assertIn("10 units", server.send_message.call_args.args[0].get_content())


if __name__ == "__main__":
    unittest.main()
