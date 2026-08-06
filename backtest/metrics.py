"""
Backtest Metrics Module
=======================

Computes performance metrics for all three strategies and performs
trigger analysis for the DSCE System strategy.

Metrics computed:
- Total return
- CAGR (Compound Annual Growth Rate)
- Sharpe ratio (using ETH staking as risk-free rate)
- Maximum drawdown
- Trigger precision analysis (true positives vs false alarms)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────

@dataclass
class StrategyMetrics:
    """Performance metrics for a single strategy."""

    strategy_name: str
    total_return_pct: float       # (final - initial) / initial * 100
    cagr_pct: float               # annualised compound growth rate
    sharpe_ratio: float           # annualised, using ETH staking as risk-free
    max_drawdown_pct: float       # maximum peak-to-trough decline
    max_drawdown_date: str        # date of maximum drawdown trough
    final_nav: float              # final portfolio value
    initial_nav: float            # starting portfolio value
    total_gas_paid: float         # total gas costs over the period
    total_slippage_paid: float    # total slippage costs over the period
    num_rebalances: int           # number of rebalance events
    avg_daily_return_pct: float   # mean daily return
    volatility_annual_pct: float  # annualised standard deviation of daily returns


@dataclass
class TriggerAnalysisEntry:
    """Analysis of a single trigger fire: was it a true positive or false alarm?"""

    date: str
    protocol: str
    trigger_type: str           # 'tvl_drop', 'apy_anomaly', 'tier_migration'
    severity: str               # 'WARNING', 'CRITICAL'
    trigger_value: float        # the metric value that breached
    threshold: float            # the threshold that was breached
    description: str
    outcome: str                # 'true_positive' or 'false_alarm'
    outcome_reason: str         # explanation of classification
    portfolio_value_at_exit: float
    estimated_loss_avoided: float  # positive if true positive, negative if false alarm cost


@dataclass
class TriggerSummary:
    """Aggregate trigger analysis for Strategy 1."""

    total_fires: int
    fires_by_type: Dict[str, int]          # {trigger_type: count}
    true_positives: int
    false_alarms: int
    precision: float                        # true_positives / total_fires
    avg_loss_avoided_per_tp: float          # avg $ saved per true positive
    avg_yield_cost_per_fa: float            # avg $ lost per false alarm (missed yield)
    entries: List[TriggerAnalysisEntry]


@dataclass
class BacktestMetrics:
    """Complete metrics output for the backtest."""

    strategy_metrics: Dict[str, StrategyMetrics]
    trigger_summary: Optional[TriggerSummary]
    backtest_start: str
    backtest_end: str
    num_trading_days: int


# ─────────────────────────────────────────────────────────────────────
# Metric computation
# ─────────────────────────────────────────────────────────────────────

def compute_strategy_metrics(
    name: str,
    equity_curve: pd.Series,
    daily_returns: pd.Series,
    eth_staking_daily_rate: float = 0.035 / 365,
    gas_costs: float = 0.0,
    slippage_costs: float = 0.0,
    num_rebalances: int = 0,
) -> StrategyMetrics:
    """
    Compute performance metrics for a single strategy.

    Args:
        name: Strategy name.
        equity_curve: Daily NAV series (DatetimeIndex).
        daily_returns: Daily percentage returns (DatetimeIndex).
        eth_staking_daily_rate: Daily risk-free rate for Sharpe calculation.
        gas_costs: Total gas costs paid over the period.
        slippage_costs: Total slippage costs over the period.
        num_rebalances: Number of rebalance events.

    Returns:
        StrategyMetrics with all computed values.
    """
    # Filter out any NaN values
    equity_curve = equity_curve.dropna()
    daily_returns = daily_returns.dropna()

    if len(equity_curve) < 2:
        return StrategyMetrics(
            strategy_name=name,
            total_return_pct=0.0,
            cagr_pct=0.0,
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            max_drawdown_date="N/A",
            final_nav=equity_curve.iloc[-1] if len(equity_curve) > 0 else 0.0,
            initial_nav=equity_curve.iloc[0] if len(equity_curve) > 0 else 0.0,
            total_gas_paid=gas_costs,
            total_slippage_paid=slippage_costs,
            num_rebalances=num_rebalances,
            avg_daily_return_pct=0.0,
            volatility_annual_pct=0.0,
        )

    initial_nav = equity_curve.iloc[0]
    final_nav = equity_curve.iloc[-1]
    num_days = (equity_curve.index[-1] - equity_curve.index[0]).days

    # Total return
    total_return_pct = (final_nav - initial_nav) / initial_nav * 100

    # CAGR
    if num_days > 0 and initial_nav > 0 and final_nav > 0:
        cagr = (final_nav / initial_nav) ** (365.0 / num_days) - 1
        cagr_pct = cagr * 100
    else:
        cagr_pct = 0.0

    # Sharpe ratio (annualised)
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        excess_returns = daily_returns - eth_staking_daily_rate
        sharpe = excess_returns.mean() / daily_returns.std() * np.sqrt(365)
    else:
        sharpe = 0.0

    # Max drawdown
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    max_dd_pct = drawdown.min() * 100
    max_dd_date = drawdown.idxmin()
    if isinstance(max_dd_date, pd.Timestamp):
        max_dd_date_str = max_dd_date.strftime("%Y-%m-%d")
    else:
        max_dd_date_str = str(max_dd_date)

    # Daily return stats
    avg_daily_return = daily_returns.mean() * 100
    volatility_annual = daily_returns.std() * np.sqrt(365) * 100

    return StrategyMetrics(
        strategy_name=name,
        total_return_pct=round(total_return_pct, 4),
        cagr_pct=round(cagr_pct, 4),
        sharpe_ratio=round(sharpe, 4),
        max_drawdown_pct=round(max_dd_pct, 4),
        max_drawdown_date=max_dd_date_str,
        final_nav=round(final_nav, 2),
        initial_nav=round(initial_nav, 2),
        total_gas_paid=round(gas_costs, 2),
        total_slippage_paid=round(slippage_costs, 2),
        num_rebalances=num_rebalances,
        avg_daily_return_pct=round(avg_daily_return, 6),
        volatility_annual_pct=round(volatility_annual, 4),
    )


# ─────────────────────────────────────────────────────────────────────
# Trigger analysis
# ─────────────────────────────────────────────────────────────────────

def analyse_triggers(
    trigger_log: List[dict],
    pool_apy: Dict[str, pd.DataFrame],
    pool_tvl: Dict[str, pd.DataFrame],
    lookforward_days: int = 14,
    loss_threshold_pct: float = 5.0,
) -> TriggerSummary:
    """
    Analyse each trigger fire to determine if it was a true positive or false alarm.

    Classification logic:
    - TRUE POSITIVE: Within `lookforward_days` after the trigger fired, the pool's
      TVL dropped by more than `loss_threshold_pct` from the trigger-fire date,
      OR the pool's APY dropped to near-zero (indicating a genuine problem).
    - FALSE ALARM: The pool recovered within `lookforward_days` with no material
      loss — the exit cost the portfolio missed yield.

    Args:
        trigger_log: List of trigger event dicts from the engine.
        pool_apy: Dict of protocol_slug -> APY DataFrame.
        pool_tvl: Dict of protocol_slug -> TVL DataFrame (from protocol_tvl, with tvl_usd column).
        lookforward_days: Number of days to look ahead for outcome classification.
        loss_threshold_pct: TVL decline threshold to classify as true positive.

    Returns:
        TriggerSummary with per-trigger analysis and aggregate stats.
    """
    entries: List[TriggerAnalysisEntry] = []

    for trigger in trigger_log:
        trigger_date = pd.Timestamp(trigger.get("date"))
        # Ensure trigger_date is tz-naive for comparison
        if trigger_date.tzinfo is not None:
            trigger_date = trigger_date.tz_localize(None)
        protocol = trigger.get("protocol", "")
        trigger_type = trigger.get("trigger_type", "")
        severity = trigger.get("severity", "WARNING")
        value = trigger.get("value", 0.0)
        threshold = trigger.get("threshold", 0.0)
        description = trigger.get("description", "")
        pv_at_exit = trigger.get("portfolio_value_before", 0.0)

        # Look ahead at TVL and APY to classify the outcome
        outcome = "false_alarm"
        outcome_reason = ""
        estimated_impact = 0.0

        # Get TVL data for this protocol
        tvl_df = pool_tvl.get(protocol)
        apy_df = pool_apy.get(protocol)

        if tvl_df is not None and len(tvl_df) > 0:
            # Normalize timezone on the DataFrame index for comparison
            _tvl_df = tvl_df.copy()
            if hasattr(_tvl_df.index, 'tz') and _tvl_df.index.tz is not None:
                _tvl_df.index = _tvl_df.index.tz_localize(None)
            lookforward_end = trigger_date + timedelta(days=lookforward_days)

            # Get TVL at trigger date and the minimum TVL in the lookforward window
            tvl_col = "tvl_usd" if "tvl_usd" in _tvl_df.columns else _tvl_df.columns[0]
            mask = (_tvl_df.index >= trigger_date) & (_tvl_df.index <= lookforward_end)
            window_tvl = _tvl_df.loc[mask, tvl_col] if tvl_col in _tvl_df.columns else pd.Series(dtype=float)

            if len(window_tvl) >= 2:
                tvl_at_trigger = window_tvl.iloc[0]
                tvl_min_after = window_tvl.min()

                if tvl_at_trigger > 0:
                    tvl_decline_pct = (tvl_min_after - tvl_at_trigger) / tvl_at_trigger * 100

                    if tvl_decline_pct < -loss_threshold_pct:
                        outcome = "true_positive"
                        outcome_reason = (
                            f"TVL declined {tvl_decline_pct:.1f}% within {lookforward_days} days "
                            f"(below -{loss_threshold_pct}% threshold)"
                        )
                        # Estimate loss avoided: what would the portfolio have lost
                        # if it stayed in this position
                        alloc_at_exit = trigger.get("position_value", pv_at_exit * 0.15)
                        estimated_impact = abs(alloc_at_exit * tvl_decline_pct / 100)
                    else:
                        outcome = "false_alarm"
                        outcome_reason = (
                            f"TVL changed only {tvl_decline_pct:.1f}% within {lookforward_days} days "
                            f"(above -{loss_threshold_pct}% threshold) — pool recovered"
                        )
                        # Estimate missed yield
                        if apy_df is not None and len(apy_df) > 0:
                            _apy_df = apy_df.copy()
                            if hasattr(_apy_df.index, 'tz') and _apy_df.index.tz is not None:
                                _apy_df.index = _apy_df.index.tz_localize(None)
                            apy_col = "apy" if "apy" in _apy_df.columns else _apy_df.columns[0]
                            apy_mask = (_apy_df.index >= trigger_date) & (_apy_df.index <= lookforward_end)
                            window_apy = _apy_df.loc[apy_mask, apy_col] if apy_col in _apy_df.columns else pd.Series(dtype=float)
                            if len(window_apy) > 0:
                                avg_missed_apy = window_apy.mean()
                                alloc_at_exit = trigger.get("position_value", pv_at_exit * 0.15)
                                missed_yield = alloc_at_exit * (avg_missed_apy / 100) * (lookforward_days / 365)
                                estimated_impact = -missed_yield  # negative = cost
            else:
                outcome_reason = "Insufficient lookforward data to classify"
        else:
            outcome_reason = "No TVL data available for classification"

        # Also check APY-based classification for apy_anomaly triggers
        if trigger_type == "apy_anomaly" and apy_df is not None and len(apy_df) > 0:
            _apy_df2 = apy_df.copy()
            if hasattr(_apy_df2.index, 'tz') and _apy_df2.index.tz is not None:
                _apy_df2.index = _apy_df2.index.tz_localize(None)
            apy_col = "apy" if "apy" in _apy_df2.columns else _apy_df2.columns[0]
            lookforward_end = trigger_date + timedelta(days=lookforward_days)
            apy_mask = (_apy_df2.index >= trigger_date) & (_apy_df2.index <= lookforward_end)
            window_apy = _apy_df2.loc[apy_mask, apy_col] if apy_col in _apy_df2.columns else pd.Series(dtype=float)

            if len(window_apy) >= 2:
                apy_at_trigger = window_apy.iloc[0]
                apy_min_after = window_apy.min()

                # If APY crashed to near-zero, that's a true positive regardless of TVL
                if apy_at_trigger > 0 and apy_min_after < apy_at_trigger * 0.3:
                    outcome = "true_positive"
                    outcome_reason = (
                        f"APY dropped from {apy_at_trigger:.1f}% to {apy_min_after:.1f}% "
                        f"within {lookforward_days} days — genuine yield collapse"
                    )

        entries.append(TriggerAnalysisEntry(
            date=trigger_date.strftime("%Y-%m-%d"),
            protocol=protocol,
            trigger_type=trigger_type,
            severity=severity,
            trigger_value=round(value, 2),
            threshold=round(threshold, 2),
            description=description,
            outcome=outcome,
            outcome_reason=outcome_reason,
            portfolio_value_at_exit=round(pv_at_exit, 2),
            estimated_loss_avoided=round(estimated_impact, 2),
        ))

    # Aggregate stats
    total_fires = len(entries)
    true_positives = sum(1 for e in entries if e.outcome == "true_positive")
    false_alarms = sum(1 for e in entries if e.outcome == "false_alarm")

    fires_by_type: Dict[str, int] = {}
    for e in entries:
        fires_by_type[e.trigger_type] = fires_by_type.get(e.trigger_type, 0) + 1

    precision = true_positives / total_fires if total_fires > 0 else 0.0

    tp_impacts = [e.estimated_loss_avoided for e in entries if e.outcome == "true_positive"]
    fa_impacts = [abs(e.estimated_loss_avoided) for e in entries if e.outcome == "false_alarm"]

    avg_loss_avoided = sum(tp_impacts) / len(tp_impacts) if tp_impacts else 0.0
    avg_yield_cost = sum(fa_impacts) / len(fa_impacts) if fa_impacts else 0.0

    return TriggerSummary(
        total_fires=total_fires,
        fires_by_type=fires_by_type,
        true_positives=true_positives,
        false_alarms=false_alarms,
        precision=round(precision, 4),
        avg_loss_avoided_per_tp=round(avg_loss_avoided, 2),
        avg_yield_cost_per_fa=round(avg_yield_cost, 2),
        entries=entries,
    )


def compute_all_metrics(
    equity_curves: Dict[str, pd.Series],
    daily_returns: Dict[str, pd.Series],
    trigger_log: List[dict],
    pool_apy: Dict[str, pd.DataFrame],
    pool_tvl: Dict[str, pd.DataFrame],
    eth_staking_apy: float = 0.035,
    gas_costs: Optional[Dict[str, float]] = None,
    slippage_costs: Optional[Dict[str, float]] = None,
    rebalance_counts: Optional[Dict[str, int]] = None,
) -> BacktestMetrics:
    """
    Compute all backtest metrics for all strategies.

    Args:
        equity_curves: {strategy_name: daily NAV Series}.
        daily_returns: {strategy_name: daily return Series}.
        trigger_log: List of trigger event dicts from engine.
        pool_apy: {protocol_slug: APY DataFrame}.
        pool_tvl: {protocol_slug: TVL DataFrame}.
        eth_staking_apy: Annual ETH staking rate for Sharpe calculation.
        gas_costs: {strategy_name: total gas paid}.
        slippage_costs: {strategy_name: total slippage paid}.
        rebalance_counts: {strategy_name: number of rebalances}.

    Returns:
        BacktestMetrics with all strategy metrics and trigger analysis.
    """
    gas_costs = gas_costs or {}
    slippage_costs = slippage_costs or {}
    rebalance_counts = rebalance_counts or {}

    eth_daily_rate = eth_staking_apy / 365

    strategy_metrics: Dict[str, StrategyMetrics] = {}
    for name, curve in equity_curves.items():
        returns = daily_returns.get(name, pd.Series(dtype=float))
        metrics = compute_strategy_metrics(
            name=name,
            equity_curve=curve,
            daily_returns=returns,
            eth_staking_daily_rate=eth_daily_rate,
            gas_costs=gas_costs.get(name, 0.0),
            slippage_costs=slippage_costs.get(name, 0.0),
            num_rebalances=rebalance_counts.get(name, 0),
        )
        strategy_metrics[name] = metrics

    # Trigger analysis (only for DSCE System)
    trigger_summary = None
    if trigger_log:
        trigger_summary = analyse_triggers(
            trigger_log=trigger_log,
            pool_apy=pool_apy,
            pool_tvl=pool_tvl,
        )

    # Date range
    all_dates = []
    for curve in equity_curves.values():
        if len(curve) > 0:
            all_dates.extend([curve.index[0], curve.index[-1]])

    if all_dates:
        start_date = min(all_dates).strftime("%Y-%m-%d")
        end_date = max(all_dates).strftime("%Y-%m-%d")
        num_days = (max(all_dates) - min(all_dates)).days
    else:
        start_date = "N/A"
        end_date = "N/A"
        num_days = 0

    return BacktestMetrics(
        strategy_metrics=strategy_metrics,
        trigger_summary=trigger_summary,
        backtest_start=start_date,
        backtest_end=end_date,
        num_trading_days=num_days,
    )
