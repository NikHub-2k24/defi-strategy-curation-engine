"""
DSCE Dashboard — Streamlit Entry Point

A four-tab dashboard providing:
  1. Portfolio Overview   – AUM metrics, allocation chart, risk table, alerts
  2. Strategy Evaluator   – score new strategies interactively
  3. Market Data          – live protocol data from DefiLlama / CoinGecko
  4. Risk Monitor         – anomaly cards, incident log, runbook
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── ensure project root is on sys.path ──────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.risk_scoring import (
    AssetType,
    CounterpartyType,
    RiskScorer,
    RiskTier,
    Strategy,
)
from modules.portfolio_monitor import PortfolioMonitor
from modules.memo_generator import CurationMemoGenerator
from modules.incident_runbook import get_runbook, simulate_incident, get_incident_summary_table

# ─────────────────────────────────────────────────────────────────────
# Page Config & Theme
# ─────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="DSCE — DeFi Strategy Curation Engine",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Risk tier colours
COLORS = {
    "GREEN": "#22c55e",
    "AMBER": "#f59e0b",
    "RED": "#ef4444",
    "bg_dark": "#0f1117",
    "card_bg": "#1a1d29",
    "text": "#e2e8f0",
    "accent": "#6366f1",
    "accent2": "#8b5cf6",
}

# ── inject custom CSS ───────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* Global */
html, body, [class*="st-"] {
    font-family: 'Inter', sans-serif;
}
.stApp {
    background: linear-gradient(135deg, #0f1117 0%, #1a1d29 50%, #0f1117 100%);
}

/* Metric cards */
.metric-card {
    background: linear-gradient(145deg, #1e2130, #252a3a);
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: 16px;
    padding: 24px;
    text-align: center;
    transition: all 0.3s ease;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}
.metric-card:hover {
    border-color: rgba(99, 102, 241, 0.5);
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(99, 102, 241, 0.15);
}
.metric-value {
    font-size: 2.2rem;
    font-weight: 800;
    background: linear-gradient(90deg, #6366f1, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 8px 0;
}
.metric-label {
    font-size: 0.85rem;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    font-weight: 600;
}

/* Strategy cards */
.strategy-card {
    background: linear-gradient(145deg, #1e2130, #252a3a);
    border: 1px solid rgba(99, 102, 241, 0.15);
    border-radius: 14px;
    padding: 20px;
    margin-bottom: 12px;
    transition: all 0.3s ease;
}
.strategy-card:hover {
    border-color: rgba(99, 102, 241, 0.4);
    box-shadow: 0 6px 24px rgba(0,0,0,0.3);
}
.strategy-card.anomaly {
    border-color: #ef4444;
    box-shadow: 0 0 20px rgba(239, 68, 68, 0.15);
}

/* Risk tier badges */
.tier-badge {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 1px;
}
.tier-green { background: rgba(34,197,94,0.15); color: #22c55e; }
.tier-amber { background: rgba(245,158,11,0.15); color: #f59e0b; }
.tier-red { background: rgba(239,68,68,0.15); color: #ef4444; }

/* Section headers */
.section-header {
    font-size: 1.3rem;
    font-weight: 700;
    color: #e2e8f0;
    margin: 24px 0 16px 0;
    padding-bottom: 8px;
    border-bottom: 2px solid rgba(99, 102, 241, 0.3);
}

/* Breach alert */
.breach-alert {
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 10px;
    padding: 14px 18px;
    margin: 6px 0;
    color: #fca5a5;
    font-size: 0.9rem;
}

/* Incident card */
.incident-card {
    background: linear-gradient(145deg, #1e2130, #252a3a);
    border: 1px solid rgba(99, 102, 241, 0.15);
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 10px;
}

/* Hide streamlit default */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* Progress bar overrides */
.stProgress > div > div > div > div {
    border-radius: 10px;
}

/* Tabs styling */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background: rgba(30, 33, 48, 0.8);
    border-radius: 12px;
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px;
    padding: 10px 24px;
    font-weight: 600;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
# Initialize state
# ─────────────────────────────────────────────────────────────────────

@st.cache_resource
def load_monitor() -> PortfolioMonitor:
    """Load and cache the portfolio monitor."""
    return PortfolioMonitor()

@st.cache_resource
def load_scorer() -> RiskScorer:
    """Load and cache the risk scorer."""
    return RiskScorer()

@st.cache_resource
def load_memo_gen() -> CurationMemoGenerator:
    """Load and cache the memo generator."""
    return CurationMemoGenerator()

monitor = load_monitor()
scorer = load_scorer()
memo_gen = load_memo_gen()


# ─────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────

def tier_color(tier: str) -> str:
    """Return hex colour for a risk tier string."""
    return COLORS.get(tier, COLORS["text"])


def tier_badge_html(tier: str) -> str:
    """Return HTML for a coloured tier badge."""
    cls = f"tier-{tier.lower()}"
    return f'<span class="tier-badge {cls}">{tier}</span>'


def metric_card(label: str, value: str) -> str:
    """Return HTML for a metric card."""
    return f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
    </div>
    """


