"""Backward-compatible inventory access import.

Inventory persistence is provided by the local SQLite store.
"""

from database.inventory_store import get_inventory


def fetch_inventory_data():
    return get_inventory()
