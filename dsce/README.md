# DeFi Strategy Curation Engine (DSCE)

An institutional-grade DeFi strategy evaluation and risk monitoring system built in Python. DSCE evaluates yield-generating DeFi strategies (stETH/WETH LP on Curve, stETH lending on Aave, ETH staking via Lido, etc.) across multiple risk dimensions, monitors portfolio concentration, and generates written curation memos — exactly as a DeFi asset management team would do before deploying capital.

Built as a portfolio project demonstrating the end-to-end curation workflow for a DeFi asset management role, DSCE implements transparent, rules-based risk scoring (no black-box ML), real-time data integration via DefiLlama and CoinGecko APIs, and an interactive Streamlit dashboard for portfolio monitoring and strategy evaluation.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     STREAMLIT DASHBOARD                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │ Portfolio │ │ Strategy │ │  Market  │ │   Risk Monitor   │  │
│  │ Overview  │ │Evaluator │ │   Data   │ │ + Incident Mgmt  │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────────┬─────────┘  │
└───────┼─────────────┼───────────┼─────────────────┼────────────┘
        │             │           │                 │
┌───────┴─────────────┴───────────┴─────────────────┴────────────┐
│                       MODULE LAYER                              │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │ risk_scoring  │  │  portfolio   │  │   memo_generator      │ │
│  │              │  │  _monitor    │  │                       │ │
│  │ • 5 risk     │◄─┤              │  │ • Strategy memos      │ │
│  │   dimensions │  │ • AUM / HHI  │──┤ • Portfolio reports   │ │
│  │ • Composite  │  │ • Breaches   │  │ • Recommendations     │ │
│  │   scoring    │  │ • Anomalies  │  └───────────────────────┘ │
│  │ • Risk tiers │  │ • Benchmark  │                            │
│  └──────────────┘  └──────────────┘  ┌───────────────────────┐ │
│                                       │ incident_runbook      │ │
│  ┌──────────────┐                     │                       │ │
│  │data_ingestion│                     │ • 7 runbook entries   │ │
│  │              │                     │ • Simulation engine   │ │
│  │ • DefiLlama  │                     │ • Incident log        │ │
│  │ • CoinGecko  │                     └───────────────────────┘ │
│  │ • Cache/Mock │                                               │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
        │
┌───────┴─────────────────────────────────────────────────────────┐
│                        DATA LAYER                               │
│  data/                                                          │
│  ├── raw/              (API response cache, auto-managed)       │
│  ├── portfolio_config.json  (7 strategies, limits, benchmark)   │
│  └── mock_incidents.json    (3 historical incidents)            │
└─────────────────────────────────────────────────────────────────┘
```

## How to Run Locally

### Prerequisites
- Python 3.10+
- pip

### Setup

```bash
# 1. Navigate to the project directory
cd dsce/

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the Streamlit dashboard
streamlit run dashboard.py
```

The dashboard opens at `http://localhost:8501`.

### Running Individual Modules

Each module can be run standalone for testing:

```bash
# Test risk scoring
python -m modules.risk_scoring

# Test data ingestion (fetches live data or falls back to mock)
python -m modules.data_ingestion

# Test portfolio monitor
python -m modules.portfolio_monitor

# Test memo generator
python -m modules.memo_generator

# Test incident runbook
python -m modules.incident_runbook
```

## Sample Outputs

### Tab 1: Portfolio Overview
- **4 metric cards**: Total AUM ($100M), Weighted APY (4.35%), Avg Risk Score, HHI Index
- **Horizontal bar chart**: Strategy allocations color-coded by risk tier (GREEN/AMBER/RED)
- **Donut chart**: Allocation breakdown by percentage
- **Strategy table**: All 7 strategies with allocation, APY, risk score, risk tier, and risk-adjusted yield
- **Concentration alerts**: Warns if any single strategy exceeds 40% or counterparty type exceeds 30%
- **Benchmark comparison**: Portfolio APY vs 3.5% ETH staking rate with Sharpe equivalent

### Tab 2: Strategy Evaluator
- **Interactive form**: Input any strategy's parameters (protocol, TVL, APY, audits, oracle, etc.)
- **Risk score banner**: Large composite score with color-coded tier
- **Progress bars**: Each of 5 risk dimensions shown as colored bars (green/amber/red)
- **Radar chart**: Pentagon visualization of all 5 risk dimensions
- **Risk flags**: All triggered risk factors listed with explanations
- **Curation memo**: Full 7-section institutional memo, ready to copy-paste

### Tab 3: Market Data
- **Top 10 LST protocols**: Sorted by TVL from DefiLlama
- **stETH/ETH price ratio chart**: 90-day area chart from CoinGecko
- **Lido TVL trend**: 30-day TVL history
- **Refresh button**: Manual data refresh with timestamp

