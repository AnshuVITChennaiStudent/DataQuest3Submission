"""System Engine Core & Algorithmic Math for DQPS.

Pure functions that operate on a SystemState. No I/O, no side effects beyond
appending diagnostic log lines to the state so the dashboard can replay every
transition. Math uses numpy for the exponential decay derivative.
"""

from __future__ import annotations

import numpy as np

from state import ProductRecord, SystemState


# ---------------------------------------------------------------------------
# Product Margin Engine
# ---------------------------------------------------------------------------
def net_product_margin(price: float, cogs: float, logistics: float) -> float:
    """True Net Product Margin percentage M_p = (Price - COGS - Logistics) / Price.

    Returns a percentage in 0..1 form (e.g. 0.62 == 62%). We return a fraction
    rather than a percentage-point value because the mROAS derivative consumes
    the fraction directly.
    """
    if price <= 0:
        return 0.0
    return (price - cogs - logistics) / price


def compute_margins(state: SystemState) -> None:
    """Populate net_margin_pct for every product in state."""
    for p in state.products:
        p.net_margin_pct = net_product_margin(p.price_usd, p.cogs_usd, p.logistics_usd)
        state.log(
            agent="Engine",
            event="MARGIN_COMPUTED",
            detail=(
                f"{p.product_sku} ({p.product_name}) | "
                f"Price=${p.price_usd:.2f} COGS=${p.cogs_usd:.2f} Logistics=${p.logistics_usd:.2f} -> "
                f"Net Margin {p.net_margin_pct*100:.1f}%"
            ),
        )


# ---------------------------------------------------------------------------
# Marginal ROAS Calculator
# ---------------------------------------------------------------------------
def marginal_roas(budget: float, alpha: float, beta: float, margin: float) -> float:
    """Diminishing-returns yield derivative.

        mROAS = alpha * beta * exp(-beta * Budget) * M_p

    This is the derivative of the saturation curve ROAS(B) = alpha*(1 - exp(-beta*B))
    scaled by the product margin, so it represents the marginal incremental revenue
    per additional dollar of ad spend at the current budget level.
    """
    return float(alpha * beta * np.exp(-beta * budget) * margin)


def compute_mroas(state: SystemState) -> None:
    """Compute mROAS for every product using its platform's curve params."""
    for p in state.products:
        params = state.platform_params.get(p.platform)
        if not params:
            state.log(
                agent="Engine",
                event="MROAS_SKIP",
                detail=f"{p.product_sku} | unknown platform '{p.platform}', skipping",
                level="WARN",
            )
            p.mroas = 0.0
            continue
        p.mroas = marginal_roas(
            budget=p.active_daily_budget,
            alpha=params["alpha"],
            beta=params["beta"],
            margin=p.net_margin_pct,
        )
        state.log(
            agent="Engine",
            event="MROAS_COMPUTED",
            detail=(
                f"{p.product_sku} | platform={p.platform} alpha={params['alpha']} beta={params['beta']} "
                f"Budget=${p.active_daily_budget:.2f} M_p={p.net_margin_pct*100:.1f}% -> mROAS={p.mroas:.4f}"
            ),
        )


# ---------------------------------------------------------------------------
# Budget proposal (gradient-style step toward the floor ROAS)
# ---------------------------------------------------------------------------
def propose_budget(p: ProductRecord, state: SystemState) -> float:
    """Suggest a new daily budget for the product.

    Strategy: if mROAS is above the floor we have headroom to scale spend; if
    below the floor we should pull back. We move proportionally to the gap, but
    the Safety Gate later caps any single-cycle move at +/-20%.
    """
    floor = state.target_floor_roas
    gap = p.mroas - floor
    # Gentle gradient step: 15% of current budget scaled by the relative gap,
    # bounded to +/-15% so healthy products stay within the safety gate. The
    # creative-fatigue halving in the Diagnostic Brain is what creates larger
    # cuts that then trip the safety gate.
    step_factor = max(-0.15, min(0.15, (gap / max(floor, 1e-6)) * 0.15))
    proposed = p.active_daily_budget * (1.0 + step_factor)
    # Never propose negative or zero budgets.
    return max(proposed, 5.0)


def run_engine(state: SystemState) -> None:
    """Run the full math pass: margins -> mROAS -> budget proposals."""
    compute_margins(state)
    compute_mroas(state)
    for p in state.products:
        p.proposed_daily_budget = propose_budget(p, state)
        p.budget_delta_pct = (
            ((p.proposed_daily_budget - p.active_daily_budget) / p.active_daily_budget) * 100.0
            if p.active_daily_budget > 0
            else 0.0
        )
        state.log(
            agent="Engine",
            event="BUDGET_PROPOSED",
            detail=(
                f"{p.product_sku} | current=${p.active_daily_budget:.2f} proposed=${p.proposed_daily_budget:.2f} "
                f"delta={p.budget_delta_pct:+.1f}%"
            ),
        )
