import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backtest.risk_engine import HistoricalRiskEngine, TriggerEvent

@dataclass
class BacktestDataset:
    tvl_data: pd.DataFrame
    apy_data: pd.DataFrame
    eth_price: pd.DataFrame
    il_data: Optional[pd.DataFrame] = None
    pool_data: Optional[pd.DataFrame] = None

@dataclass
class BacktestResult:
    equity_curves: Dict[str, pd.Series]
    trigger_log: List[dict]
    daily_returns: Dict[str, pd.Series]
    strategy_names: List[str]
    initial_capital: float
    start_date: datetime
    end_date: datetime
    # Per-strategy cost tracking
    strategy_gas: Dict[str, float] = None  # {strategy_name: total_gas}
    strategy_slippage: Dict[str, float] = None  # {strategy_name: total_slippage}
    strategy_rebalances: Dict[str, int] = None  # {strategy_name: rebalance_count}

class Position:
    def __init__(self, protocol: str, allocation_usd: float, entry_date: date, last_apy: float):
        self.protocol = protocol
        self.allocation_usd = allocation_usd
        self.entry_date = entry_date
        self.last_apy = last_apy
        self.in_withdrawal = False
        self.withdrawal_release_date: Optional[date] = None
        self.cooldown_until: Optional[date] = None

def get_slippage(tvl: float) -> float:
    if tvl > 100_000_000:
        return 0.001
    elif tvl >= 10_000_000:
        return 0.003
    return 0.01

def safe_get(df: pd.DataFrame, date, col: str) -> float:
    """Safely get a value from a DataFrame, raising ValueError if column missing or NaN."""
    if col not in df.columns:
        raise ValueError(f"Column '{col}' not found in data.")
    try:
        val = df.at[date, col]
        if pd.isna(val):
            raise ValueError(f"NaN value encountered for '{col}' at date {date}.")
        return float(val)
    except KeyError:
        raise ValueError(f"Date '{date}' not found in data index.")
    except (KeyError, IndexError):
        return default