### Tab 4: Risk Monitor
- **Strategy risk cards**: 2-column grid with risk score, APY, TVL change, allocation
- **Anomaly highlighting**: Red-bordered cards for strategies with active alerts
- **Incident log**: 3 historical incidents (TVL drop, APY anomaly, oracle delay)
- **Runbook viewer**: Expandable section showing all 7 incident response procedures
- **Incident simulator**: Select any scenario and see a phase-by-phase walkthrough

## Methodology

### Risk Scoring Formula

Each strategy is scored across **5 dimensions** on a 1-10 scale (1 = lowest risk, 10 = highest risk):

| Dimension | Weight | Key Factors |
|-----------|--------|-------------|
| Smart Contract Risk | 25% | Audit count, protocol age, TVL (battle-testing proxy) |
| Liquidity Risk | 25% | Liquidity depth, 7-day TVL change, LP token IL risk |
| Oracle/Market Risk | 20% | Oracle provider quality, APY sustainability |
| Counterparty Risk | 20% | Governance model, mcap/TVL collateralisation ratio |
| Concentration Risk | 10% | HHI at portfolio level, single-strategy limits |

**Composite Score** = Σ (dimension_score × weight)

**Risk Tiers:**
- 🟢 **GREEN** (1-3): Approve — low risk, suitable for deployment
- 🟡 **AMBER** (4-6): Conditional Approve — enhanced monitoring required
- 🔴 **RED** (7-10): Reject — risk exceeds tolerance

### Herfindahl-Hirschman Index (HHI)

Measures portfolio concentration:

```
HHI = Σ (allocation_i / total_AUM)²
```

- **HHI < 0.15**: Well-diversified portfolio
- **HHI 0.15-0.25**: Moderate concentration
- **HHI > 0.25**: High concentration — action required

**Concentration Limits:**
- No single strategy may exceed **40%** of portfolio
- No single counterparty type may exceed **30%** of portfolio

### Risk-Adjusted Yield (RAY)

```
RAY = APY% / Composite_Risk_Score
```

Higher RAY indicates better risk-adjusted return. Used to compare strategies on a level playing field — a strategy yielding 4% with risk score 2.0 (RAY = 2.0) is preferred over one yielding 8% with risk score 6.0 (RAY = 1.33).

### Sharpe Equivalent

```
Sharpe Equivalent = (Portfolio_APY - Benchmark_APY) / Weighted_Risk_Score
```

Uses ETH staking rate (3.5%) as the risk-free benchmark. Measures how much excess yield the portfolio generates per unit of risk taken.

## Project Structure

```
dsce/
├── data/
│   ├── raw/                       # Auto-managed API cache (JSON)
│   ├── portfolio_config.json      # 7 strategies + concentration limits
│   └── mock_incidents.json        # 3 historical incident records
├── modules/
│   ├── __init__.py
│   ├── data_ingestion.py          # DefiLlama + CoinGecko clients
│   ├── risk_scoring.py            # 5-dimension risk engine
│   ├── portfolio_monitor.py       # Portfolio analytics + monitoring
│   ├── memo_generator.py          # Curation memo + report generation
│   └── incident_runbook.py        # Runbook definitions + simulation
├── dashboard.py                   # Streamlit 4-tab dashboard
├── requirements.txt
└── README.md
```

## Limitations and Future Improvements

### Current Limitations
- **Static portfolio config**: Portfolio is defined in JSON — no persistent storage or real-time rebalancing
- **API rate limits**: CoinGecko free tier has aggressive rate limiting; may require API key for production
- **No backtesting**: Risk scores are point-in-time — no historical scoring or strategy performance backtesting
- **Simplified Sharpe**: Uses risk score as volatility proxy rather than actual return variance
- **Single-chain focus**: Primarily designed for Ethereum-based strategies

### Future Improvements
- **Database integration**: PostgreSQL/TimescaleDB for time-series risk data and audit trail
- **Real-time alerts**: WebSocket-based monitoring with Telegram/Slack notifications
- **Multi-chain expansion**: Cross-chain risk correlation analysis (Arbitrum, Optimism, etc.)
- **ML-augmented scoring**: Ensemble models for anomaly detection while keeping base rules transparent
- **Governance integration**: Snapshot voting analysis as a counterparty risk signal
- **On-chain monitoring**: Direct RPC integration for real-time TVL and oracle health checks
- **PDF export**: Generate downloadable curation memos and portfolio reports via fpdf2
- **Role-based access**: Multi-user support with analyst/reviewer/approver workflows
- **Backtesting engine**: Replay historical scenarios against risk scoring rules
- **Stress testing**: Simulate correlated drawdown scenarios across portfolio positions

## License

This project is a portfolio demonstration. Built for educational and professional showcase purposes.
