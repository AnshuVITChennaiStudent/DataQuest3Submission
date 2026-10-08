"""Global System State & Utilities for DQPS.

Defines a strict, shared state schema that flows down the entire pipeline.
Every agent reads from and writes to this single state object so transitions
are auditable end-to-end. Keeping the schema in one place avoids the "mismatched
keys between data silos" problem that Agent A exists to resolve.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Canonical key maps
# ---------------------------------------------------------------------------
# Different upstream data sources use different field names for the same
# concept. Agent A normalizes everything against these canonical keys.
STORE_INVENTORY_KEY_MAP: dict[str, str] = {
    "sku": "product_sku",
    "product_id": "product_sku",
    "stock": "inventory_stock",
    "units_in_stock": "inventory_stock",
    "qty": "inventory_stock",
    "price": "price_usd",
    "cost": "cogs_usd",
    "ship_cost": "logistics_usd",
    "shipping": "logistics_usd",
}

AD_NETWORK_KEY_MAP: dict[str, str] = {
    "ad_id": "ad_id",
    "campaign_id": "campaign_id",
    "spend": "spend_usd",
    "daily_budget": "active_daily_budget",
    "budget": "active_daily_budget",
    "ctr": "current_ctr",
    "hist_ctr": "historical_ctr",
    "historical_ctr_3d": "historical_ctr",
    "freq": "frequency",
    "frequency": "frequency",
    "network": "platform",
}


# ---------------------------------------------------------------------------
# Shared state schema
# ---------------------------------------------------------------------------
@dataclass
class ProductRecord:
    """A single normalized product + its ad telemetry."""

    product_sku: str
    product_name: str
    price_usd: float
    cogs_usd: float
    logistics_usd: float

    # Inventory
    inventory_stock: int

    # Live ad telemetry (one record per active ad / platform)
    platform: str = "Meta"
    ad_id: str = ""
    campaign_id: str = ""
    spend_usd: float = 0.0
    active_daily_budget: float = 0.0
    current_ctr: float = 0.0
    historical_ctr: float = 0.0
    frequency: float = 0.0

    # Computed downstream (filled by engine / agents)
    net_margin_pct: float = 0.0
    mroas: float = 0.0
    creative_fatigue: bool = False
    inventory_suppressed: bool = False
    safety_breach_flag: bool = False
    proposed_daily_budget: float = 0.0
    budget_delta_pct: float = 0.0


@dataclass
class SystemState:
    """The strict shared state object threaded through the orchestrator."""

    products: list[ProductRecord] = field(default_factory=list)
    engine_diagnostic_log: list[dict[str, Any]] = field(default_factory=list)
    safety_breach_flag: bool = False
    outbound_api_payload: dict[str, Any] = field(default_factory=dict)
    cycle_id: int = 0
    target_floor_roas: float = 1.8
    max_budget_variance_pct: float = 20.0

    # Platform curve parameters for the diminishing-returns mROAS model.
    platform_params: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "Meta": {"alpha": 3.5, "beta": 0.0015},
        "Google": {"alpha": 2.8, "beta": 0.0008},
    })

    def log(self, agent: str, event: str, detail: str, level: str = "INFO") -> None:
        """Append a structured diagnostic line to the engine log."""
        self.engine_diagnostic_log.append({
            "cycle": self.cycle_id,
            "agent": agent,
            "event": event,
            "detail": detail,
            "level": level,
        })

    def snapshot(self) -> SystemState:
        """Deep copy so downstream callers cannot mutate mid-flight."""
        return deepcopy(self)


def build_initial_state(seed_products: list[dict[str, Any]]) -> SystemState:
    """Construct the initial SystemState from raw (possibly mismatched) dicts.

    Raw dicts intentionally use mismatched keys on purpose so Agent A can
    demonstrate its normalization role in the live dashboard.
    """
    state = SystemState()
    for raw in seed_products:
        rec = ProductRecord(
            product_sku=raw.get("product_sku", raw.get("sku", raw.get("product_id", "UNKNOWN"))),
            product_name=raw.get("product_name", "Untitled Product"),
            price_usd=float(raw.get("price_usd", raw.get("price", 0.0))),
            cogs_usd=float(raw.get("cogs_usd", raw.get("cost", 0.0))),
            logistics_usd=float(raw.get("logistics_usd", raw.get("ship_cost", raw.get("shipping", 0.0)))),
            inventory_stock=int(raw.get("inventory_stock", raw.get("stock", raw.get("qty", 0)))),
            platform=raw.get("platform", "Meta"),
            ad_id=raw.get("ad_id", ""),
            campaign_id=raw.get("campaign_id", ""),
            spend_usd=float(raw.get("spend_usd", raw.get("spend", 0.0))),
            active_daily_budget=float(raw.get("active_daily_budget", raw.get("daily_budget", raw.get("budget", 0.0)))),
            current_ctr=float(raw.get("current_ctr", raw.get("ctr", 0.0))),
            historical_ctr=float(raw.get("historical_ctr", raw.get("hist_ctr", raw.get("historical_ctr_3d", 0.0)))),
            frequency=float(raw.get("frequency", raw.get("freq", 0.0))),
        )
        state.products.append(rec)
    return state


# Seed data used by the dashboard when no other source is supplied.
DEFAULT_SEED_PRODUCTS: list[dict[str, Any]] = [
    {
        "product_sku": "DQPS-001",
        "product_name": "Aurora Hydrating Serum",
        "price": 48.00,
        "cost": 11.50,
        "ship_cost": 4.20,
        "stock": 142,
        "platform": "Meta",
        "ad_id": "meta_ad_8841",
        "campaign_id": "camp_meta_aurora",
        "spend": 620.00,
        "daily_budget": 750.00,
        "ctr": 0.0218,
        "historical_ctr_3d": 0.0295,
        "freq": 4.6,
    },
    {
        "product_sku": "DQPS-002",
        "product_name": "Nimbus Wireless Earbuds",
        "price": 129.00,
        "cost": 38.00,
        "ship_cost": 6.75,
        "stock": 8,
        "platform": "Google",
        "ad_id": "google_ad_2207",
        "campaign_id": "camp_google_nimbus",
        "spend": 410.00,
        "daily_budget": 500.00,
        "ctr": 0.0162,
        "hist_ctr": 0.0190,
        "frequency": 2.1,
    },
    {
        "product_sku": "DQPS-003",
        "product_name": "Verdant Matcha Kit",
        "price": 64.00,
        "cost": 17.25,
        "ship_cost": 5.10,
        "stock": 73,
        "platform": "Meta",
        "ad_id": "meta_ad_5530",
        "campaign_id": "camp_meta_verdant",
        "spend": 285.00,
        "daily_budget": 320.00,
        "ctr": 0.0188,
        "historical_ctr": 0.0196,
        "freq": 3.1,
    },
    {
        "product_sku": "DQPS-004",
        "product_name": "Lumen Desk Lamp",
        "price": 89.00,
        "cost": 29.40,
        "ship_cost": 7.80,
        "stock": 35,
        "platform": "Google",
        "ad_id": "google_ad_9912",
        "campaign_id": "camp_google_lumen",
        "spend": 198.00,
        "daily_budget": 240.00,
        "ctr": 0.0141,
        "historical_ctr": 0.0138,
        "frequency": 1.9,
    },
]
