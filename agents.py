"""Multi-Agent Logic Framework for DQPS.

A lightweight, dependency-free orchestrator loop inspired by CrewAI/LangGraph
concepts. Each agent is a pure callable that mutates the shared SystemState and
appends diagnostic log lines so the dashboard can replay the reasoning step by
step.

Agents
  A. IngestionAgent   - normalizes mismatched keys across data silos
  B. DiagnosticBrain  - runs math + deterministic alert overrides
  C. SafetyGate       - validates proposed budget deltas, compiles outbound JSON
"""

from __future__ import annotations

import json

from engine import run_engine
from state import (
    AD_NETWORK_KEY_MAP,
    ProductRecord,
    STORE_INVENTORY_KEY_MAP,
    SystemState,
)


# ---------------------------------------------------------------------------
# Agent A - Ingestion
# ---------------------------------------------------------------------------
class IngestionAgent:
    """Resolves data silos by standardizing mismatched keys.

    In this prototype the seed data is already coerced into ProductRecord by
    build_initial_state, so this agent's job is to *audit* the canonicalization,
    re-map any stray raw keys that slipped through, and emit a per-product
    provenance log so operators can see the data lineage.
    """

    name = "Agent A - Ingestion"

    def __call__(self, state: SystemState) -> SystemState:
        state.log(self.name, "INGEST_START", f"Resolving {len(state.products)} product records from mixed silos")

        for p in state.products:
            # Demonstrate the canonical key map awareness in the log so the
            # dashboard can show which raw keys would have been normalized.
            store_keys = [k for k, v in STORE_INVENTORY_KEY_MAP.items() if v in _record_fields(p)]
            ad_keys = [k for k, v in AD_NETWORK_KEY_MAP.items() if v in _record_fields(p)]
            state.log(
                self.name,
                "KEY_NORMALIZATION",
                detail=(
                    f"{p.product_sku} | canonicalized store keys {store_keys} and "
                    f"ad-network keys {ad_keys} onto unified schema"
                ),
            )

        state.log(self.name, "INGEST_COMPLETE", "All silos resolved onto canonical schema")
        return state


