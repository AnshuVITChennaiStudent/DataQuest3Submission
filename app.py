"""DQPS Control Room - dark-mode Streamlit dashboard.

Run:  streamlit run app.py

Serves as a live command center for the Next-Generation Autonomous D2C
Advertising Intelligence & Decision Engine. Two tabs:
  - Control Room: agent console (left) + outbound payload (right) + mROAS curves
  - Report: filterable, user-friendly decision report with status pills
Sidebar: real-time product inventory tracker matrix.
"""

from __future__ import annotations

import json
import sys
import time
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Ensure src/ is importable regardless of how streamlit is launched.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agents import run_orchestrator  # noqa: E402
from engine import marginal_roas, net_product_margin  # noqa: E402
from state import DEFAULT_SEED_PRODUCTS, SystemState, build_initial_state  # noqa: E402

def process_payload(p):
    res = p["human_confirmation_required"]
    return res


# ---------------------------------------------------------------------------
# Page config & dark theme
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="DQPS Control Room",
    page_icon=":rocket:",
    layout="wide",
    initial_sidebar_state="expanded",
)

DARK_BG = "#0a0e1a"
PANEL_BG = "#121826"
ACCENT = "#22d3ee"
ACCENT_DIM = "#0e7490"
SUCCESS = "#34d399"
WARN = "#fbbf24"
ERROR = "#f87171"
TEXT = "#e2e8f0"
MUTED = "#64748b"

