"""
DSCE Module 4: Curation Memo Generator

Generates institutional-grade curation memos for individual strategies
and full portfolio reports — the kind of documents a DeFi asset
management team produces before deploying capital.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from modules.risk_scoring import RiskReport, RiskTier, Strategy

if TYPE_CHECKING:
    from modules.portfolio_monitor import PortfolioMonitor


# ─────────────────────────────────────────────────────────────────────
# Curation Memo Generator
# ─────────────────────────────────────────────────────────────────────

class CurationMemoGenerator:
    """
    Generates curation memos and portfolio reports.

    Produces human-readable documents that follow the exact template
    structure used in institutional DeFi asset management workflows.

    Usage::

        gen = CurationMemoGenerator()
        memo = gen.generate_memo(strategy, risk_report, "APPROVE")
        report = gen.generate_portfolio_report(portfolio_monitor)
    """

    TIER_DECISIONS = {
        RiskTier.GREEN: "APPROVE",
        RiskTier.AMBER: "CONDITIONAL APPROVE",
        RiskTier.RED: "REJECT",
    }

    # ── Strategy-level memo ──────────────────────────────────────────

    def generate_memo(
        self,
        strategy: dict | Strategy,
        risk_report: RiskReport,
        decision: Optional[str] = None,
    ) -> str:
        """
        Generate a full curation memo for a single strategy.

        Args:
            strategy: Strategy data (dict or pydantic model).
            risk_report: Completed RiskReport from the scorer.
            decision: Override decision string. If None, derived from risk tier.

        Returns:
            Formatted multi-line memo string.
        """
        if isinstance(strategy, dict):
            s = Strategy(**strategy)
        else:
            s = strategy

        if decision is None:
            decision = self.TIER_DECISIONS.get(risk_report.risk_tier, "REVIEW REQUIRED")

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ds = risk_report.dimension_scores

        lines = [
            "─" * 70,
            f"CURATION MEMO — {s.strategy_name.upper()}",
            f"Date: {today}",
            "Analyst: DeFi Curation Engine v1.0",
            f"Decision: {decision}",
            "─" * 70,
            "",
            "1. EXECUTIVE SUMMARY",
            f"   {self._executive_summary(s, risk_report, decision)}",
            "",
            "2. STRATEGY DESCRIPTION",
            f"   Protocol:      {s.protocol_name}",
            f"   Chain:          {s.chain}",
            f"   Asset Type:     {s.asset_type.value}",
            f"   Current APY:    {s.apy_pct:.1f}%",
            f"   TVL:            ${s.tvl_usd / 1e6:,.1f}M",
            f"   Age:            {s.age_days} days",
            f"   Counterparty:   {s.counterparty_type.value}",
            f"   Oracle:         {s.oracle_provider or 'None'}",
            "",
            "3. RISK ASSESSMENT",
            f"   Composite Risk Score: {risk_report.composite_score}/10 "
            f"({risk_report.risk_tier.value})",
            "",
            f"   Smart Contract Risk: {ds.smart_contract}/10",
            f"   {self._explain_smart_contract(s)}",
            "",
            f"   Liquidity Risk: {ds.liquidity}/10",
            f"   {self._explain_liquidity(s)}",
            "",
            f"   Oracle/Market Risk: {ds.oracle_market}/10",
            f"   {self._explain_oracle(s)}",
            "",
            f"   Counterparty Risk: {ds.counterparty}/10",
            f"   {self._explain_counterparty(s)}",
            "",
            f"   Concentration Risk: {ds.concentration}/10",
            "   - Evaluated at portfolio level via HHI calculation",
            "",
            "4. KEY RISKS",
        ]

        if risk_report.flags:
            for flag in risk_report.flags:
                lines.append(f"   • {flag}")
        else:
            lines.append("   • No material risk flags identified")

        lines.extend([
            "",
            "5. PROPOSED ALLOCATION",
            f"   Recommended allocation: ${s.allocation_usd / 1e6:,.1f}M",
            f"   Rationale: {self._allocation_rationale(s, risk_report)}",
        ])

        # Section 6: Conditions (only for CONDITIONAL APPROVE)
        lines.extend([
            "",
            "6. CONDITIONS" + (" (if CONDITIONAL APPROVE)" if decision == "CONDITIONAL APPROVE" else ""),
        ])
        if decision == "CONDITIONAL APPROVE":
            conditions = self._generate_conditions(s, risk_report)
            for c in conditions:
                lines.append(f"   • {c}")
        elif decision == "REJECT":
            lines.append("   • Strategy does not meet risk threshold for capital deployment")
            lines.append("   • Re-evaluate after risk mitigants are implemented")
        else:
            lines.append("   • No additional conditions required")

        lines.extend([
            "",
            "7. MONITORING TRIGGERS",
            "   • Alert if TVL drops >15% in 7 days",
            "   • Alert if APY changes >20% in 7 days",
            "   • Alert if risk score moves to RED tier",
            f"   • Next scheduled review: {self._next_review_date(risk_report)}",
            "",
            "─" * 70,
        ])

        return "\n".join(lines)

    # ── Portfolio-level report ───────────────────────────────────────

    def generate_portfolio_report(self, monitor: "PortfolioMonitor") -> str:
        """
        Generate a comprehensive portfolio-level report.

        Args:
            monitor: Initialized PortfolioMonitor instance.

        Returns:
            Formatted multi-line portfolio report string.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        summary = monitor.get_portfolio_summary()
        dashboard = monitor.get_risk_dashboard()
        breaches = monitor.check_concentration_limits()
        benchmark = monitor.get_benchmark_comparison()
        anomalies = monitor.flag_anomalies()

        lines = [
            "═" * 70,
            "PORTFOLIO CURATION REPORT",
            f"Date: {today}",
            "Analyst: DeFi Curation Engine v1.0",
            "═" * 70,
            "",
            "1. PORTFOLIO SUMMARY",
            f"   Total AUM:            ${summary.total_aum_usd / 1e6:,.0f}M",
            f"   Strategy Count:       {summary.strategy_count}",
            f"   Weighted Avg APY:     {summary.weighted_avg_apy_pct:.2f}%",
            f"   Weighted Avg Risk:    {summary.weighted_avg_risk_score:.2f}/10",
            f"   HHI (Concentration):  {summary.hhi:.4f}",
            "",
            "2. STRATEGY ALLOCATION TABLE",
            "",
            "   {:<28} {:>10} {:>8} {:>7} {:>6} {:>6}  {:>6}".format(
                "Strategy", "Alloc $M", "Alloc %", "APY %", "Risk", "Tier", "RAY"
            ),
            "   " + "─" * 78,
        ]

        for entry in dashboard:
            lines.append(
                "   {:<28} {:>10} {:>7.1f}% {:>6.1f}% {:>5.2f}  {:>6} {:>6.3f}".format(
                    entry.strategy_name[:28],
                    f"${entry.allocation_usd / 1e6:,.0f}M",
                    entry.allocation_pct,
                    entry.apy_pct,
                    entry.risk_score,
                    entry.risk_tier.value,
                    entry.risk_adjusted_yield,
                )
            )

        lines.extend([
            "",
            "3. CONCENTRATION ANALYSIS",
            f"   HHI Index: {summary.hhi:.4f} "
            f"({'HIGH — concentrated' if summary.hhi > 0.25 else 'MODERATE' if summary.hhi > 0.15 else 'LOW — well diversified'})",
        ])

        if breaches:
            lines.append("")
            lines.append("   Breaches Detected:")
            for b in breaches:
                lines.append(f"   ⚠ {b}")
        else:
            lines.append("   ✓ No concentration breaches detected")

        lines.extend([
            "",
            "4. PERFORMANCE VS BENCHMARK",
            f"   Portfolio APY:     {benchmark.portfolio_apy_pct:.2f}%",
            f"   Benchmark APY:     {benchmark.benchmark_apy_pct:.2f}% (ETH staking rate)",
            f"   Excess Yield:      {benchmark.excess_yield_pct:+.2f}%",
            f"   Sharpe Equivalent: {benchmark.sharpe_equivalent:.4f}",
        ])

        # Top risks
        lines.extend([
            "",
            "5. TOP RISKS TO MONITOR",
        ])
        top_risks = self._identify_top_risks(dashboard, breaches, anomalies)
        for i, risk in enumerate(top_risks[:3], 1):
            lines.append(f"   {i}. {risk}")

        # Rebalancing recommendations
        lines.extend([
            "",
            "6. RECOMMENDED REBALANCING ACTIONS",
        ])
        rebalancing = self._generate_rebalancing(dashboard, breaches, summary)
        if rebalancing:
            for action in rebalancing:
                lines.append(f"   • {action}")
        else:
            lines.append("   • No rebalancing required at this time")

        # Anomalies
        if anomalies:
            lines.extend([
                "",
                "7. ACTIVE ANOMALY ALERTS",
            ])
            for alert in anomalies:
                lines.append(
                    f"   [{alert.severity}] {alert.strategy_name}: {alert.description}"
                )

        lines.extend([
            "",
            "═" * 70,
        ])

        return "\n".join(lines)

    # ── private helpers ──────────────────────────────────────────────

    @staticmethod
    def _executive_summary(
        s: Strategy, report: RiskReport, decision: str,
    ) -> str:
        """Generate a 2-3 sentence executive summary."""
        summary_parts = [
            f"{s.strategy_name} is a {s.asset_type.value} strategy on {s.chain} "
            f"via {s.protocol_name}, currently yielding {s.apy_pct:.1f}% APY "
            f"with ${s.tvl_usd / 1e6:,.0f}M TVL.",
        ]

        if decision == "APPROVE":
            summary_parts.append(
                f"The strategy scores {report.composite_score}/10 "
                f"({report.risk_tier.value}) and is recommended for approval "
                f"with standard monitoring."
            )
        elif decision == "CONDITIONAL APPROVE":
            summary_parts.append(
                f"The strategy scores {report.composite_score}/10 "
                f"({report.risk_tier.value}) and is recommended for conditional "
                f"approval subject to enhanced monitoring and risk mitigants."
            )
        else:
            summary_parts.append(
                f"The strategy scores {report.composite_score}/10 "
                f"({report.risk_tier.value}) and is not recommended for "
                f"capital deployment at this time."
            )

        return " ".join(summary_parts)

    @staticmethod
    def _explain_smart_contract(s: Strategy) -> str:
        """Generate bullet explanation for smart contract risk."""
        parts = []
        parts.append(f"- {s.audit_count} audit(s) completed")
        parts.append(f", protocol age {s.age_days} days")
        if s.tvl_usd > 100_000_000:
            parts.append(f", well battle-tested (${s.tvl_usd / 1e6:,.0f}M TVL)")
        elif s.tvl_usd < 10_000_000:
            parts.append(f", limited battle-testing (${s.tvl_usd / 1e6:,.1f}M TVL)")
        return "".join(parts)

    @staticmethod
    def _explain_liquidity(s: Strategy) -> str:
        """Generate bullet explanation for liquidity risk."""
        depth_str = (
            f"${s.liquidity_depth_usd / 1e6:,.0f}M"
            if s.liquidity_depth_usd >= 1_000_000
            else f"${s.liquidity_depth_usd:,.0f}"
        )
        parts = [f"- Liquidity depth: {depth_str}"]
        if s.tvl_7d_change_pct < -10:
            parts.append(f", TVL outflow {s.tvl_7d_change_pct:.1f}% (7d)")
        if s.asset_type.value == "LP_token":
            parts.append(", impermanent loss risk applies")
        return "".join(parts)

    @staticmethod
    def _explain_oracle(s: Strategy) -> str:
        """Generate bullet explanation for oracle/market risk."""
        if not s.has_oracle:
            return "- No oracle dependency — minimal manipulation risk"
        return (
            f"- Uses {s.oracle_provider or 'unknown'} oracle"
            + (f", APY {s.apy_pct:.1f}% within normal range" if s.apy_pct <= 20 else
               f", elevated APY {s.apy_pct:.1f}% warrants scrutiny")
        )

    @staticmethod
    def _explain_counterparty(s: Strategy) -> str:
        """Generate bullet explanation for counterparty risk."""
        return (
            f"- {s.counterparty_type.value.title()} governance model"
            + (f", mcap/TVL ratio {s.mcap_tvl_ratio:.2f}"
               + (" (potentially undercollateralised)" if s.mcap_tvl_ratio < 0.3 else ""))
        )

    @staticmethod
    def _allocation_rationale(s: Strategy, report: RiskReport) -> str:
        """Generate one-sentence allocation rationale."""
        if report.risk_tier == RiskTier.GREEN:
            return (
                f"Allocation of ${s.allocation_usd / 1e6:,.1f}M is appropriate "
                f"given the strong risk profile ({report.composite_score}/10) "
                f"and adequate liquidity depth."
            )
        elif report.risk_tier == RiskTier.AMBER:
            return (
                f"Allocation of ${s.allocation_usd / 1e6:,.1f}M is acceptable "
                f"with enhanced monitoring, given moderate risk "
                f"({report.composite_score}/10)."
            )
        else:
            return (
                f"Current allocation of ${s.allocation_usd / 1e6:,.1f}M should be "
                f"reduced or unwound given elevated risk "
                f"({report.composite_score}/10)."
            )

    @staticmethod
    def _generate_conditions(s: Strategy, report: RiskReport) -> List[str]:
        """Generate conditions for CONDITIONAL APPROVE."""
        conditions = []
        ds = report.dimension_scores

        if ds.smart_contract >= 5:
            conditions.append(
                "Obtain additional independent audit before increasing allocation"
            )
        if ds.liquidity >= 6:
            conditions.append(
                "Maintain allocation below 10% of portfolio until liquidity improves"
            )
        if ds.oracle_market >= 5:
            conditions.append(
                "Implement secondary price feed monitoring as cross-check"
            )
        if ds.counterparty >= 6:
            conditions.append(
                "Monitor governance proposals weekly for centralisation risk changes"
            )
        if not conditions:
            conditions.append(
                "Maintain enhanced monitoring cadence (daily review) for 30 days"
            )
        return conditions

    @staticmethod
    def _next_review_date(report: RiskReport) -> str:
        """Determine next review date based on risk tier."""
        from datetime import timedelta
        if report.risk_tier == RiskTier.GREEN:
            delta = timedelta(days=30)
        elif report.risk_tier == RiskTier.AMBER:
            delta = timedelta(days=14)
        else:
            delta = timedelta(days=7)
        return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%d")

    @staticmethod
    def _identify_top_risks(
        dashboard: list,
        breaches: List[str],
        anomalies: list,
    ) -> List[str]:
        """Identify the top 3 portfolio risks to highlight."""
        risks: List[str] = []

        # Concentration breaches
        for b in breaches:
            risks.append(f"Concentration: {b}")

        # Highest-risk strategies
        sorted_strats = sorted(
            dashboard, key=lambda x: x.risk_score, reverse=True
        )
        for entry in sorted_strats[:2]:
            if entry.risk_score >= 4:
                risks.append(
                    f"{entry.strategy_name} has elevated risk score "
                    f"({entry.risk_score}/10, {entry.risk_tier.value})"
                )

        # Active anomalies
        for alert in anomalies:
            risks.append(f"Anomaly: {alert.description}")

        # Fallback
        if not risks:
            risks.append("No material risks identified — portfolio within normal parameters")

        return risks[:3]

    @staticmethod
    def _generate_rebalancing(
        dashboard: list,
        breaches: List[str],
        summary,
    ) -> List[str]:
        """Generate rebalancing recommendations if concentration breaches exist."""
        actions: List[str] = []

        if not breaches:
            return actions

        # Find overweight strategies
        for entry in dashboard:
            if entry.allocation_pct > 40:
                target_pct = 30.0
                reduce_by = entry.allocation_pct - target_pct
                actions.append(
                    f"Reduce {entry.strategy_name} from {entry.allocation_pct:.1f}% "
                    f"to {target_pct:.0f}% (redeploy {reduce_by:.1f}% to "
                    f"underweight strategies)"
                )

        # Suggest diversification into underweight strategies
        underweight = [e for e in dashboard if e.allocation_pct < 10 and e.risk_score <= 5]
        if underweight:
            names = ", ".join(e.strategy_name for e in underweight[:2])
            actions.append(
                f"Consider increasing allocation to underweight strategies: {names}"
            )

        if not actions:
            actions.append(
                "Review counterparty distribution and consider "
                "adding strategies with different governance models"
            )

        return actions


# ─────────────────────────────────────────────────────────────────────
# Quick self-test
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from rich.console import Console

    from modules.portfolio_monitor import PortfolioMonitor

    console = Console()

    monitor = PortfolioMonitor()
    gen = CurationMemoGenerator()

    # Generate memo for first strategy
    strat = monitor.strategies[0]
    report = monitor.risk_reports[strat.strategy_name]
    memo = gen.generate_memo(strat, report)
    console.print(memo)

    console.rule("[bold cyan]Portfolio Report[/bold cyan]")
    portfolio_report = gen.generate_portfolio_report(monitor)
    console.print(portfolio_report)
