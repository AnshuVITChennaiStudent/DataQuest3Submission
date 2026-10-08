from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.state import DEFAULT_SEED_PRODUCTS

DEFAULT_STORE_PATH = Path(__file__).with_name("inventory.json")


def normalize_product(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a product payload to the canonical schema used across the app."""
    product_sku = str(raw.get("product_sku") or raw.get("sku") or raw.get("product_id") or "NEW-ITEM")
    product_name = str(raw.get("product_name") or raw.get("name") or "Untitled Product")

    return {
        "product_sku": product_sku,
        "product_name": product_name,
        "price": float(raw.get("price", raw.get("price_usd", 0.0)) or 0.0),
        "cost": float(raw.get("cost", raw.get("cogs_usd", 0.0)) or 0.0),
        "ship_cost": float(raw.get("ship_cost", raw.get("logistics_usd", raw.get("shipping", 0.0))) or 0.0),
        "stock": int(raw.get("stock", raw.get("inventory_stock", raw.get("qty", 0))) or 0),
        "platform": str(raw.get("platform") or "Meta"),
        "ad_id": str(raw.get("ad_id") or ""),
        "campaign_id": str(raw.get("campaign_id") or ""),
        "spend": float(raw.get("spend", raw.get("spend_usd", 0.0)) or 0.0),
        "daily_budget": float(raw.get("daily_budget", raw.get("active_daily_budget", raw.get("budget", 0.0))) or 0.0),
        "ctr": float(raw.get("ctr", raw.get("current_ctr", 0.0)) or 0.0),
        "historical_ctr": float(raw.get("historical_ctr", raw.get("hist_ctr", raw.get("historical_ctr_3d", 0.0))) or 0.0),
        "frequency": float(raw.get("frequency", raw.get("freq", 0.0)) or 0.0),
    }


def get_seed_products() -> list[dict[str, Any]]:
    return [normalize_product(item) for item in DEFAULT_SEED_PRODUCTS]


def load_products(store_path: str | Path = DEFAULT_STORE_PATH) -> list[dict[str, Any]]:
    path = Path(store_path)
    if not path.exists():
        save_products(get_seed_products(), path)

    try:
        parsed = json.loads(path.read_text())
    except json.JSONDecodeError:
        save_products(get_seed_products(), path)
        parsed = json.loads(path.read_text())

    if not isinstance(parsed, list):
        save_products(get_seed_products(), path)
        parsed = json.loads(path.read_text())

    return [normalize_product(item) for item in parsed]


def save_products(products: Iterable[Mapping[str, Any]], store_path: str | Path = DEFAULT_STORE_PATH) -> list[dict[str, Any]]:
    path = Path(store_path)
    normalized = [normalize_product(item) for item in products]
    path.write_text(json.dumps(normalized, indent=2))
    return normalized


def append_product(product: Mapping[str, Any], store_path: str | Path = DEFAULT_STORE_PATH) -> list[dict[str, Any]]:
    existing = load_products(store_path)
    updated = [*existing, normalize_product(product)]
    return save_products(updated, store_path)


if __name__ == "__main__":
    print(json.dumps(load_products(), indent=2))
