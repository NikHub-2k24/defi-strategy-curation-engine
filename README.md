# DeFi Strategy Curation Engine (DSCE)

An automated risk management and portfolio curation system for Decentralized Finance (DeFi) yield strategies. The DSCE evaluates smart contract, liquidity, oracle, and counterparty risks across major DeFi protocols to autonomously govern a theoretical $100M portfolio.

This repository includes both the **Production Risk Engine** (`dsce/`) and a rigorous **Historical Backtest Pipeline** (`backtest/`) that replays the engine's rules against 1.5 years of real-world market data to validate its efficacy.

## 🌟 Features

### 1. Multi-Vector Risk Scoring
The engine grades every protocol dynamically across 5 dimensions:
- **Smart Contract Risk**: Age-based decay and audit validation.
- **Liquidity Risk**: Market Cap / TVL ratio proxy.
- **Oracle Risk**: Validation of decentralized price feeds.
- **Counterparty Risk**: Penalties for centralized administration/multisigs.
- **Concentration Risk**: Enforces Herfindahl-Hirschman Index (HHI) limits (< 0.25) and single-asset caps (40%).

### 2. Emergency Triggers
The system continuously monitors live data and forces immediate capital flight if anomalies are detected:
- **TVL Bank Run**: >15% TVL drop over 7 days triggers a WARNING; >30% triggers a CRITICAL exit.
- **Yield Anomaly**: >20% relative APY deviation from the trailing 7-day average.
- **Tier Migration**: Downgrades from GREEN (<5.0 score) to RED (>7.0 score).

### 3. Historical Backtest Pipeline
A deterministic, time-aware simulator that proves the engine's rules in reality:
- **Data Ingestion**: Automatically fetches and caches historical TVL, APY, and price data from DeFiLlama and CoinGecko APIs.
- **Real-World Friction**: accurately models network gas costs ($5/txn), volume-weighted slippage (0.1% - 1.0%), and withdrawal delays (e.g., EigenLayer's 7-day queue).
- **Holdout Validation**: Strictly isolates a 6-month out-of-sample holdout window to test strategy logic free from path-dependent historical bias.

## 📁 Project Structure

```text
defi-strategy-curation-engine/
├── dsce/                      # Production Risk Engine
│   ├── modules/               
│   │   ├── risk_scoring.py    # Core 5-vector scoring logic
│   │   └── portfolio_monitor.py # Trigger and anomaly detection
│   └── data/
│       └── portfolio_config.json # Base allocation targets and limits
│
├── backtest/                  # Historical Simulator
│   ├── run_backtest.py        # Main execution entrypoint
│   ├── data_fetcher.py        # DeFiLlama/CoinGecko API integrations
│   ├── risk_engine.py         # Time-aware adapter for historical scoring
│   ├── engine.py              # The core daily tick-based state machine
│   ├── metrics.py             # Calculates Sharpe, Drawdown, Precision
│   └── report.py              # Markdown and Chart generator
│
└── README.md
```

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Pandas, Requests, Matplotlib, Numpy

### Running the Backtest

To run the full 18-month simulation and generate the performance reports:

1. Navigate to the backtest directory:
   ```bash
   cd backtest
   ```
2. Run the pipeline:
   ```bash
   python run_backtest.py
   ```
3. The engine will fetch historical data (or load from local cache), run the simulations, and output the results to `backtest/output/`.

### Viewing Results
Once the backtest completes, check the `backtest/output/` directory for:
- `backtest_report.md`: A comprehensive breakdown of returns, triggers, and calibration metrics.
- `equity_curves.png`: A visual comparison of the DSCE against the Naive Yield-Chaser and ETH Staking benchmarks.
- `trigger_annotations.png`: A timeline of every emergency exit executed by the engine.

## 🛡️ License
MIT License
