"""
DSCE Module 3: Portfolio Monitor

Tracks a portfolio of DeFi strategies, computes aggregate analytics,
monitors concentration limits, detects anomalies, and benchmarks
performance against ETH staking rate.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from modules.risk_scoring import (
    AssetType,
    CounterpartyType,
    RiskReport,
    RiskScorer,
    RiskTier,
    Strategy,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PORTFOLIO_CONFIG = DATA_DIR / "portfolio_config.json"
ETH_STAKING_BENCHMARK_APY = 3.5  # fallback; overridden by config


# ─────────────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────────────

class PortfolioSummary(BaseModel):
    """Aggregate portfolio-level metrics."""

    total_aum_usd: float = Field(..., description="Total assets under management")
    weighted_avg_apy_pct: float = Field(..., description="AUM-weighted average APY")
    weighted_avg_risk_score: float = Field(..., description="AUM-weighted average risk score")
    hhi: float = Field(..., ge=0, le=1, description="Herfindahl-Hirschman Index")
    strategy_count: int = Field(..., ge=0)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class StrategyDashboardEntry(BaseModel):
    """Per-strategy row in the risk dashboard."""

    strategy_name: str
    protocol_name: str
    chain: str
    allocation_usd: float
    allocation_pct: float
    apy_pct: float
    risk_score: float
    risk_tier: RiskTier
    risk_adjusted_yield: float = Field(
        ..., description="APY / composite_risk_score (higher = better)"
    )
    asset_type: str
    counterparty_type: str


class BenchmarkComparison(BaseModel):
    """Portfolio performance vs ETH staking benchmark."""

    portfolio_apy_pct: float
    benchmark_apy_pct: float
    excess_yield_pct: float = Field(
        ..., description="portfolio_apy - benchmark_apy"
    )
    sharpe_equivalent: float = Field(
        ...,
        description="Excess yield / weighted risk score "
                    "(simplified risk-adjusted return metric)",
    )


class AnomalyAlert(BaseModel):
    """An anomaly detected during portfolio monitoring."""

    strategy_name: str
    alert_type: str  # 'apy_change', 'tvl_drop', 'tier_migration'
    description: str
    severity: str  # 'WARNING', 'CRITICAL'
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─────────────────────────────────────────────────────────────────────
# Portfolio Monitor
# ─────────────────────────────────────────────────────────────────────

class PortfolioMonitor:
    """
    Monitors a portfolio of DeFi yield strategies.

    Loads strategy definitions from ``portfolio_config.json``, scores each
    strategy via :class:`RiskScorer`, and exposes aggregate analytics,
    concentration checks, anomaly detection, and benchmark comparison.

    Usage::

        monitor = PortfolioMonitor()
        summary = monitor.get_portfolio_summary()
        dashboard = monitor.get_risk_dashboard()
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        scorer: Optional[RiskScorer] = None,
    ) -> None:
        """
        Initialize the portfolio monitor.

        Args:
            config_path: Path to portfolio_config.json.
                         Defaults to ``dsce/data/portfolio_config.json``.
            scorer:      Optional pre-configured RiskScorer instance.
        """
        self.config_path = config_path or PORTFOLIO_CONFIG
        self.scorer = scorer or RiskScorer()
        self._config: Dict[str, Any] = {}
        self._strategies: List[Strategy] = []
        self._risk_reports: Dict[str, RiskReport] = {}
        self._portfolio_map: Dict[str, float] = {}
        self._benchmark_apy: float = ETH_STAKING_BENCHMARK_APY

        self._load_config()
        self._score_all()

    # ── initialisation helpers ───────────────────────────────────────

    def _load_config(self) -> None:
        """Load and parse portfolio_config.json."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        except FileNotFoundError:
            logger.warning(
                "Portfolio config not found at %s — using empty portfolio",
                self.config_path,
            )
            self._config = {"strategies": [], "benchmark_apy_pct": ETH_STAKING_BENCHMARK_APY}

        self._benchmark_apy = self._config.get(
            "benchmark_apy_pct", ETH_STAKING_BENCHMARK_APY
        )

        self._strategies = []
        for s in self._config.get("strategies", []):
            try:
                self._strategies.append(Strategy(**s))
            except Exception as exc:
                logger.error("Failed to parse strategy %s: %s", s.get("strategy_name"), exc)

        self._portfolio_map = {
            s.strategy_name: s.allocation_usd for s in self._strategies
        }

    def _score_all(self) -> None:
        """Score every strategy in the portfolio."""
        self._risk_reports = {}
        for strat in self._strategies:
            try:
                report = self.scorer.score_strategy(strat, self._portfolio_map)
                self._risk_reports[strat.strategy_name] = report
            except Exception as exc:
                logger.error("Scoring failed for %s: %s", strat.strategy_name, exc)

    def refresh(self) -> None:
        """Reload config and re-score all strategies."""
        self._load_config()
        self._score_all()

    # ── public API ───────────────────────────────────────────────────

    @property
    def strategies(self) -> List[Strategy]:
        """Return loaded strategy models."""
        return self._strategies

    @property
    def risk_reports(self) -> Dict[str, RiskReport]:
        """Return cached risk reports keyed by strategy name."""
        return self._risk_reports

    def get_portfolio_summary(self) -> PortfolioSummary:
        """
        Compute aggregate portfolio metrics.

        Returns:
            PortfolioSummary with total AUM, weighted APY, weighted risk, HHI.
        """
        total_aum = sum(s.allocation_usd for s in self._strategies)
        if total_aum == 0:
            return PortfolioSummary(
                total_aum_usd=0,
                weighted_avg_apy_pct=0,
                weighted_avg_risk_score=0,
                hhi=0,
                strategy_count=0,
            )

        w_apy = sum(
            s.apy_pct * s.allocation_usd for s in self._strategies
        ) / total_aum

        w_risk = sum(
            self._risk_reports[s.strategy_name].composite_score * s.allocation_usd
            for s in self._strategies
            if s.strategy_name in self._risk_reports
        ) / total_aum

        # HHI
        shares = [s.allocation_usd / total_aum for s in self._strategies]
        hhi = round(sum(sh ** 2 for sh in shares), 4)

        return PortfolioSummary(
            total_aum_usd=total_aum,
            weighted_avg_apy_pct=round(w_apy, 2),
            weighted_avg_risk_score=round(w_risk, 2),
            hhi=hhi,
            strategy_count=len(self._strategies),
        )

    def check_concentration_limits(self) -> List[str]:
        """
        Check for concentration limit breaches.

        Returns:
            List of human-readable breach descriptions.
        """
        breaches: List[str] = []

        # Strategy-level concentration
        conc = self.scorer.score_concentration(self._portfolio_map)
        breaches.extend(conc.breaches)

        # Counterparty-level concentration
        cpty_breaches = self.scorer.check_counterparty_concentration(
            [s.model_dump() for s in self._strategies],
            self._portfolio_map,
        )
        breaches.extend(cpty_breaches)

        return breaches

    def get_risk_dashboard(self) -> List[StrategyDashboardEntry]:
        """
        Build per-strategy dashboard data.

        Returns:
            List of StrategyDashboardEntry models, one per strategy.
        """
        total_aum = sum(s.allocation_usd for s in self._strategies)
        entries: List[StrategyDashboardEntry] = []

        for strat in self._strategies:
            report = self._risk_reports.get(strat.strategy_name)
            if not report:
                continue

            alloc_pct = (strat.allocation_usd / total_aum * 100) if total_aum else 0
            ray = self.compute_risk_adjusted_yield(strat)

            entries.append(
                StrategyDashboardEntry(
                    strategy_name=strat.strategy_name,
                    protocol_name=strat.protocol_name,
                    chain=strat.chain,
                    allocation_usd=strat.allocation_usd,
                    allocation_pct=round(alloc_pct, 2),
                    apy_pct=strat.apy_pct,
                    risk_score=report.composite_score,
                    risk_tier=report.risk_tier,
                    risk_adjusted_yield=ray,
                    asset_type=strat.asset_type.value,
                    counterparty_type=strat.counterparty_type.value,
                )
            )

        return entries

    def compute_risk_adjusted_yield(self, strategy: Strategy) -> float:
        """
        Compute risk-adjusted yield: APY / composite_risk_score.

        A higher value indicates better risk-adjusted return.

        Args:
            strategy: The strategy to evaluate.

        Returns:
            Risk-adjusted yield ratio (higher = better).
        """
        report = self._risk_reports.get(strategy.strategy_name)
        if not report or report.composite_score == 0:
            return 0.0
        return round(strategy.apy_pct / report.composite_score, 4)

    def get_benchmark_comparison(self) -> BenchmarkComparison:
        """
        Compare portfolio's weighted APY against ETH staking benchmark.

        Returns:
            BenchmarkComparison with excess yield and Sharpe equivalent.
        """
        summary = self.get_portfolio_summary()
        excess = round(summary.weighted_avg_apy_pct - self._benchmark_apy, 2)

        # Simplified Sharpe: excess return / risk
        sharpe = (
            round(excess / summary.weighted_avg_risk_score, 4)
            if summary.weighted_avg_risk_score > 0
            else 0.0
        )

        return BenchmarkComparison(
            portfolio_apy_pct=summary.weighted_avg_apy_pct,
            benchmark_apy_pct=self._benchmark_apy,
            excess_yield_pct=excess,
            sharpe_equivalent=sharpe,
        )

    def flag_anomalies(
        self,
        prev_data: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> List[AnomalyAlert]:
        """
        Detect anomalies in portfolio strategies.

        Checks for:
        - APY changed >20% in 7 days
        - TVL dropped >15% in 7 days
        - Risk score moved up a tier

        Args:
            prev_data: Optional dict of {strategy_name: {prev_apy, prev_tvl, prev_risk_tier}}
                       for comparison. If None, uses tvl_7d_change_pct from strategy data
                       and skips APY comparison.

        Returns:
            List of AnomalyAlert objects.
        """
        alerts: List[AnomalyAlert] = []

        for strat in self._strategies:
            report = self._risk_reports.get(strat.strategy_name)
            if not report:
                continue

            # TVL drop check (always available from strategy data)
            if strat.tvl_7d_change_pct < -15:
                alerts.append(
                    AnomalyAlert(
                        strategy_name=strat.strategy_name,
                        alert_type="tvl_drop",
                        description=(
                            f"TVL dropped {strat.tvl_7d_change_pct:.1f}% in 7 days "
                            f"(threshold: -15%)"
                        ),
                        severity="CRITICAL" if strat.tvl_7d_change_pct < -30 else "WARNING",
                    )
                )

            # Comparisons against previous data
            if prev_data and strat.strategy_name in prev_data:
                prev = prev_data[strat.strategy_name]

                # APY change check
                prev_apy = prev.get("prev_apy", strat.apy_pct)
                if prev_apy > 0:
                    apy_change_pct = abs(strat.apy_pct - prev_apy) / prev_apy * 100
                    if apy_change_pct > 20:
                        alerts.append(
                            AnomalyAlert(
                                strategy_name=strat.strategy_name,
                                alert_type="apy_change",
                                description=(
                                    f"APY changed by {apy_change_pct:.1f}% "
                                    f"(from {prev_apy:.1f}% to {strat.apy_pct:.1f}%, "
                                    f"threshold: 20%)"
                                ),
                                severity="WARNING",
                            )
                        )

                # Tier migration check
                prev_tier = prev.get("prev_risk_tier")
                if prev_tier:
                    tier_order = {RiskTier.GREEN: 0, RiskTier.AMBER: 1, RiskTier.RED: 2}
                    if isinstance(prev_tier, str):
                        try:
                            prev_tier = RiskTier(prev_tier)
                        except ValueError:
                            prev_tier = None

                    if prev_tier and tier_order.get(report.risk_tier, 0) > tier_order.get(prev_tier, 0):
                        alerts.append(
                            AnomalyAlert(
                                strategy_name=strat.strategy_name,
                                alert_type="tier_migration",
                                description=(
                                    f"Risk tier migrated from {prev_tier.value} "
                                    f"to {report.risk_tier.value}"
                                ),
                                severity="CRITICAL",
                            )
                        )

        return alerts

    # ── convenience ──────────────────────────────────────────────────

    def get_strategy_by_name(self, name: str) -> Optional[Strategy]:
        """Look up a strategy by its name."""
        for s in self._strategies:
            if s.strategy_name == name:
                return s
        return None

    def get_report_by_name(self, name: str) -> Optional[RiskReport]:
        """Look up a risk report by strategy name."""
        return self._risk_reports.get(name)

    def get_total_aum(self) -> float:
        """Return total portfolio AUM in USD."""
        return sum(s.allocation_usd for s in self._strategies)


# ─────────────────────────────────────────────────────────────────────
# Quick self-test
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table

    console = Console()

    monitor = PortfolioMonitor()

    # Portfolio summary
    summary = monitor.get_portfolio_summary()
    console.rule("[bold cyan]Portfolio Summary[/bold cyan]")
    console.print(f"Total AUM:       ${summary.total_aum_usd / 1e6:.0f}M")
    console.print(f"Weighted APY:    {summary.weighted_avg_apy_pct:.2f}%")
    console.print(f"Weighted Risk:   {summary.weighted_avg_risk_score:.2f}/10")
    console.print(f"HHI:             {summary.hhi:.4f}")
    console.print(f"Strategy Count:  {summary.strategy_count}")

    # Dashboard table
    console.rule("[bold cyan]Risk Dashboard[/bold cyan]")
    table = Table()
    table.add_column("Strategy", style="cyan")
    table.add_column("Alloc $M", justify="right")
    table.add_column("Alloc %", justify="right")
    table.add_column("APY %", justify="right")
    table.add_column("Risk", justify="right")
    table.add_column("Tier", justify="center")
    table.add_column("RAY", justify="right")

    tier_colors = {"GREEN": "green", "AMBER": "yellow", "RED": "red"}

    for entry in monitor.get_risk_dashboard():
        color = tier_colors.get(entry.risk_tier.value, "white")
        table.add_row(
            entry.strategy_name,
            f"${entry.allocation_usd / 1e6:.0f}M",
            f"{entry.allocation_pct:.1f}%",
            f"{entry.apy_pct:.1f}%",
            f"{entry.risk_score:.2f}",
            f"[{color}]{entry.risk_tier.value}[/{color}]",
            f"{entry.risk_adjusted_yield:.3f}",
        )
    console.print(table)

    # Concentration checks
    console.rule("[bold cyan]Concentration Checks[/bold cyan]")
    breaches = monitor.check_concentration_limits()
    if breaches:
        for b in breaches:
            console.print(f"  [red]⚠ {b}[/red]")
    else:
        console.print("  [green]✓ No concentration breaches[/green]")

    # Benchmark
    console.rule("[bold cyan]Benchmark Comparison[/bold cyan]")
    bench = monitor.get_benchmark_comparison()
    console.print(f"Portfolio APY:    {bench.portfolio_apy_pct:.2f}%")
    console.print(f"Benchmark APY:   {bench.benchmark_apy_pct:.2f}%")
    console.print(f"Excess Yield:    {bench.excess_yield_pct:+.2f}%")
    console.print(f"Sharpe Equiv:    {bench.sharpe_equivalent:.4f}")