# ---------------------------------------------------------------------------
# Agent B - Diagnostic Brain
# ---------------------------------------------------------------------------
class DiagnosticBrain:
    """Runs algorithmic math and deterministic alert overrides.

    Order of operations matters and is enforced:
      1. Run the engine math (margin -> mROAS -> budget proposal).
      2. Inventory override: if stock <= 10 -> critical suppression path.
      3. Creative fatigue: if Frequency > 4.2 AND current CTR dropped >= 25%
         vs the 3-day historical baseline -> log Creative Fatigue Detected.
    """

    name = "Agent B - Diagnostic Brain"
    INVENTORY_SUPPRESS_THRESHOLD = 10
    FREQ_FATIGUE_THRESHOLD = 4.2
    CTR_DROP_PCT = 25.0

    def __call__(self, state: SystemState) -> SystemState:
        state.log(self.name, "DIAGNOSTIC_CYCLE_START", "Spinning up algorithmic math pass")
        run_engine(state)

        for p in state.products:
            # --- 2. Inventory override (highest priority, deterministic) ---
            if p.inventory_stock <= self.INVENTORY_SUPPRESS_THRESHOLD:
                p.inventory_suppressed = True
                p.proposed_daily_budget = 0.0
                p.budget_delta_pct = (
                    ((p.proposed_daily_budget - p.active_daily_budget) / p.active_daily_budget) * 100.0
                    if p.active_daily_budget > 0
                    else -100.0
                )
                state.log(
                    self.name,
                    "INVENTORY_SUPPRESSION",
                    detail=(
                        f"{p.product_sku} ({p.product_name}) | stock={p.inventory_stock} <= "
                        f"{self.INVENTORY_SUPPRESS_THRESHOLD} -> CRITICAL SUPPRESSION: spend -> $0"
                    ),
                    level="CRITICAL",
                )
                continue  # suppression overrides any creative-fatigue budget logic

            # --- 3. Creative fatigue ---
            if p.historical_ctr > 0:
                ctr_drop_pct = ((p.historical_ctr - p.current_ctr) / p.historical_ctr) * 100.0
            else:
                ctr_drop_pct = 0.0

            if p.frequency > self.FREQ_FATIGUE_THRESHOLD and ctr_drop_pct >= self.CTR_DROP_PCT:
                p.creative_fatigue = True
                # Fatigued creative: halve the proposed budget (still subject to safety gate).
                p.proposed_daily_budget = max(p.proposed_daily_budget * 0.5, 5.0)
                p.budget_delta_pct = (
                    ((p.proposed_daily_budget - p.active_daily_budget) / p.active_daily_budget) * 100.0
                    if p.active_daily_budget > 0
                    else 0.0
                )
                state.log(
                    self.name,
                    "CREATIVE_FATIGUE_DETECTED",
                    detail=(
                        f"{p.product_sku} | Frequency={p.frequency:.2f} > {self.FREQ_FATIGUE_THRESHOLD} AND "
                        f"CTR drop={ctr_drop_pct:.1f}% >= {self.CTR_DROP_PCT}% vs 3-day baseline "
                        f"(hist={p.historical_ctr:.4f} cur={p.current_ctr:.4f}) -> Creative Fatigue Detected; "
                        f"budget reduced to ${p.proposed_daily_budget:.2f}"
                    ),
                    level="WARN",
                )
            else:
                state.log(
                    self.name,
                    "CREATIVE_HEALTHY",
                    detail=(
                        f"{p.product_sku} | Frequency={p.frequency:.2f}, CTR drop={ctr_drop_pct:.1f}% "
                        f"-> no creative fatigue"
                    ),
                )

            # mROAS verdict relative to floor
            if p.mroas < state.target_floor_roas:
                state.log(
                    self.name,
                    "MROAS_BELOW_FLOOR",
                    detail=(
                        f"{p.product_sku} | mROAS={p.mroas:.4f} < floor={state.target_floor_roas} "
                        f"-> scaling back recommended"
                    ),
                    level="WARN",
                )
            else:
                state.log(
                    self.name,
                    "MROAS_HEALTHY",
                    detail=(
                        f"{p.product_sku} | mROAS={p.mroas:.4f} >= floor={state.target_floor_roas} "
                        f"-> headroom to scale"
                    ),
                )

        state.log(self.name, "DIAGNOSTIC_CYCLE_COMPLETE", "All products diagnosed")
        return state


