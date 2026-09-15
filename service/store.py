"""Frozen in-memory inventory data for the dashboard service.

The demo deployment serves a fixed catalog; a real deployment would back
this module with the warehouse inventory database.
"""

from __future__ import annotations


# Frozen demo inventory: sku -> units on hand.
INVENTORY: dict[str, int] = {
    "SKU-MAPLE-12": 34,
    "SKU-BIRCH-24": 8,
    "SKU-OAK-36": 25,
    "SKU-PINE-48": 12,
    "SKU-CEDAR-51": 41,
    "SKU-WALNUT-63": 5,
}
