"""
Backtest Runner
===============

Entry point for the full backtest pipeline:
1. Fetch and cache historical data from DeFiLlama + CoinGecko
2. Run the three-strategy simulation
3. Compute performance metrics and trigger analysis
4. Generate charts
5. Generate markdown report
6. Print summary to console

Usage:
    python -m backtest.run_backtest
"""

from __future__ import annotations

import sys
import os
import time

# Add project root to sys.path for DSCE imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd

from backtest.data_fetcher import fetch_all_data
from backtest.engine import BacktestDataset as EngineDataset, run_backtest
from backtest.metrics import compute_all_metrics
from backtest.charts import plot_equity_curves, plot_trigger_annotations
from backtest.report import generate_report


def prepare_engine_dataset(fetched_data) -> EngineDataset:
    """
    Bridge the data_fetcher output format to the engine's expected input.

    data_fetcher returns:
        - protocol_tvl: Dict[str, DataFrame]  (each has 'tvl_usd' column)
        - pool_apy: Dict[str, DataFrame]       (each has 'apy', 'il_7d', etc.)

    engine expects:
        - tvl_data: DataFrame with protocol names as columns, dates as index
        - apy_data: DataFrame with protocol names as columns, dates as index
        - il_data: DataFrame with protocol names as columns, dates as index
    """
    # Combine TVL DataFrames into a single wide DataFrame
    tvl_frames = {}
    for protocol, df in fetched_data.protocol_tvl.items():
        if not df.empty and "tvl_usd" in df.columns:
            tvl_frames[protocol] = df["tvl_usd"]

    if tvl_frames:
        tvl_data = pd.DataFrame(tvl_frames)
    else:
        tvl_data = pd.DataFrame()

    # Combine APY DataFrames into a single wide DataFrame
    apy_frames = {}
    il_frames = {}
    for protocol, df in fetched_data.pool_apy.items():
        if not df.empty:
            if "apy" in df.columns:
                apy_frames[protocol] = df["apy"]
            if "il_7d" in df.columns:
                il_frames[protocol] = df["il_7d"]

    if apy_frames:
        apy_data = pd.DataFrame(apy_frames)
    else:
        apy_data = pd.DataFrame()

    if il_frames:
        il_data = pd.DataFrame(il_frames)
    else:
        il_data = None

    # Align all DataFrames to a common date range
    if not tvl_data.empty and not apy_data.empty:
        common_start = max(tvl_data.index.min(), apy_data.index.min())
        common_end = min(tvl_data.index.max(), apy_data.index.max())

        # Trim to last 18 months (545 days) to keep the backtest focused
        target_start = common_end - pd.Timedelta(days=545)
        if target_start > common_start:
            common_start = target_start
            print(f"  Trimmed to last 18 months: {common_start.date()} to {common_end.date()}")

        # Use the common date range
        date_range = pd.date_range(start=common_start, end=common_end, freq="D")

        tvl_data = tvl_data.reindex(date_range).ffill().bfill()
        apy_data = apy_data.reindex(date_range).ffill().bfill()

        if il_data is not None:
            il_data = il_data.reindex(date_range).ffill().fillna(0)

    # Remove timezone info from index if present (engine uses naive timestamps)
    for df_ref in [tvl_data, apy_data]:
        if hasattr(df_ref.index, 'tz') and df_ref.index.tz is not None:
            df_ref.index = df_ref.index.tz_localize(None)
    if il_data is not None and hasattr(il_data.index, 'tz') and il_data.index.tz is not None:
        il_data.index = il_data.index.tz_localize(None)

    print(f"  Data aligned: {len(tvl_data)} days, {len(tvl_data.columns)} protocols")
    print(f"  Protocols in TVL data: {list(tvl_data.columns)}")
    print(f"  Protocols in APY data: {list(apy_data.columns)}")
    print(f"  Date range: {tvl_data.index[0]} to {tvl_data.index[-1]}")

    return EngineDataset(
        tvl_data=tvl_data,
        apy_data=apy_data,
        eth_price=fetched_data.eth_price,
        il_data=il_data,
    )