st.markdown(
    f"""
    <style>
        /* Global dark theme */
        .stApp {{
            background-color: {DARK_BG};
            color: {TEXT};
        }}
        section[data-testid="stSidebar"] {{
            background-color: #0b1020;
            border-right: 1px solid #1e293b;
        }}
        .stMetric, .stMetricValue, .stMetricLabel {{
            color: {TEXT} !important;
        }}
        .stMetricValue {{
            font-weight: 700;
        }}
        /* Panels / cards */
        .panel {{
            background-color: {PANEL_BG};
            border: 1px solid #1e293b;
            border-radius: 12px;
            padding: 16px;
        }}
        /* Glowing status frame for the outbound payload */
        .glow-frame {{
            background-color: #0b1322;
            border: 1px solid {ACCENT};
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 0 12px {ACCENT_DIM}, inset 0 0 8px rgba(34,211,238,0.08);
        }}
        .glow-frame.breach {{
            border-color: {ERROR};
            box-shadow: 0 0 14px rgba(248,113,113,0.5), inset 0 0 8px rgba(248,113,113,0.08);
        }}
        /* Animated agent log rows */
        .agent-line {{
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 12px;
            line-height: 1.45;
            padding: 4px 8px;
            border-left: 2px solid transparent;
            margin-bottom: 2px;
            animation: fadeIn 0.4s ease;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateX(-6px); }}
            to   {{ opacity: 1; transform: translateX(0); }}
        }}
        .lvl-INFO    {{ border-left-color: {ACCENT}; color: {TEXT}; }}
        .lvl-WARN    {{ border-left-color: {WARN}; color: {WARN}; }}
        .lvl-CRITICAL{{ border-left-color: {ERROR}; color: {ERROR}; font-weight: 600; }}
        .agent-tag   {{ color: {ACCENT}; font-weight: 700; }}
        .json-pre {{
            background: transparent !important;
            color: {ACCENT} !important;
            font-family: 'JetBrains Mono','Fira Code', monospace;
            font-size: 12px;
            white-space: pre-wrap;
            word-break: break-word;
        }}
        h1, h2, h3, h4 {{ color: {TEXT} !important; }}
        .stButton > button {{
            background-color: {ACCENT_DIM};
            color: {TEXT};
            border: 1px solid {ACCENT};
            border-radius: 8px;
        }}
        .stButton > button:hover {{
            background-color: {ACCENT};
            color: #06121a;
        }}
        /* Health pill */
        .pill {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 700;
        }}
        .pill-ok   {{ background: rgba(52,211,153,0.18); color: {SUCCESS}; }}
        .pill-warn {{ background: rgba(251,191,36,0.18); color: {WARN}; }}
        .pill-bad  {{ background: rgba(248,113,113,0.18); color: {ERROR}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------
def get_state() -> SystemState:
    if "dqps_state" not in st.session_state:
        st.session_state["dqps_state"] = build_initial_state(DEFAULT_SEED_PRODUCTS)
    return st.session_state["dqps_state"]


def reset_state() -> None:
    st.session_state["dqps_state"] = build_initial_state(DEFAULT_SEED_PRODUCTS)
    st.session_state["agent_log_html"] = ""
    st.session_state["last_payload"] = None


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <div style='display:flex;justify-content:space-between;align-items:center;padding:6px 0 14px 0;border-bottom:1px solid #1e293b;margin-bottom:14px;'>
        <div>
            <div style='font-size:22px;font-weight:800;color:{TEXT};'>DQPS Control Room</div>
            <div style='font-size:12px;color:{MUTED};'>Next-Generation Autonomous D2C Advertising Intelligence &amp; Decision Engine</div>
        </div>
        <div style='text-align:right;'>
            <div style='font-size:12px;color:{MUTED};'>Target Floor ROAS</div>
            <div style='font-size:20px;font-weight:700;color:{ACCENT};'>1.8</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Top control row
col_run, col_reset, col_spacer = st.columns([1, 1, 6])
with col_run:
    run_clicked = st.button("Run Decision Cycle")
with col_reset:
    st.button("Reset State", on_click=reset_state)

# Tabs: Control Room | Report
tab_control, tab_report = st.tabs(["Control Room", "Report"])


# ---------------------------------------------------------------------------
# Sidebar - inventory tracker matrix
# ---------------------------------------------------------------------------
st.sidebar.markdown("## Inventory Tracker Matrix")
state = get_state()

inv_rows = []
for p in state.products:
    margin_pct = net_product_margin(p.price_usd, p.cogs_usd, p.logistics_usd) * 100
    if p.inventory_stock <= 10:
        stock_pill = "bad"
    elif p.inventory_stock <= 40:
        stock_pill = "warn"
    else:
        stock_pill = "ok"
    if margin_pct < 40:
        margin_pill = "warn"
    else:
        margin_pill = "ok"
    inv_rows.append({
        "SKU": p.product_sku,
        "Product": p.product_name,
        "Platform": p.platform,
        "Stock": p.inventory_stock,
        "Price $": p.price_usd,
        "Net Margin %": round(margin_pct, 1),
        "Stock Status": stock_pill,
        "Margin Status": margin_pill,
    })

inv_df = pd.DataFrame(inv_rows)

# Render inventory as styled cards for a premium feel
for _, row in inv_df.iterrows():
    stock_pill = f"pill-{'ok' if row['Stock Status']=='ok' else 'warn' if row['Stock Status']=='warn' else 'bad'}"
    margin_pill = f"pill-{'ok' if row['Margin Status']=='ok' else 'warn'}"
    st.sidebar.markdown(
        f"""
        <div class='panel' style='margin-bottom:10px;'>
            <div style='display:flex;justify-content:space-between;align-items:center;'>
                <div style='font-weight:700;font-size:13px;color:{TEXT};'>{row['Product']}</div>
                <span class='pill {stock_pill}'>{row['Stock']} units</span>
            </div>
            <div style='font-size:11px;color:{MUTED};margin-top:2px;'>{row['SKU']} · {row['Platform']}</div>
            <div style='display:flex;justify-content:space-between;margin-top:8px;font-size:12px;'>
                <span style='color:{MUTED};'>Price</span><span style='color:{TEXT};font-weight:600;'>${row['Price $']:.2f}</span>
            </div>
            <div style='display:flex;justify-content:space-between;font-size:12px;'>
                <span style='color:{MUTED};'>Net Margin</span><span class='pill {margin_pill}'>{row['Net Margin %']:.1f}%</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.sidebar.markdown("---")
st.sidebar.markdown(
    f"<div style='font-size:11px;color:{MUTED};'>Floor ROAS <b style='color:{ACCENT};'>1.8</b> · Max variance ±20%</div>",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Run a decision cycle (animated agent log)
# ---------------------------------------------------------------------------
def level_class(level: str) -> str:
    return {
        "INFO": "lvl-INFO",
        "WARN": "lvl-WARN",
        "CRITICAL": "lvl-CRITICAL",
    }.get(level, "lvl-INFO")


def render_agent_log_lines(log_entries: list[dict]) -> str:
    html_parts = []
    for e in log_entries:
        cls = level_class(e["level"])
        html_parts.append(
            f"<div class='agent-line {cls}'>"
            f"<span style='color:{MUTED};'>[c{e['cycle']}]</span> "
            f"<span class='agent-tag'>{e['agent']}</span> "
            f"<span style='color:{ACCENT};'>{e['event']}</span> "
            f"<span style='color:{TEXT};'>{e['detail']}</span>"
            f"</div>"
        )
    return "".join(html_parts)


# Initialize log container in session
if "agent_log_html" not in st.session_state:
    st.session_state["agent_log_html"] = ""

with tab_control:
    left_col, right_col = st.columns([1.15, 1], gap="medium")

    with left_col:
        st.markdown(f"<div style='font-size:15px;font-weight:700;color:{TEXT};margin-bottom:8px;'>Multi-Agent Reasoning Console</div>", unsafe_allow_html=True)
        log_container = st.empty()

        # Always render whatever we have so the panel is never empty
        log_container.markdown(
            f"<div class='panel' style='max-height:560px;overflow:auto;'>{st.session_state['agent_log_html'] or '<div style=&quot;color:#64748b;font-size:12px;&quot;>Press Run Decision Cycle to start the orchestrator.</div>'}</div>",
            unsafe_allow_html=True,
        )

    with right_col:
        st.markdown(f"<div style='font-size:15px;font-weight:700;color:{TEXT};margin-bottom:8px;'>Outbound API Payload</div>", unsafe_allow_html=True)
        payload_container = st.empty()
        if st.session_state.get("last_payload"):
            breach = st.session_state["last_payload"].get("safety_breach_flag", False)
            frame_cls = "glow-frame breach" if breach else "glow-frame"
            status_text = "SAFETY BREACH - HUMAN CONFIRMATION REQUIRED" if breach else "CLEAN - READY FOR DEPLOYMENT"
            status_color = ERROR if breach else SUCCESS
            payload_container.markdown(
                f"""
                <div class='{frame_cls}'>
                    <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;'>
                        <div style='font-size:12px;color:{MUTED};'>Production Payload</div>
                        <div style='font-size:12px;font-weight:700;color:{status_color};'>{status_text}</div>
                    </div>
                    <pre class='json-pre'>{json.dumps(st.session_state['last_payload'], indent=2)}</pre>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            payload_container.markdown(
                f"<div class='glow-frame'><div style='color:{MUTED};font-size:12px;'>No payload yet. Run a decision cycle to compile the outbound API JSON.</div></div>",
                unsafe_allow_html=True,
            )

# ---------------------------------------------------------------------------
# Trigger an animated cycle
# ---------------------------------------------------------------------------
if run_clicked:
    # Rebuild a fresh state from seed so each run is deterministic & comparable,
    # but increment cycle counter by reusing the existing state's count.
    existing_cycle = st.session_state.get("dqps_state").cycle_id if "dqps_state" in st.session_state else 0
    fresh = build_initial_state(DEFAULT_SEED_PRODUCTS)
    fresh.cycle_id = existing_cycle
    st.session_state["dqps_state"] = fresh
    state = fresh

    # We run the orchestrator, but to animate we replay the log entries one by
    # one. We execute the full pipeline first (so the payload is available),
    # then stream the log lines into the console with a small delay.
    run_orchestrator(state)
    full_log = state.engine_diagnostic_log

    accumulated_html = ""
    # stream in batches for a smooth "typing" effect without too many rerenders
    batch_size = 2
    with st.spinner("Agents reasoning..."):
        for i in range(0, len(full_log), batch_size):
            batch = full_log[: i + batch_size]
            accumulated_html = render_agent_log_lines(batch)
            st.session_state["agent_log_html"] = accumulated_html
            log_container.markdown(
                f"<div class='panel' style='max-height:560px;overflow:auto;'>{accumulated_html}</div>",
                unsafe_allow_html=True,
            )
            time.sleep(0.18)

    # Publish final payload
    st.session_state["last_payload"] = state.outbound_api_payload
    breach = state.outbound_api_payload.get("safety_breach_flag", False)
    frame_cls = "glow-frame breach" if breach else "glow-frame"
    status_text = "SAFETY BREACH - HUMAN CONFIRMATION REQUIRED" if breach else "CLEAN - READY FOR DEPLOYMENT"
    status_color = ERROR if breach else SUCCESS
    payload_container.markdown(
        f"""
        <div class='{frame_cls}'>
            <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;'>
                <div style='font-size:12px;color:{MUTED};'>Production Payload</div>
                <div style='font-size:12px;font-weight:700;color:{status_color};'>{status_text}</div>
            </div>
            <pre class='json-pre'>{process_payload(state.outbound_api_payload)}</pre>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Refresh sidebar inventory post-cycle (margins may now reflect suppression)
    st.rerun()


# ---------------------------------------------------------------------------
# Bottom analytics - mROAS curves per product (inside Control Room tab)
# ---------------------------------------------------------------------------
with tab_control:
    st.markdown("---")
    st.markdown(f"<div style='font-size:15px;font-weight:700;color:{TEXT};margin-bottom:8px;'>Diminishing-Returns mROAS Curves</div>", unsafe_allow_html=True)

    curve_cols = st.columns(len(state.products))
    budget_range = np.linspace(10, 1500, 120)

    for col, p in zip(curve_cols, state.products):
        params = state.platform_params.get(p.platform, {"alpha": 1.0, "beta": 0.001})
        margin = net_product_margin(p.price_usd, p.cogs_usd, p.logistics_usd)
        mroas_curve = np.array([marginal_roas(b, params["alpha"], params["beta"], margin) for b in budget_range])
        current_mroas = marginal_roas(p.active_daily_budget, params["alpha"], params["beta"], margin)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=budget_range, y=mroas_curve,
            mode="lines", name="mROAS",
            line=dict(color=ACCENT, width=2),
        ))
        fig.add_hline(y=1.8, line_dash="dash", line_color=WARN, annotation_text="Floor 1.8", annotation_position="top left")
        fig.add_trace(go.Scatter(
            x=[p.active_daily_budget], y=[current_mroas],
            mode="markers", name="Current",
            marker=dict(color=ERROR if current_mroas < 1.8 else SUCCESS, size=9, line=dict(width=1, color="#0a0e1a")),
        ))
        fig.update_layout(
            title=dict(text=f"{p.product_name} <span style='color:#64748b;font-size:10px;'>{p.platform}</span>", x=0.02, font=dict(size=12, color=TEXT)),
            paper_bgcolor=PANEL_BG, plot_bgcolor=PANEL_BG,
            font=dict(color=TEXT, size=10),
            margin=dict(l=30, r=14, t=34, b=28),
            height=230,
            showlegend=False,
            xaxis=dict(title="Budget $", gridcolor="#1e293b", zerolinecolor="#1e293b"),
            yaxis=dict(title="mROAS", gridcolor="#1e293b", zerolinecolor="#1e293b"),
        )
        col.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Report tab - filterable user-friendly decision report
# ---------------------------------------------------------------------------
STATUS_PILL_CLASS = {
    "SAFE": "pill-ok",
    "BREACH": "pill-bad",
    "INVENTORY HOLD": "pill-warn",
}
ACTION_COLOR = {
    "SCALE": SUCCESS,
    "REDUCE": WARN,
    "PAUSE": ERROR,
    "HOLD": MUTED,
}

with tab_report:
    payload = st.session_state.get("last_payload")
    if not payload:
        st.markdown(
            f"<div class='panel' style='text-align:center;padding:40px;'>"
            f"<div style='font-size:16px;color:{MUTED};'>No report yet.</div>"
            f"<div style='font-size:13px;color:{MUTED};margin-top:6px;'>"
            f"Run a decision cycle on the Control Room tab to generate the report.</div></div>",
            unsafe_allow_html=True,
        )
    else:
        report_rows = payload.get("report", [])
        summary = payload.get("summary", {})

        # Summary metrics row
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Products", summary.get("total_products", 0))
        m2.metric("Safe", summary.get("safe", 0))
        m3.metric("Breach", summary.get("breach", 0))
        m4.metric("Inventory Hold", summary.get("inventory_hold", 0))
        m5.metric("Current → Proposed", f"${summary.get('total_current_spend', 0):.0f} → ${summary.get('total_proposed_spend', 0):.0f}")

        st.markdown("---")
        st.markdown(f"<div style='font-size:15px;font-weight:700;color:{TEXT};margin-bottom:10px;'>Decision Report</div>", unsafe_allow_html=True)

        # Filters
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            status_filter = st.multiselect(
                "Filter by Status",
                options=["SAFE", "BREACH", "INVENTORY HOLD"],
                default=[],
            )
        with f_col2:
            action_filter = st.multiselect(
                "Filter by Action",
                options=["SCALE", "REDUCE", "PAUSE", "HOLD"],
                default=[],
            )
        with f_col3:
            platform_filter = st.multiselect(
                "Filter by Platform",
                options=sorted({r.get("platform", "") for r in report_rows}),
                default=[],
            )

        def _matches(row: dict) -> bool:
            if status_filter and row.get("status") not in status_filter:
                return False
            if action_filter and row.get("action_label") not in action_filter:
                return False
            if platform_filter and row.get("platform") not in platform_filter:
                return False
            return True

        filtered = [r for r in report_rows if _matches(r)]
        st.caption(f"Showing {len(filtered)} of {len(report_rows)} products")

        if not filtered:
            st.markdown(
                f"<div class='panel' style='text-align:center;padding:24px;color:{MUTED};font-size:13px;'>"
                "No products match the selected filters.</div>",
                unsafe_allow_html=True,
            )
        else:
            # Render each product as a clean report card
            for r in filtered:
                pill_cls = STATUS_PILL_CLASS.get(r["status"], "pill-ok")
                act_color = ACTION_COLOR.get(r["action_label"], MUTED)
                delta_sign = "+" if r["delta_pct"] > 0 else ""
                delta_color = ERROR if r["delta_pct"] < -20 else (SUCCESS if r["delta_pct"] > 0 else WARN)
                fatigue_badge = (
                    f"<span class='pill pill-bad' style='margin-left:6px;'>CREATIVE FATIGUE</span>"
                    if r.get("creative_fatigue") else ""
                )

                st.markdown(
f"""<div class='panel' style='margin-bottom:10px;'>
    <div style='display:flex;justify-content:space-between;align-items:center;'>
        <div>
            <span style='font-weight:700;font-size:15px;color:{TEXT};'>{r['product_name']}</span>
            <span style='font-size:11px;color:{MUTED};margin-left:8px;'>{r['product_sku']} · {r['platform']}</span>
        </div>
        <span class='pill {pill_cls}'>{r['status']}</span>
    </div>
    <div style='display:flex;gap:24px;margin-top:12px;flex-wrap:wrap;'>
        <div>
            <div style='font-size:10px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;'>Current Budget</div>
            <div style='font-size:18px;font-weight:700;color:{TEXT};'>${r['current_budget']:.2f}</div>
        </div>
        <div>
            <div style='font-size:10px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;'>Proposed Budget</div>
            <div style='font-size:18px;font-weight:700;color:{TEXT};'>${r['proposed_budget']:.2f}</div>
        </div>
        <div>
            <div style='font-size:10px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;'>Delta %</div>
            <div style='font-size:18px;font-weight:700;color:{delta_color};'>{delta_sign}{r['delta_pct']:.1f}%</div>
        </div>
        <div>
            <div style='font-size:10px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;'>Action</div>
            <div style='font-size:18px;font-weight:700;color:{act_color};'>{r['action_label']}</div>
        </div>
        <div>
            <div style='font-size:10px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;'>mROAS</div>
            <div style='font-size:18px;font-weight:700;color:{ACCENT};'>{r['computed_mroas']:.4f}</div>
        </div>
        <div>
            <div style='font-size:10px;color:{MUTED};text-transform:uppercase;letter-spacing:0.5px;'>Net Margin</div>
            <div style='font-size:18px;font-weight:700;color:{TEXT};'>{r['net_margin_pct']:.1f}%</div>
        </div>
    </div>
</div>""",
                    unsafe_allow_html=True
                )

            # Plain-text friendly summary at the bottom
            st.markdown("---")
            st.markdown(f"<div style='font-size:15px;font-weight:700;color:{TEXT};margin-bottom:8px;'>Brief Summary</div>", unsafe_allow_html=True)
            n_scale = summary.get("scale", 0)
            n_reduce = summary.get("reduce", 0)
            n_pause = summary.get("pause", 0)
            n_safe = summary.get("safe", 0)
            n_breach = summary.get("breach", 0)
            n_hold = summary.get("inventory_hold", 0)
            cur = summary.get("total_current_spend", 0)
            prop = summary.get("total_proposed_spend", 0)
            overall_delta_pct = ((prop - cur) / cur * 100) if cur else 0
            overall_color = ERROR if overall_delta_pct < 0 else SUCCESS
            st.markdown(
                f"<div class='panel' style='font-size:13px;line-height:1.6;color:{TEXT};'>"
                f"This cycle evaluated <b>{summary.get('total_products',0)}</b> products. "
                f"<b style='color:{SUCCESS};'>{n_scale}</b> scaled up, "
                f"<b style='color:{WARN};'>{n_reduce}</b> reduced, and "
                f"<b style='color:{ERROR};'>{n_pause}</b> paused due to low inventory. "
                f"<b style='color:{SUCCESS};'>{n_safe}</b> passed the safety gate cleanly, "
                f"<b style='color:{ERROR};'>{n_breach}</b> breached the ±20% budget-variance rule and need human confirmation, "
                f"and <b style='color:{WARN};'>{n_hold}</b> are on inventory hold. "
                f"Total recommended spend moves from <b>${cur:.2f}</b> to <b>${prop:.2f}</b> "
                f"(<b style='color:{overall_color};'>{overall_delta_pct:+.1f}%</b>)."
                f"</div>",
                unsafe_allow_html=True,
            )

# Footer note
st.markdown(
    f"<div style='text-align:center;font-size:11px;color:{MUTED};margin-top:10px;'>"
    "DQPS prototype · deterministic agent pipeline · mROAS = α·β·exp(−β·Budget)·M_p"
    "</div>",
    unsafe_allow_html=True,
)