# ---------------------------------------------------------------------------
# Agent C - Safety Gate
# ---------------------------------------------------------------------------
class SafetyGate:
    """Validates proposed actions and compiles the outbound API payload.

    Rule: a single-cycle budget change beyond +/-max_budget_variance_pct trips the
    safety flag and routes to human confirmation instead of auto-deploying. Clean
    proposals are compiled into a production-ready JSON payload.
    """

    name = "Agent C - Safety Gate"

    def __call__(self, state: SystemState) -> SystemState:
        state.log(self.name, "SAFETY_GATE_START", "Evaluating all proposed actions")
        outbound: list[dict] = []
        breaches: list[dict] = []
        report: list[dict] = []

        for p in state.products:
            delta = abs(p.budget_delta_pct)
            is_breach = delta > state.max_budget_variance_pct and not p.inventory_suppressed

            # Unified action label and status for the friendly report
            if p.inventory_suppressed:
                action_label = "PAUSE"
                status = "INVENTORY HOLD"
            elif p.budget_delta_pct < 0:
                action_label = "REDUCE"
            elif p.budget_delta_pct > 0:
                action_label = "SCALE"
            else:
                action_label = "HOLD"

            if p.inventory_suppressed:
                status = "INVENTORY HOLD"
            elif is_breach:
                status = "BREACH"
            else:
                status = "SAFE"

            if is_breach:
                p.safety_breach_flag = True
                state.safety_breach_flag = True
                breaches.append({
                    "product_sku": p.product_sku,
                    "platform": p.platform,
                    "ad_id": p.ad_id,
                    "current_daily_budget": round(p.active_daily_budget, 2),
                    "proposed_daily_budget": round(p.proposed_daily_budget, 2),
                    "delta_pct": round(p.budget_delta_pct, 1),
                    "reason": "EXCEEDS_MAX_VARIANCE",
                    "action": "ROUTE_TO_HUMAN_CONFIRMATION",
                })
                state.log(
                    self.name,
                    "SAFETY_BREACH",
                    detail=(
                        f"{p.product_sku} | proposed delta {p.budget_delta_pct:+.1f}% exceeds +/-"
                        f"{state.max_budget_variance_pct:.0f}% -> tripped safety flag, routed to human confirmation"
                    ),
                    level="CRITICAL",
                )
            else:
                # Clean: compile into outbound payload
                outbound.append({
                    "product_sku": p.product_sku,
                    "platform": p.platform,
                    "ad_id": p.ad_id,
                    "campaign_id": p.campaign_id,
                    "action": action_label,
                    "current_daily_budget": round(p.active_daily_budget, 2),
                    "new_daily_budget": round(p.proposed_daily_budget, 2),
                    "delta_pct": round(p.budget_delta_pct, 1),
                    "computed_mroas": round(p.mroas, 4),
                    "net_margin_pct": round(p.net_margin_pct * 100, 1),
                    "creative_fatigue": p.creative_fatigue,
                    "inventory_suppressed": p.inventory_suppressed,
                })
                state.log(
                    self.name,
                    "SAFETY_CLEAR",
                    detail=(
                        f"{p.product_sku} | delta {p.budget_delta_pct:+.1f}% within +/-"
                        f"{state.max_budget_variance_pct:.0f}% -> compiled {action_label} payload"
                    ),
                )

            # Every product gets a unified report row regardless of status
            report.append({
                "product_sku": p.product_sku,
                "product_name": p.product_name,
                "platform": p.platform,
                "current_budget": round(p.active_daily_budget, 2),
                "proposed_budget": round(p.proposed_daily_budget, 2),
                "delta_pct": round(p.budget_delta_pct, 1),
                "action_label": action_label,
                "status": status,
                "computed_mroas": round(p.mroas, 4),
                "net_margin_pct": round(p.net_margin_pct * 100, 1),
                "creative_fatigue": p.creative_fatigue,
                "frequency": round(p.frequency, 2),
            })

        state.outbound_api_payload = {
            "cycle_id": state.cycle_id,
            "target_floor_roas": state.target_floor_roas,
            "max_budget_variance_pct": state.max_budget_variance_pct,
            "safety_breach_flag": state.safety_breach_flag,
            "summary": {
                "total_products": len(state.products),
                "safe": sum(1 for r in report if r["status"] == "SAFE"),
                "breach": sum(1 for r in report if r["status"] == "BREACH"),
                "inventory_hold": sum(1 for r in report if r["status"] == "INVENTORY HOLD"),
                "scale": sum(1 for r in report if r["action_label"] == "SCALE"),
                "reduce": sum(1 for r in report if r["action_label"] == "REDUCE"),
                "pause": sum(1 for r in report if r["action_label"] == "PAUSE"),
                "total_current_spend": round(sum(r["current_budget"] for r in report), 2),
                "total_proposed_spend": round(sum(r["proposed_budget"] for r in report), 2),
            },
            "report": report,
            "deployments": outbound,
            "human_confirmation_required": breaches,
        }

        if state.safety_breach_flag:
            state.log(
                self.name,
                "SAFETY_GATE_HOLD",
                detail=f"{len(breaches)} proposal(s) held for human confirmation; "
                f"{len(outbound)} clean proposal(s) compiled",
                level="WARN",
            )
        else:
            state.log(
                self.name,
                "SAFETY_GATE_PASS",
                detail=f"All {len(outbound)} proposal(s) clean -> outbound payload ready",
            )

        state.log(
            self.name,
            "OUTBOUND_PAYLOAD",
            detail=json.dumps(state.outbound_api_payload, indent=2),
        )
        return state


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
AGENT_PIPELINE = [IngestionAgent(), DiagnosticBrain(), SafetyGate()]


def run_orchestrator(state: SystemState) -> SystemState:
    """Execute the full multi-agent pipeline in order, one shared state object."""
    state.cycle_id += 1
    state.log("Orchestrator", "CYCLE_START", f"Starting cycle {state.cycle_id} with {len(state.products)} products")
    for agent in AGENT_PIPELINE:
        agent(state)
    state.log("Orchestrator", "CYCLE_COMPLETE", f"Cycle {state.cycle_id} finished")
    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _record_fields(p: ProductRecord) -> list[str]:
    """Return the populated canonical field names for a product record."""
    return [f for f in p.__dataclass_fields__ if getattr(p, f) not in (None, "", 0, 0.0)]
