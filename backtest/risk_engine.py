import sys
import os
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dsce.modules.risk_scoring import RiskScorer, RiskReport, Strategy, RiskTier

@dataclass
class TriggerEvent:
    date: datetime
    protocol: str
    trigger_type: str  # 'tvl_drop', 'apy_anomaly', 'tier_migration'
    severity: str  # 'WARNING', 'CRITICAL'
    value: float
    threshold: float
    description: str

class HistoricalRiskEngine:
    LISTED_AT = {
        'lido': 1608163200,
        'aave': 1578528000,
        'curve-dex': 1578268800,
        'morpho': 1667260800,
        'pendle': 1624406400,
        'spark': 1683849600,
        'eigenlayer': 1686700800
    }

    def __init__(self, protocol_configs: Dict):
        """
        protocol_configs: dict of {protocol_name: {config dict}}
        """
        self.configs = protocol_configs
        self.scorer = RiskScorer()

    def score_at_date(self, date_val: pd.Timestamp, tvl_data: pd.DataFrame, apy_data: pd.DataFrame, portfolio_allocations: Dict[str, float]) -> Dict[str, RiskReport]:
        reports = {}
        date_timestamp = date_val.timestamp()

        for protocol, config in self.configs.items():
            # Get TVL
            tvl_today = 0.0
            if protocol in tvl_data.columns and date_val in tvl_data.index:
                tvl_today = tvl_data.at[date_val, protocol]

            date_7d_ago = date_val - pd.Timedelta(days=7)
            tvl_7d_ago = 0.0
            if protocol in tvl_data.columns and date_7d_ago in tvl_data.index:
                tvl_7d_ago = tvl_data.at[date_7d_ago, protocol]

            if pd.isna(tvl_today):
                tvl_today = 0.0
            if pd.isna(tvl_7d_ago):
                tvl_7d_ago = 0.0

            tvl_7d_change_pct = 0.0
            if tvl_7d_ago > 0:
                tvl_7d_change_pct = (tvl_today - tvl_7d_ago) / tvl_7d_ago * 100.0

            # Get APY
            apy_today = 0.0
            if protocol in apy_data.columns and date_val in apy_data.index:
                apy_today = apy_data.at[date_val, protocol]
            if pd.isna(apy_today):
                apy_today = 0.0

            listed_at = self.LISTED_AT.get(protocol, 0)
            age_days = int((date_timestamp - listed_at) / 86400)
            if age_days < 0:
                age_days = 0

            alloc = portfolio_allocations.get(protocol, 0.0)
            
            strategy_dict = {
                "strategy_name": config.get("strategy_name", protocol),
                "protocol_name": protocol,
                "tvl_usd": float(tvl_today),
                "tvl_7d_change_pct": float(tvl_7d_change_pct),
                "audit_count": int(config.get("audit_count", 0)),
                "age_days": age_days,
                "apy_pct": float(apy_today),
                "mcap_tvl_ratio": float(config.get("mcap_tvl_ratio", 0.0)),
                "chain": config.get("chain", "Ethereum"),
                "has_oracle": bool(config.get("has_oracle", False)),
                "oracle_provider": config.get("oracle_provider", None),
                "counterparty_type": config.get("counterparty_type", "decentralized"),
                "liquidity_depth_usd": float(tvl_today * 0.3),
                "asset_type": config.get("asset_type", "volatile"),
                "allocation_usd": float(alloc)
            }

            try:
                report = self.scorer.score_strategy(strategy_dict, portfolio_allocations)
                reports[protocol] = report
            except Exception as e:
                pass
                
        return reports

    def check_triggers(self, date_val: pd.Timestamp, protocol_slug: str, tvl_data: pd.DataFrame, apy_data: pd.DataFrame, eth_price_data: pd.DataFrame, prev_reports: Dict[str, RiskReport], current_reports: Dict[str, RiskReport]) -> List[TriggerEvent]:
        events = []
        date_7d_ago = date_val - pd.Timedelta(days=7)

        # 1. TVL Drop (Native ETH Denominated)
        tvl_today = 0.0
        if protocol_slug in tvl_data.columns and date_val in tvl_data.index:
            tvl_today = tvl_data.at[date_val, protocol_slug]
        
        tvl_7d_ago = 0.0
        if protocol_slug in tvl_data.columns and date_7d_ago in tvl_data.index:
            tvl_7d_ago = tvl_data.at[date_7d_ago, protocol_slug]

        eth_price_today = 1.0
        if date_val in eth_price_data.index:
            eth_price_today = eth_price_data.at[date_val, 'price_usd']
            
        eth_price_7d_ago = 1.0
        if date_7d_ago in eth_price_data.index:
            eth_price_7d_ago = eth_price_data.at[date_7d_ago, 'price_usd']

        if not pd.isna(tvl_today) and not pd.isna(tvl_7d_ago) and tvl_7d_ago > 0:
            native_tvl_today = tvl_today / eth_price_today
            native_tvl_7d_ago = tvl_7d_ago / eth_price_7d_ago
            tvl_change = (native_tvl_today - native_tvl_7d_ago) / native_tvl_7d_ago * 100
            
            if tvl_change < -30:
                events.append(TriggerEvent(date_val.to_pydatetime(), protocol_slug, 'tvl_drop', 'CRITICAL', tvl_change, -30.0, f"Native TVL dropped by {abs(tvl_change):.1f}%"))
            elif tvl_change < -15:
                events.append(TriggerEvent(date_val.to_pydatetime(), protocol_slug, 'tvl_drop', 'WARNING', tvl_change, -15.0, f"Native TVL dropped by {abs(tvl_change):.1f}%"))

        # 2. APY Anomaly
        apy_today = 0.0
        if protocol_slug in apy_data.columns and date_val in apy_data.index:
            apy_today = apy_data.at[date_val, protocol_slug]
            
        apy_7d_ago = 0.0
        if protocol_slug in apy_data.columns and date_7d_ago in apy_data.index:
            apy_7d_ago = apy_data.at[date_7d_ago, protocol_slug]
            
        if not pd.isna(apy_today) and not pd.isna(apy_7d_ago) and apy_7d_ago > 0:
            apy_change_rel = abs(apy_today - apy_7d_ago) / apy_7d_ago * 100
            apy_change_abs = abs(apy_today - apy_7d_ago)
            # Compound trigger: >20% relative AND >1.5% absolute
            if apy_change_rel > 20 and apy_change_abs > 1.5:
                events.append(TriggerEvent(date_val.to_pydatetime(), protocol_slug, 'apy_anomaly', 'WARNING', apy_change_rel, 20.0, f"APY changed by {apy_change_rel:.1f}% relative and {apy_change_abs:.1f}% absolute"))

        # 3. Tier Migration
        if prev_reports and protocol_slug in prev_reports and protocol_slug in current_reports:
            prev_tier = prev_reports[protocol_slug].risk_tier
            curr_tier = current_reports[protocol_slug].risk_tier
            
            # Decoupled AMBER from emergency exits. Only trigger exit on migration to RED.
            if prev_tier == RiskTier.GREEN and curr_tier == RiskTier.RED:
                events.append(TriggerEvent(date_val.to_pydatetime(), protocol_slug, 'tier_migration', 'CRITICAL', 0.0, 0.0, "Tier migrated from GREEN to RED"))
            elif prev_tier == RiskTier.AMBER and curr_tier == RiskTier.RED:
                events.append(TriggerEvent(date_val.to_pydatetime(), protocol_slug, 'tier_migration', 'CRITICAL', 0.0, 0.0, "Tier migrated from AMBER to RED"))

        return events