# ─────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────

st.markdown("""
<div style="text-align: center; padding: 20px 0 10px 0;">
    <h1 style="font-size: 2.4rem; font-weight: 800;
        background: linear-gradient(90deg, #6366f1, #a78bfa, #c084fc);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 4px;">
        🛡️ DeFi Strategy Curation Engine
    </h1>
    <p style="color: #94a3b8; font-size: 1.05rem; font-weight: 400;">
        Institutional-Grade Risk Evaluation & Portfolio Monitoring
    </p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Portfolio Overview",
    "🔬 Strategy Evaluator",
    "📈 Market Data",
    "🚨 Risk Monitor",
])


# ═════════════════════════════════════════════════════════════════════
# TAB 1: Portfolio Overview
# ═════════════════════════════════════════════════════════════════════

with tab1:
    summary = monitor.get_portfolio_summary()
    dashboard = monitor.get_risk_dashboard()
    breaches = monitor.check_concentration_limits()
    benchmark = monitor.get_benchmark_comparison()

    # ── Metric cards ─────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            metric_card("Total AUM", f"${summary.total_aum_usd / 1e6:,.0f}M"),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            metric_card("Weighted APY", f"{summary.weighted_avg_apy_pct:.2f}%"),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            metric_card("Avg Risk Score", f"{summary.weighted_avg_risk_score:.2f}/10"),
            unsafe_allow_html=True,
        )
    with c4:
        hhi_label = "LOW" if summary.hhi < 0.15 else ("MOD" if summary.hhi < 0.25 else "HIGH")
        st.markdown(
            metric_card("HHI Index", f"{summary.hhi:.4f} ({hhi_label})"),
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Allocation bar chart ─────────────────────────────────────────
    left_col, right_col = st.columns([3, 2])

    with left_col:
        st.markdown('<div class="section-header">Strategy Allocation</div>', unsafe_allow_html=True)
        df_alloc = pd.DataFrame([
            {
                "Strategy": e.strategy_name,
                "Allocation ($M)": e.allocation_usd / 1e6,
                "Risk Tier": e.risk_tier.value,
            }
            for e in dashboard
        ])

        color_map = {"GREEN": COLORS["GREEN"], "AMBER": COLORS["AMBER"], "RED": COLORS["RED"]}
        fig_bar = px.bar(
            df_alloc,
            x="Allocation ($M)",
            y="Strategy",
            color="Risk Tier",
            orientation="h",
            color_discrete_map=color_map,
            height=350,
        )
        fig_bar.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e2e8f0", family="Inter"),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                bgcolor="rgba(0,0,0,0)",
            ),
            margin=dict(l=10, r=10, t=10, b=10),
            yaxis=dict(autorange="reversed"),
            xaxis=dict(gridcolor="rgba(99,102,241,0.1)"),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with right_col:
        st.markdown('<div class="section-header">Allocation Breakdown</div>', unsafe_allow_html=True)
        fig_pie = px.pie(
            df_alloc,
            values="Allocation ($M)",
            names="Strategy",
            hole=0.55,
            color="Risk Tier",
            color_discrete_map=color_map,
            height=350,
        )
        fig_pie.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e2e8f0", family="Inter", size=11),
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
            margin=dict(l=10, r=10, t=10, b=10),
        )
        fig_pie.update_traces(textposition='inside', textinfo='percent')
        st.plotly_chart(fig_pie, use_container_width=True)

    # ── Strategy table ───────────────────────────────────────────────
    st.markdown('<div class="section-header">Strategy Dashboard</div>', unsafe_allow_html=True)

    df_table = pd.DataFrame([
        {
            "Strategy": e.strategy_name,
            "Allocation $M": f"${e.allocation_usd / 1e6:,.0f}M",
            "Allocation %": f"{e.allocation_pct:.1f}%",
            "APY %": f"{e.apy_pct:.1f}%",
            "Risk Score": f"{e.risk_score:.2f}",
            "Risk Tier": e.risk_tier.value,
            "Risk-Adj Yield": f"{e.risk_adjusted_yield:.3f}",
            "Asset Type": e.asset_type,
            "Counterparty": e.counterparty_type,
        }
        for e in dashboard
    ])

    st.dataframe(df_table, use_container_width=True, hide_index=True)

    # ── Concentration alerts ─────────────────────────────────────────
    st.markdown('<div class="section-header">Concentration Alerts</div>', unsafe_allow_html=True)
    if breaches:
        for b in breaches:
            st.markdown(f'<div class="breach-alert">⚠️ {b}</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<div style="background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.3); '
            'border-radius: 10px; padding: 14px 18px; color: #86efac; font-size: 0.9rem;">'
            '✅ No concentration breaches — portfolio is within limits</div>',
            unsafe_allow_html=True,
        )

    # ── Benchmark comparison ─────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    b1, b2, b3, b4 = st.columns(4)
    with b1:
        st.metric("Portfolio APY", f"{benchmark.portfolio_apy_pct:.2f}%")
    with b2:
        st.metric("Benchmark (ETH)", f"{benchmark.benchmark_apy_pct:.2f}%")
    with b3:
        st.metric("Excess Yield", f"{benchmark.excess_yield_pct:+.2f}%",
                   delta=f"{benchmark.excess_yield_pct:+.2f}%")
    with b4:
        st.metric("Sharpe Equivalent", f"{benchmark.sharpe_equivalent:.4f}")


# ═════════════════════════════════════════════════════════════════════
# TAB 2: Strategy Evaluator
# ═════════════════════════════════════════════════════════════════════

with tab2:
    st.markdown('<div class="section-header">Evaluate a New Strategy</div>', unsafe_allow_html=True)

    with st.form("strategy_form"):
        fc1, fc2, fc3 = st.columns(3)

        with fc1:
            strategy_name = st.text_input("Strategy Name", "New LST Strategy")
            protocol_name = st.text_input("Protocol Name", "example-protocol")
            chain = st.selectbox("Chain", ["Ethereum", "Arbitrum", "Optimism", "Polygon", "BSC", "Avalanche"])
            asset_type = st.selectbox("Asset Type", [a.value for a in AssetType])
            counterparty_type = st.selectbox("Counterparty Type", [c.value for c in CounterpartyType])

        with fc2:
            tvl_usd = st.number_input("TVL (USD)", min_value=0.0, value=500_000_000.0,
                                       step=1_000_000.0, format="%.0f")
            tvl_7d_change = st.number_input("TVL 7d Change %", value=0.0, step=0.1)
            apy_pct = st.number_input("APY %", min_value=0.0, value=5.0, step=0.1)
            liquidity_depth = st.number_input("Liquidity Depth (USD)", min_value=0.0,
                                               value=50_000_000.0, step=1_000_000.0, format="%.0f")

        with fc3:
            audit_count = st.number_input("Audit Count", min_value=0, value=2, step=1)
            age_days = st.number_input("Protocol Age (days)", min_value=0, value=365, step=1)
            mcap_tvl = st.number_input("Mcap/TVL Ratio", min_value=0.0, value=0.3, step=0.01)
            has_oracle = st.checkbox("Uses Oracle", value=True)
            oracle_provider = st.selectbox("Oracle Provider",
                                            ["Chainlink", "Uniswap TWAP", "custom", "None"])
            allocation = st.number_input("Proposed Allocation (USD)", min_value=0.0,
                                          value=10_000_000.0, step=1_000_000.0, format="%.0f")

        submitted = st.form_submit_button("🔍 Evaluate Strategy", type="primary",
                                           use_container_width=True)

    if submitted:
        strat_dict = {
            "strategy_name": strategy_name,
            "protocol_name": protocol_name,
            "chain": chain,
            "asset_type": asset_type,
            "counterparty_type": counterparty_type,
            "tvl_usd": tvl_usd,
            "tvl_7d_change_pct": tvl_7d_change,
            "apy_pct": apy_pct,
            "liquidity_depth_usd": liquidity_depth,
            "audit_count": audit_count,
            "age_days": age_days,
            "mcap_tvl_ratio": mcap_tvl,
            "has_oracle": has_oracle,
            "oracle_provider": oracle_provider if oracle_provider != "None" else None,
            "allocation_usd": allocation,
        }

        # Build current portfolio map for concentration scoring
        portfolio_map = {s.strategy_name: s.allocation_usd for s in monitor.strategies}
        portfolio_map[strategy_name] = allocation

        report = scorer.score_strategy(strat_dict, portfolio_map)

        # ── Tier banner ──────────────────────────────────────────────
        tier_bg = {
            "GREEN": "rgba(34,197,94,0.12)",
            "AMBER": "rgba(245,158,11,0.12)",
            "RED": "rgba(239,68,68,0.12)",
        }
        tier_border = {
            "GREEN": "rgba(34,197,94,0.4)",
            "AMBER": "rgba(245,158,11,0.4)",
            "RED": "rgba(239,68,68,0.4)",
        }
        st.markdown(f"""
        <div style="background: {tier_bg[report.risk_tier.value]};
                    border: 2px solid {tier_border[report.risk_tier.value]};
                    border-radius: 14px; padding: 20px; text-align: center; margin: 16px 0;">
            <div style="font-size: 0.85rem; color: #94a3b8; text-transform: uppercase;
                        letter-spacing: 1.5px; font-weight: 600;">Composite Risk Score</div>
            <div style="font-size: 3rem; font-weight: 800;
                        color: {tier_color(report.risk_tier.value)};">
                {report.composite_score}/10
            </div>
            <div>{tier_badge_html(report.risk_tier.value)}</div>
            <div style="color: #94a3b8; font-size: 0.9rem; margin-top: 8px;">
                {report.recommendation}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Dimension scores: progress bars + radar chart ────────────
        r1, r2 = st.columns([1, 1])

        with r1:
            st.markdown('<div class="section-header">Risk Dimensions</div>',
                        unsafe_allow_html=True)
            dims = report.dimension_scores.model_dump()
            dim_labels = {
                "smart_contract": "Smart Contract",
                "liquidity": "Liquidity",
                "oracle_market": "Oracle / Market",
                "counterparty": "Counterparty",
                "concentration": "Concentration",
            }
            for key, label in dim_labels.items():
                val = dims[key]
                if val <= 3:
                    bar_color = COLORS["GREEN"]
                elif val <= 6:
                    bar_color = COLORS["AMBER"]
                else:
                    bar_color = COLORS["RED"]

                st.markdown(f"""
                <div style="margin-bottom: 14px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                        <span style="color: #e2e8f0; font-weight: 500; font-size: 0.9rem;">
                            {label}
                        </span>
                        <span style="color: {bar_color}; font-weight: 700; font-size: 0.9rem;">
                            {val}/10
                        </span>
                    </div>
                    <div style="background: rgba(99,102,241,0.1); border-radius: 8px;
                                height: 10px; overflow: hidden;">
                        <div style="width: {val * 10}%; height: 100%;
                                    background: {bar_color};
                                    border-radius: 8px;
                                    transition: width 0.5s ease;"></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        with r2:
            st.markdown('<div class="section-header">Risk Radar</div>',
                        unsafe_allow_html=True)
            categories = list(dim_labels.values())
            values = [dims[k] for k in dim_labels]
            values_closed = values + [values[0]]  # close the polygon
            categories_closed = categories + [categories[0]]

            fig_radar = go.Figure()
            fig_radar.add_trace(go.Scatterpolar(
                r=values_closed,
                theta=categories_closed,
                fill='toself',
                fillcolor='rgba(99, 102, 241, 0.15)',
                line=dict(color='#6366f1', width=2),
                marker=dict(size=6, color='#a78bfa'),
                name='Risk Score',
            ))
            fig_radar.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True, range=[0, 10],
                        gridcolor="rgba(99,102,241,0.15)",
                        linecolor="rgba(99,102,241,0.1)",
                        tickfont=dict(color="#94a3b8", size=10),
                    ),
                    angularaxis=dict(
                        gridcolor="rgba(99,102,241,0.1)",
                        linecolor="rgba(99,102,241,0.1)",
                        tickfont=dict(color="#e2e8f0", size=11),
                    ),
                    bgcolor="rgba(0,0,0,0)",
                ),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e2e8f0", family="Inter"),
                showlegend=False,
                height=340,
                margin=dict(l=60, r=60, t=20, b=20),
            )
            st.plotly_chart(fig_radar, use_container_width=True)

        # ── Flags ────────────────────────────────────────────────────
        if report.flags:
            st.markdown('<div class="section-header">Risk Flags</div>',
                        unsafe_allow_html=True)
            for flag in report.flags:
                st.markdown(f"""
                <div style="background: rgba(245,158,11,0.08); border-left: 3px solid #f59e0b;
                            padding: 10px 16px; margin: 6px 0; border-radius: 0 8px 8px 0;
                            color: #fcd34d; font-size: 0.85rem;">
                    ⚡ {flag}
                </div>
                """, unsafe_allow_html=True)

        # ── Generated memo ───────────────────────────────────────────
        st.markdown('<div class="section-header">Curation Memo</div>',
                    unsafe_allow_html=True)
        strat_obj = Strategy(**strat_dict)
        memo = memo_gen.generate_memo(strat_obj, report)
        st.text_area("Generated Curation Memo (copy-paste ready)", memo, height=500)


# ═════════════════════════════════════════════════════════════════════
# TAB 3: Market Data
# ═════════════════════════════════════════════════════════════════════

with tab3:
    st.markdown('<div class="section-header">Live Market Data</div>', unsafe_allow_html=True)

    if "market_data_loaded" not in st.session_state:
        st.session_state.market_data_loaded = False
        st.session_state.market_data_ts = None

    col_refresh, col_ts = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 Refresh Data", type="primary"):
            st.session_state.market_data_loaded = False
            st.cache_data.clear()

    with col_ts:
        if st.session_state.market_data_ts:
            st.caption(f"Last refreshed: {st.session_state.market_data_ts}")

    # Lazy-import data ingestion
    from modules.data_ingestion import (
        fetch_protocols,
        fetch_steth_price_history,
        fetch_protocol_tvl,
        generate_mock_data,
    )

    @st.cache_data(ttl=3600)
    def load_market_data():
        """Load market data with mock fallback."""
        try:
            protocols = fetch_protocols()
            steth_history = fetch_steth_price_history(days=90)
            lido_tvl = fetch_protocol_tvl("lido")
            return protocols, steth_history, lido_tvl, True
        except Exception:
            mock = generate_mock_data()
            return mock["protocols"], mock["steth_history"], [], False

    protocols, steth_history, lido_tvl, is_live = load_market_data()
    st.session_state.market_data_loaded = True
    st.session_state.market_data_ts = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    if not is_live:
        st.warning("⚠️ Using mock data — live APIs are unavailable")

    # ── Top 10 LST protocols by TVL ──────────────────────────────────
    st.markdown('<div class="section-header">Top 10 LST Protocols by TVL</div>',
                unsafe_allow_html=True)

    lst_protocols = [
        p for p in protocols
        if isinstance(p, dict) and
        (p.get("category", "").lower() in ("liquid staking", "staking") or
         p.get("name", "").lower() in ("lido", "rocket pool", "coinbase wrapped staked eth",
                                         "frax ether", "stakewise", "mantle staked ether"))
    ]
    lst_protocols.sort(key=lambda x: x.get("tvl") or 0, reverse=True)
    lst_top10 = lst_protocols[:10]

    if lst_top10:
        df_lst = pd.DataFrame([
            {
                "Protocol": p.get("name", "Unknown"),
                "TVL ($M)": f"${(p.get('tvl') or 0) / 1e6:,.0f}M",
                "Chain": (p.get("chain", "—") if isinstance(p.get("chain"), str)
                          else ", ".join(p.get("chains", ["—"])[:2])),
                "Category": p.get("category", "—"),
            }
            for p in lst_top10
        ])
        st.dataframe(df_lst, use_container_width=True, hide_index=True)
    else:
        st.info("No LST protocols found in data")

    # ── stETH/ETH price ratio chart ──────────────────────────────────
    mc1, mc2 = st.columns(2)

    with mc1:
        st.markdown('<div class="section-header">stETH/ETH Price Ratio (90 days)</div>',
                    unsafe_allow_html=True)
        if steth_history:
            df_steth = pd.DataFrame(steth_history)
            if "timestamp" in df_steth.columns and "price_ratio" in df_steth.columns:
                df_steth["date"] = pd.to_datetime(df_steth["timestamp"], unit="ms", errors="coerce")
                fig_steth = px.area(
                    df_steth, x="date", y="price_ratio",
                    labels={"date": "", "price_ratio": "stETH/ETH"},
                    height=350,
                )
                fig_steth.update_traces(
                    fill='tozeroy',
                    fillcolor='rgba(99,102,241,0.1)',
                    line=dict(color='#6366f1', width=2),
                )
                fig_steth.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#e2e8f0", family="Inter"),
                    margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(gridcolor="rgba(99,102,241,0.1)"),
                    yaxis=dict(gridcolor="rgba(99,102,241,0.1)"),
                )
                st.plotly_chart(fig_steth, use_container_width=True)
            else:
                st.info("stETH history data format unexpected")
        else:
            st.info("No stETH price history available")

    with mc2:
        st.markdown('<div class="section-header">Lido TVL Trend (30 days)</div>',
                    unsafe_allow_html=True)
        if lido_tvl and isinstance(lido_tvl, list):
            # lido_tvl is list of [timestamp, tvl]
            df_tvl = pd.DataFrame(lido_tvl, columns=["timestamp", "tvl"])
            df_tvl["date"] = pd.to_datetime(df_tvl["timestamp"], unit="s", errors="coerce")
            df_tvl = df_tvl.tail(30)
            fig_tvl = px.area(
                df_tvl, x="date", y="tvl",
                labels={"date": "", "tvl": "TVL (USD)"},
                height=350,
            )
            fig_tvl.update_traces(
                fill='tozeroy',
                fillcolor='rgba(139,92,246,0.1)',
                line=dict(color='#8b5cf6', width=2),
            )
            fig_tvl.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e2e8f0", family="Inter"),
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis=dict(gridcolor="rgba(99,102,241,0.1)"),
                yaxis=dict(gridcolor="rgba(99,102,241,0.1)"),
            )
            st.plotly_chart(fig_tvl, use_container_width=True)
        else:
            st.info("No Lido TVL data available (showing mock trend)")
            # Show mock trend
            import numpy as np
            dates = pd.date_range(end=datetime.utcnow(), periods=30, freq="D")
            tvl_vals = 14e9 + np.random.randn(30).cumsum() * 1e8
            df_mock_tvl = pd.DataFrame({"date": dates, "tvl": tvl_vals})
            fig_mock = px.area(df_mock_tvl, x="date", y="tvl", height=350)
            fig_mock.update_traces(
                fill='tozeroy', fillcolor='rgba(139,92,246,0.1)',
                line=dict(color='#8b5cf6', width=2),
            )
            fig_mock.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e2e8f0", family="Inter"),
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis=dict(gridcolor="rgba(99,102,241,0.1)"),
                yaxis=dict(gridcolor="rgba(99,102,241,0.1)"),
            )
            st.plotly_chart(fig_mock, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════
# TAB 4: Risk Monitor
# ═════════════════════════════════════════════════════════════════════

with tab4:
    st.markdown('<div class="section-header">Active Strategy Risk Cards</div>',
                unsafe_allow_html=True)

    anomalies = monitor.flag_anomalies()
    anomaly_names = {a.strategy_name for a in anomalies}

    # ── Strategy cards (2 per row) ───────────────────────────────────
    dashboard_entries = monitor.get_risk_dashboard()
    for i in range(0, len(dashboard_entries), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            idx = i + j
            if idx >= len(dashboard_entries):
                break
            entry = dashboard_entries[idx]
            strat = monitor.get_strategy_by_name(entry.strategy_name)
            is_anomaly = entry.strategy_name in anomaly_names

            card_class = "strategy-card anomaly" if is_anomaly else "strategy-card"
            border_extra = "border-color: #ef4444 !important;" if is_anomaly else ""

            with col:
                st.markdown(f"""
                <div class="{card_class}" style="{border_extra}">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div style="font-size: 1.05rem; font-weight: 700; color: #e2e8f0;">
                            {entry.strategy_name}
                        </div>
                        {tier_badge_html(entry.risk_tier.value)}
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
                                margin-top: 14px;">
                        <div>
                            <div style="color: #64748b; font-size: 0.75rem; text-transform: uppercase;
                                        letter-spacing: 1px;">Risk Score</div>
                            <div style="color: {tier_color(entry.risk_tier.value)};
                                        font-size: 1.4rem; font-weight: 700;">
                                {entry.risk_score:.2f}
                            </div>
                        </div>
                        <div>
                            <div style="color: #64748b; font-size: 0.75rem; text-transform: uppercase;
                                        letter-spacing: 1px;">APY</div>
                            <div style="color: #a78bfa; font-size: 1.4rem; font-weight: 700;">
                                {entry.apy_pct:.1f}%
                            </div>
                        </div>
                        <div>
                            <div style="color: #64748b; font-size: 0.75rem; text-transform: uppercase;
                                        letter-spacing: 1px;">TVL 7d Change</div>
                            <div style="color: {'#ef4444' if strat and strat.tvl_7d_change_pct < -5 else '#22c55e'};
                                        font-size: 1.1rem; font-weight: 600;">
                                {strat.tvl_7d_change_pct if strat else 0:+.1f}%
                            </div>
                        </div>
                        <div>
                            <div style="color: #64748b; font-size: 0.75rem; text-transform: uppercase;
                                        letter-spacing: 1px;">Allocation</div>
                            <div style="color: #94a3b8; font-size: 1.1rem; font-weight: 600;">
                                ${entry.allocation_usd / 1e6:,.0f}M
                            </div>
                        </div>
                    </div>
                    {"<div style='margin-top: 10px; color: #fca5a5; font-size: 0.8rem;'>⚠️ Anomaly detected</div>" if is_anomaly else ""}
                </div>
                """, unsafe_allow_html=True)

    # ── Active anomaly alerts ────────────────────────────────────────
    if anomalies:
        st.markdown('<div class="section-header">⚠️ Active Anomaly Alerts</div>',
                    unsafe_allow_html=True)
        for alert in anomalies:
            sev_color = COLORS["RED"] if alert.severity == "CRITICAL" else COLORS["AMBER"]
            st.markdown(f"""
            <div style="background: rgba(239,68,68,0.08); border-left: 3px solid {sev_color};
                        padding: 12px 16px; margin: 6px 0; border-radius: 0 8px 8px 0;">
                <div style="color: {sev_color}; font-weight: 700; font-size: 0.85rem;">
                    [{alert.severity}] {alert.strategy_name}
                </div>
                <div style="color: #e2e8f0; font-size: 0.85rem; margin-top: 4px;">
                    {alert.description}
                </div>
            </div>
            """, unsafe_allow_html=True)

    # ── Incident Log ─────────────────────────────────────────────────
    st.markdown('<div class="section-header">📋 Incident Log</div>', unsafe_allow_html=True)

    mock_incidents_path = PROJECT_ROOT / "data" / "mock_incidents.json"
    try:
        with open(mock_incidents_path, "r", encoding="utf-8") as f:
            incidents_data = json.load(f)
        incidents = incidents_data.get("incidents", [])
    except Exception:
        incidents = []

    for inc in incidents:
        sev_colors = {"P1": COLORS["RED"], "P2": COLORS["AMBER"], "P3": "#6366f1"}
        sev_c = sev_colors.get(inc.get("severity", "P3"), "#6366f1")

        st.markdown(f"""
        <div class="incident-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="font-weight: 700; color: #e2e8f0; font-size: 0.95rem;">
                    {inc.get('title', 'Unknown Incident')}
                </div>
                <span class="tier-badge" style="background: rgba(99,102,241,0.15); color: {sev_c};">
                    {inc.get('severity', '—')}
                </span>
            </div>
            <div style="color: #94a3b8; font-size: 0.8rem; margin-top: 6px;">
                {inc.get('date', '—')} &nbsp;·&nbsp; {inc.get('id', '')} &nbsp;·&nbsp;
                Resolved: {inc.get('resolved_date', 'Pending')}
            </div>
            <div style="color: #cbd5e1; font-size: 0.85rem; margin-top: 8px;">
                {inc.get('description', '')}
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Incident Response Runbook ────────────────────────────────────
    st.markdown('<div class="section-header">📖 Incident Response Runbook</div>',
                unsafe_allow_html=True)

    runbook = get_runbook()

    with st.expander("🔍 View Full Incident Response Runbook", expanded=False):
        for key, entry in runbook.items():
            sev_colors = {"P1": COLORS["RED"], "P2": COLORS["AMBER"], "P3": "#6366f1"}
            sev_c = sev_colors.get(entry.severity, "#6366f1")

            st.markdown(f"""
            <div style="background: linear-gradient(145deg, #1e2130, #252a3a);
                        border: 1px solid rgba(99,102,241,0.15);
                        border-radius: 10px; padding: 16px; margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-weight: 700; color: #e2e8f0; font-size: 0.95rem;">
                        {key.replace('_', ' ').title()}
                    </div>
                    <span class="tier-badge" style="background: rgba(99,102,241,0.15); color: {sev_c};">
                        {entry.severity}
                    </span>
                </div>
                <div style="color: #94a3b8; font-size: 0.8rem; margin-top: 4px;">
                    Trigger: {entry.trigger}
                </div>
                <div style="color: #94a3b8; font-size: 0.8rem; margin-top: 2px;">
                    Detection: {entry.detection_method}
                </div>
                <div style="color: #cbd5e1; font-size: 0.85rem; margin-top: 8px;">
                    <strong>Immediate Actions:</strong>
                    <ol style="margin: 4px 0; padding-left: 20px;">
                        {"".join(f'<li>{a}</li>' for a in entry.immediate_actions)}
                    </ol>
                </div>
                <div style="color: #94a3b8; font-size: 0.8rem; margin-top: 4px;">
                    Escalation: {" → ".join(entry.escalation_path)}
                </div>
                <div style="color: #94a3b8; font-size: 0.8rem; margin-top: 2px;">
                    Resolution: {entry.resolution_criteria}
                </div>
            </div>
            """, unsafe_allow_html=True)

    # ── Incident Simulation ──────────────────────────────────────────
    st.markdown('<div class="section-header">🎮 Incident Simulation</div>',
                unsafe_allow_html=True)

    sim_type = st.selectbox(
        "Select incident type to simulate",
        list(runbook.keys()),
        format_func=lambda x: x.replace("_", " ").title(),
    )

    if st.button("▶️ Run Simulation", type="primary"):
        simulation = simulate_incident(sim_type)
        st.code(simulation, language="text")


# ─────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────

st.markdown("""
<div style="text-align: center; padding: 30px 0 10px 0; color: #64748b; font-size: 0.8rem;">
    DSCE v1.0 — DeFi Strategy Curation Engine &nbsp;·&nbsp;
    Built for institutional DeFi asset management workflows &nbsp;·&nbsp;
    Risk scores are rules-based and fully transparent
</div>
""", unsafe_allow_html=True)