def run_backtest(dataset: BacktestDataset, sim_start=None, sim_end=None) -> BacktestResult:
    # Load config
    config_path = os.path.join(os.path.dirname(__file__), "..", "dsce", "data", "portfolio_config.json")
    with open(config_path, "r") as f:
        portfolio_config = json.load(f)
        
    protocol_configs = {s["protocol_name"]: s for s in portfolio_config["strategies"]}
    
    # Only include protocols that have APY data available
    available_protocols = list(dataset.apy_data.columns)
    print(f"  Protocols with APY data available: {available_protocols}")
    
    # Filter protocol_configs to available protocols only
    active_configs = {k: v for k, v in protocol_configs.items() if k in available_protocols}
    risk_engine = HistoricalRiskEngine(active_configs)
    
    initial_capital = 100_000_000.0
    
    dates = dataset.apy_data.index.sort_values()
    if sim_start:
        dates = dates[dates >= sim_start]
    if sim_end:
        dates = dates[dates <= sim_end]
        
    start_date = dates[0]
    end_date = dates[-1]
    
    # Init Strategy 1 — redistribute allocation from missing protocols
    dsce_positions: Dict[str, Position] = {}
    dsce_cash = 0.0
    dsce_nav_series = pd.Series(index=dates, dtype=float)
    dsce_nav = initial_capital
    
    single_cap = portfolio_config.get("concentration_limits", {}).get("max_single_strategy_pct", 40.0) / 100.0
    hhi_cap = 0.25 # Implicit from DSCE design, not in config json explicitly but we'll parameterize it
    
    init_allocs = {}
    total_alloc = sum(s["allocation_usd"] for s in portfolio_config["strategies"])
    for s in portfolio_config["strategies"]:
        init_allocs[s["protocol_name"]] = s["allocation_usd"] / total_alloc
        
    # Filter to available protocols and redistribute missing weight proportionally
    active_allocs = {k: v for k, v in init_allocs.items() if k in available_protocols}
    missing_weight = sum(v for k, v in init_allocs.items() if k not in available_protocols)
    if active_allocs and missing_weight > 0:
        total_active = sum(active_allocs.values())
        for k in active_allocs:
            active_allocs[k] += missing_weight * (active_allocs[k] / total_active)
    
    print(f"  Active allocations (after redistribution): {active_allocs}")
    for p, w in active_allocs.items():
        dsce_positions[p] = Position(p, initial_capital * w, start_date.date(), 0.0)
        
    # Init Strategy 2 — only consider available protocols
    naive_nav_series = pd.Series(index=dates, dtype=float)
    naive_nav = initial_capital
    day1_apys = dataset.apy_data.loc[start_date].dropna()
    best_pool_day1 = day1_apys.idxmax()
    naive_position = Position(best_pool_day1, initial_capital, start_date.date(), day1_apys[best_pool_day1])
    
    # Init Strategy 3
    eth_nav_series = pd.Series(index=dates, dtype=float)
    eth_nav = initial_capital
    eth_position = Position('lido', initial_capital, start_date.date(), 0.0)
    
    trigger_log = []
    prev_reports = {}
    total_days = len(dates)
    
    # Global cost tracking
    dsce_total_gas = 0.0
    dsce_total_slippage = 0.0
    dsce_rebalance_count = 0
    naive_total_gas = 0.0
    naive_total_slippage = 0.0
    naive_rebalance_count = 0
    
    for i, current_date in enumerate(dates):
        if i % 7 == 0:
            print(f"  Simulating week {i//7 + 1} / {total_days//7 + 1}...")
            
        current_date_pdt = current_date.date()
        
        # 1. Earn Daily Yield
        # Strategy 3 (ETH staking via Lido)
        lido_apy = safe_get(dataset.apy_data, current_date, 'lido')
        yield_earned = eth_position.allocation_usd * (lido_apy / 100.0) / 365.0
        eth_position.allocation_usd += yield_earned
        eth_nav = eth_position.allocation_usd
        eth_nav_series[current_date] = eth_nav
        
        # Strategy 2 (Naive yield-chaser)
        apy_n = safe_get(dataset.apy_data, current_date, naive_position.protocol)
        yield_n = naive_position.allocation_usd * (apy_n / 100.0) / 365.0
        if dataset.il_data is not None and naive_position.protocol in dataset.il_data.columns:
            il = safe_get(dataset.il_data, current_date, naive_position.protocol)
            yield_n -= naive_position.allocation_usd * il
        naive_position.allocation_usd += yield_n
        naive_nav = naive_position.allocation_usd
        naive_nav_series[current_date] = naive_nav
        
        # Strategy 1
        dsce_nav = dsce_cash
        for p, pos in dsce_positions.items():
            if pos.in_withdrawal:
                if pos.withdrawal_release_date and current_date_pdt >= pos.withdrawal_release_date:
                    pos.in_withdrawal = False
                    dsce_cash += pos.allocation_usd
                    pos.allocation_usd = 0.0
                else:
                    dsce_nav += pos.allocation_usd
                continue
                
            apy = safe_get(dataset.apy_data, current_date, p)
            pos.last_apy = apy
            yield_p = pos.allocation_usd * (apy / 100.0) / 365.0
            
            cfg = protocol_configs.get(p, {})
            if cfg.get("asset_type") == "LP_token" and dataset.il_data is not None and p in dataset.il_data.columns:
                il = safe_get(dataset.il_data, current_date, p)
                yield_p -= pos.allocation_usd * il
                
            pos.allocation_usd += yield_p
            dsce_nav += pos.allocation_usd
            
        # Clean up empty positions
        dsce_positions = {k: v for k, v in dsce_positions.items() if v.allocation_usd > 0 or v.in_withdrawal}
        dsce_nav_series[current_date] = dsce_nav
        
        # 2. Check Triggers for DSCE
        # Score current day first to get reports
        allocs = {k: v.allocation_usd for k, v in dsce_positions.items()}
        current_reports = risk_engine.score_at_date(current_date, dataset.tvl_data, dataset.apy_data, allocs)
        
        for p in list(dsce_positions.keys()):
            pos = dsce_positions[p]
            if pos.in_withdrawal:
                continue
                
            events = risk_engine.check_triggers(current_date, p, dataset.tvl_data, dataset.apy_data, dataset.eth_price, prev_reports, current_reports)
            if events:
                # Trigger fired, exit immediately
                for ev in events:
                    trigger_log.append({
                        "date": current_date_pdt,
                        "protocol": p,
                        "event": ev,
                        "portfolio_value_before": dsce_nav,
                        "action_taken": f"Exit position {p} due to {ev.trigger_type}"
                    })
                
                # Apply slippage & gas
                tvl = safe_get(dataset.tvl_data, current_date, p)
                slip = get_slippage(tvl)
                val_to_exit = pos.allocation_usd
                val_after_slip = val_to_exit * (1 - slip) - 5.0 # gas
                slippage_cost = val_to_exit * slip
                dsce_total_gas += 5.0
                dsce_total_slippage += slippage_cost
                
                if p == 'eigenlayer':
                    pos.in_withdrawal = True
                    pos.withdrawal_release_date = current_date_pdt + timedelta(days=7)
                    pos.allocation_usd = val_after_slip
                else:
                    dsce_cash += val_after_slip
                    del dsce_positions[p]
                    
                dsce_nav = dsce_cash + sum(v.allocation_usd for v in dsce_positions.values())
                trigger_log[-1]["portfolio_value_after"] = dsce_nav
                
                # set cooldown
                if p not in dsce_positions:
                    pos.cooldown_until = current_date_pdt + timedelta(days=7)
        
        # 3. Weekly Rebalance (Mondays)
        if current_date.dayofweek == 0:
            # Naive
            curr_apys = dataset.apy_data.loc[current_date].dropna()
            if len(curr_apys) > 0:
                best_pool = curr_apys.idxmax()
            else:
                best_pool = naive_position.protocol
            if best_pool != naive_position.protocol:
                tvl = safe_get(dataset.tvl_data, current_date, naive_position.protocol)
                slip_out = get_slippage(tvl)
                tvl_in = safe_get(dataset.tvl_data, current_date, best_pool)
                slip_in = get_slippage(tvl_in)
                
                val = naive_position.allocation_usd
                slippage_out = val * slip_out
                val = val * (1 - slip_out) - 5.0
                slippage_in = val * slip_in
                val = val * (1 - slip_in) - 5.0
                naive_total_gas += 10.0  # 2 transactions
                naive_total_slippage += slippage_out + slippage_in
                naive_rebalance_count += 1
                naive_position = Position(best_pool, val, current_date_pdt, curr_apys[best_pool])
                naive_nav = val
                naive_nav_series[current_date] = naive_nav
                
            # DSCE
            eligible_prots = []
            rays = {}
            for p, rpt in current_reports.items():
                if rpt.composite_score <= 6.0:
                    # check cooldown
                    pos = dsce_positions.get(p)
                    if pos and pos.cooldown_until and pos.cooldown_until > current_date_pdt:
                        continue
                        
                    eligible_prots.append(p)
                    apy = safe_get(dataset.apy_data, current_date, p)
                    if apy > 0:
                        rays[p] = apy / rpt.composite_score
                    else:
                        rays[p] = 0.0
                        
            # calc target allocs
            tot_ray = sum(rays.values())
            target_alloc = {}
            total_investable = dsce_cash + sum(v.allocation_usd for v in dsce_positions.values() if not v.in_withdrawal)
            
            if tot_ray > 0 and total_investable > 0:
                for p in eligible_prots:
                    target_alloc[p] = (rays[p] / tot_ray)
                    
                # HHI & cap logic
                # simple cap
                for p in target_alloc:
                    if target_alloc[p] > single_cap:
                        diff = target_alloc[p] - single_cap
                        target_alloc[p] = single_cap
                        others = [k for k in target_alloc if k != p]
                        if others:
                            add = diff / len(others)
                            for k in others:
                                target_alloc[k] += add
                                
                # HHI
                hhi = sum(v*v for v in target_alloc.values())
                while hhi > hhi_cap:
                    top_p = max(target_alloc, key=target_alloc.get)
                    target_alloc[top_p] -= 0.01
                    others = [k for k in target_alloc if k != top_p]
                    if others:
                        add = 0.01 / len(others)
                        for k in others:
                            target_alloc[k] += add
                    hhi = sum(v*v for v in target_alloc.values())
                    
                # Execute rebalance
                new_positions = {}
                gas_paid = 0
                rebal_slip = 0.0
                
                # Sells
                for p, pos in list(dsce_positions.items()):
                    if pos.in_withdrawal:
                        new_positions[p] = pos
                        continue
                    
                    target = target_alloc.get(p, 0.0) * total_investable
                    if pos.allocation_usd > target:
                        diff = pos.allocation_usd - target
                        # apply slip
                        tvl = safe_get(dataset.tvl_data, current_date, p)
                        slip = get_slippage(tvl)
                        
                        if p == 'eigenlayer' and diff > 100: # non trivial
                            # need withdrawal
                            pos.in_withdrawal = True
                            pos.withdrawal_release_date = current_date_pdt + timedelta(days=7)
                            pos.allocation_usd = pos.allocation_usd - diff + (diff * (1-slip) - 5)
                            rebal_slip += diff * slip
                            gas_paid += 5
                            new_positions[p] = pos
                        else:
                            pos.allocation_usd = target
                            dsce_cash += (diff * (1-slip) - 5)
                            rebal_slip += diff * slip
                            gas_paid += 5
                            if target > 10:
                                new_positions[p] = pos
                    else:
                        new_positions[p] = pos
                
                dsce_positions = new_positions
                
                # Buys
                for p, frac in target_alloc.items():
                    target = frac * total_investable
                    curr = dsce_positions.get(p, Position(p, 0.0, current_date_pdt, 0.0)).allocation_usd
                    if target > curr + 10:
                        diff = target - curr
                        if diff <= dsce_cash:
                            tvl = safe_get(dataset.tvl_data, current_date, p)
                            slip = get_slippage(tvl)
                            invested = diff * (1-slip) - 5
                            rebal_slip += diff * slip
                            if p in dsce_positions:
                                dsce_positions[p].allocation_usd += invested
                            else:
                                dsce_positions[p] = Position(p, invested, current_date_pdt, 0.0)
                            dsce_cash -= diff
                            gas_paid += 5
                            
            dsce_total_gas += gas_paid
            dsce_total_slippage += rebal_slip
            if gas_paid > 0:
                dsce_rebalance_count += 1
            dsce_nav = dsce_cash + sum(v.allocation_usd for v in dsce_positions.values())
            dsce_nav_series[current_date] = dsce_nav

        prev_reports = current_reports

    curves = {
        'DSCE System': dsce_nav_series,
        'Naive Yield-Chaser': naive_nav_series,
        'ETH Staking Benchmark': eth_nav_series
    }
    
    daily_returns = {}
    for name, s in curves.items():
        daily_returns[name] = s.pct_change().fillna(0)

    return BacktestResult(
        equity_curves=curves,
        trigger_log=trigger_log,
        daily_returns=daily_returns,
        strategy_names=list(curves.keys()),
        initial_capital=initial_capital,
        start_date=start_date.to_pydatetime(),
        end_date=end_date.to_pydatetime(),
        strategy_gas={
            'DSCE System': dsce_total_gas,
            'Naive Yield-Chaser': naive_total_gas,
            'ETH Staking Benchmark': 0.0,
        },
        strategy_slippage={
            'DSCE System': dsce_total_slippage,
            'Naive Yield-Chaser': naive_total_slippage,
            'ETH Staking Benchmark': 0.0,
        },
        strategy_rebalances={
            'DSCE System': dsce_rebalance_count,
            'Naive Yield-Chaser': naive_rebalance_count,
            'ETH Staking Benchmark': 0,
        },
    )