def main():
    """Run the full backtest pipeline."""
    start_time = time.time()

    print("=" * 70)
    print("  DeFi Strategy Backtest Engine")
    print("  Replaying DSCE risk rules against real historical data")
    print("=" * 70)
    print()

    # ── Step 1: Fetch Data ──────────────────────────────────────────
    print(">> Step 1/5: Fetching historical data...")
    fetched_data = fetch_all_data()
    print(f"    Data range: {fetched_data.data_start} to {fetched_data.data_end}")
    print(f"    Protocols with TVL data: {list(fetched_data.protocol_tvl.keys())}")
    print(f"    Protocols with APY data: {list(fetched_data.pool_apy.keys())}")
    print(f">> Done ({time.time() - start_time:.1f}s)")
    print()

    # ── Step 2: Run Simulation ──────────────────────────────────────
    print(">> Step 2/5: Running backtest simulation...")
    engine_dataset = prepare_engine_dataset(fetched_data)
    result = run_backtest(engine_dataset)
    print(f"    Simulated {(result.end_date - result.start_date).days} days")
    print(f"    Trigger fires: {len(result.trigger_log)}")
    print(f">> Done ({time.time() - start_time:.1f}s)")
    print()

    # ── Step 3: Compute Metrics ─────────────────────────────────────
    print(">> Step 3/5: Computing metrics...")

    # Prepare trigger log in the format expected by metrics module
    formatted_triggers = []
    for t in result.trigger_log:
        event = t.get("event")
        formatted_triggers.append({
            "date": t.get("date"),
            "protocol": t.get("protocol"),
            "trigger_type": event.trigger_type if event else "",
            "severity": event.severity if event else "WARNING",
            "value": event.value if event else 0.0,
            "threshold": event.threshold if event else 0.0,
            "description": event.description if event else "",
            "portfolio_value_before": t.get("portfolio_value_before", 0),
            "portfolio_value_after": t.get("portfolio_value_after", 0),
            "position_value": 0,  # Will be estimated by the analysis
        })

    # Compute average ETH staking APY from Lido data for Sharpe calculation
    eth_staking_curve = result.equity_curves.get(
        "ETH Staking Benchmark",
        result.equity_curves.get("ETH Staking", pd.Series(dtype=float))
    )
    if len(eth_staking_curve) > 1:
        avg_eth_return = eth_staking_curve.pct_change().mean()
        avg_eth_apy = avg_eth_return * 365
    else:
        avg_eth_apy = 0.035

    metrics = compute_all_metrics(
        equity_curves=result.equity_curves,
        daily_returns=result.daily_returns,
        trigger_log=formatted_triggers,
        pool_apy=fetched_data.pool_apy,
        pool_tvl=fetched_data.protocol_tvl,
        eth_staking_apy=avg_eth_apy,
        gas_costs=result.strategy_gas,
        slippage_costs=result.strategy_slippage,
        rebalance_counts=result.strategy_rebalances,
    )
    
    # Slice for Holdout Period (last 180 days)
    holdout_curves = {}
    holdout_returns = {}
    for name, curve in result.equity_curves.items():
        if len(curve) > 180:
            holdout_curves[name] = curve.iloc[-180:]
        else:
            holdout_curves[name] = curve
            
    for name, rets in result.daily_returns.items():
        if len(rets) > 180:
            holdout_returns[name] = rets.iloc[-180:]
        else:
            holdout_returns[name] = rets
            
    metrics_holdout = compute_all_metrics(
        equity_curves=holdout_curves,
        daily_returns=holdout_returns,
        trigger_log=[],  # Simplified for holdout just to get returns
        pool_apy=fetched_data.pool_apy,
        pool_tvl=fetched_data.protocol_tvl,
        eth_staking_apy=avg_eth_apy,
        gas_costs={},  # Not recalculating exact gas for holdout
        slippage_costs={},
        rebalance_counts={},
    )

    print(f"    Strategies analysed: {list(metrics.strategy_metrics.keys())}")
    if metrics.trigger_summary:
        print(f"    Triggers: {metrics.trigger_summary.total_fires} total, "
              f"{metrics.trigger_summary.true_positives} true positives, "
              f"{metrics.trigger_summary.false_alarms} false alarms")
    print(f">> Done ({time.time() - start_time:.1f}s)")
    print()

    # ── Step 4: Generate Charts ─────────────────────────────────────
    print(">> Step 4/5: Generating charts...")
    equity_path = plot_equity_curves(result.equity_curves, result.initial_capital)

    dsce_curve = result.equity_curves.get("DSCE System", pd.Series(dtype=float))
    trigger_entries = metrics.trigger_summary.entries if metrics.trigger_summary else []
    trigger_path = plot_trigger_annotations(
        equity_curve=dsce_curve,
        trigger_log=formatted_triggers,
        trigger_analysis=trigger_entries,
    )
    print(f">> Done ({time.time() - start_time:.1f}s)")
    print()

    # ── Step 5: Generate Report ─────────────────────────────────────
    print(">> Step 5/5: Generating report...")
    report_path = generate_report(
        metrics=metrics,
        metrics_holdout=metrics_holdout,
        equity_curve_path=equity_path,
        trigger_chart_path=trigger_path,
    )
    print(f">> Done ({time.time() - start_time:.1f}s)")
    print()

    # ── Summary ─────────────────────────────────────────────────────
    total_time = time.time() - start_time
    print("=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)
    print()

    for name, sm in metrics.strategy_metrics.items():
        print(f"  {name}:")
        print(f"    Total Return: {sm.total_return_pct:+.2f}%")
        print(f"    CAGR:         {sm.cagr_pct:.2f}%")
        print(f"    Sharpe:       {sm.sharpe_ratio:.3f}")
        print(f"    Max Drawdown: {sm.max_drawdown_pct:.2f}%")
        print(f"    Final NAV:    ${sm.final_nav/1e6:.2f}M")
        if name in metrics_holdout.strategy_metrics:
            hm = metrics_holdout.strategy_metrics[name]
            print(f"    [Holdout 6m] Total Return: {hm.total_return_pct:+.2f}% | Sharpe: {hm.sharpe_ratio:.3f}")
        print()

    if metrics.trigger_summary:
        ts = metrics.trigger_summary
        print(f"  Trigger Analysis:")
        print(f"    Total fires:     {ts.total_fires}")
        print(f"    True positives:  {ts.true_positives}")
        print(f"    False alarms:    {ts.false_alarms}")
        print(f"    Precision:       {ts.precision:.1%}")
        print()

    print(f"  Output files:")
    print(f"    Report:         {report_path}")
    print(f"    Equity curves:  {equity_path}")
    print(f"    Trigger chart:  {trigger_path}")
    print()
    print(f"  Total runtime: {total_time:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
