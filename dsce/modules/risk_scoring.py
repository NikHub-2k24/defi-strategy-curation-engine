"""
DSCE Module 1: Risk Scoring Engine

Rules-based risk scoring for DeFi strategies across 5 dimensions.
Every score is deterministic and explainable — no black-box ML.

Dimensions & Weights:
    1. Smart Contract Risk   (25%)
    2. Liquidity Risk         (25%)
    3. Oracle / Market Risk   (20%)
    4. Counterparty Risk      (20%)
    5. Concentration Risk     (10%)

Risk Tiers:
    1-3  → GREEN  (approve)
    4-6  → AMBER  (conditional)
    7-10 → RED    (reject)
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────

class AssetType(str, Enum):
    """Supported DeFi asset types."""
    LST = "LST"
    STABLECOIN = "stablecoin"
    VOLATILE = "volatile"
    LP_TOKEN = "LP_token"


class CounterpartyType(str, Enum):
    """Governance / custody model of the protocol."""
    DECENTRALIZED = "decentralized"
    SEMI_CENTRALIZED = "semi-centralized"
    CENTRALIZED = "centralized"


class RiskTier(str, Enum):
    """Human-readable risk tier derived from composite score."""
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


# ─────────────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────────────

class Strategy(BaseModel):
    """Input schema for a single DeFi yield strategy."""

    strategy_name: str = Field(..., description="Human-readable strategy label")
    protocol_name: str = Field(..., description="Protocol slug (e.g. 'lido', 'aave')")
    tvl_usd: float = Field(..., ge=0, description="Total Value Locked in USD")
    tvl_7d_change_pct: float = Field(0.0, description="7-day TVL change as percentage")
    audit_count: int = Field(0, ge=0, description="Number of independent audits")
    age_days: int = Field(0, ge=0, description="Days since protocol launch")
    apy_pct: float = Field(0.0, description="Current annual percentage yield")
    mcap_tvl_ratio: float = Field(0.0, ge=0, description="Market cap / TVL ratio")
    chain: str = Field("Ethereum", description="Primary deployment chain")
    has_oracle: bool = Field(False, description="Whether strategy uses a price oracle")
    oracle_provider: Optional[str] = Field(None, description="Oracle provider name")
    counterparty_type: CounterpartyType = Field(
        CounterpartyType.DECENTRALIZED,
        description="Governance / custody model",
    )
    liquidity_depth_usd: float = Field(
        0.0, ge=0,
        description="Amount withdrawable without >1% slippage",
    )
    asset_type: AssetType = Field(AssetType.VOLATILE, description="Underlying asset class")
    allocation_usd: float = Field(0.0, ge=0, description="Portfolio allocation in USD")

    @field_validator("counterparty_type", mode="before")
    @classmethod
    def normalise_counterparty(cls, v: str) -> str:
        """Accept common variants like 'semi_centralized'."""
        if isinstance(v, str):
            return v.replace("_", "-")
        return v


class DimensionScores(BaseModel):
    """Breakdown of individual risk dimension scores (1-10 each)."""

    smart_contract: float = Field(..., ge=1, le=10)
    liquidity: float = Field(..., ge=1, le=10)
    oracle_market: float = Field(..., ge=1, le=10)
    counterparty: float = Field(..., ge=1, le=10)
    concentration: float = Field(..., ge=1, le=10)


class RiskReport(BaseModel):
    """Full risk assessment output for a single strategy."""

    strategy_name: str
    composite_score: float = Field(..., ge=1, le=10)
    risk_tier: RiskTier
    dimension_scores: DimensionScores
    flags: List[str] = Field(default_factory=list)
    recommendation: str = ""


class PortfolioConcentration(BaseModel):
    """Output of portfolio-level concentration analysis."""

    hhi: float = Field(..., ge=0, le=1, description="Herfindahl-Hirschman Index")
    concentration_score: float = Field(..., ge=1, le=10)
    breaches: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# Risk Scorer
# ─────────────────────────────────────────────────────────────────────

class RiskScorer:
    """
    Deterministic, rules-based risk scorer for DeFi strategies.

    Usage::

        scorer = RiskScorer()
        report = scorer.score_strategy(strategy_dict, portfolio)
    """

    # Dimension weights (must sum to 1.0)
    WEIGHTS = {
        "smart_contract": 0.25,
        "liquidity": 0.25,
        "oracle_market": 0.20,
        "counterparty": 0.20,
        "concentration": 0.10,
    }

    # ── public API ───────────────────────────────────────────────────

    def score_strategy(
        self,
        strategy: dict | Strategy,
        portfolio: Optional[Dict[str, float]] = None,
    ) -> RiskReport:
        """
        Score a single strategy across all 5 risk dimensions.

        Args:
            strategy: Strategy data as dict or Strategy model.
            portfolio: Optional mapping of {strategy_name: allocation_usd}
                       used for concentration scoring. If None, concentration
                       defaults to mid-range (5).

        Returns:
            A fully populated RiskReport.
        """
        if isinstance(strategy, dict):
            strat = Strategy(**strategy)
        else:
            strat = strategy

        flags: List[str] = []

        # Score each dimension
        sc_score = self._score_smart_contract(strat, flags)
        liq_score = self._score_liquidity(strat, flags)
        oracle_score = self._score_oracle_market(strat, flags)
        cpty_score = self._score_counterparty(strat, flags)

        if portfolio:
            conc = self.score_concentration(portfolio)
            conc_score = conc.concentration_score
            flags.extend(conc.breaches)
        else:
            conc_score = 5.0  # neutral default

        # Composite
        composite = (
            sc_score * self.WEIGHTS["smart_contract"]
            + liq_score * self.WEIGHTS["liquidity"]
            + oracle_score * self.WEIGHTS["oracle_market"]
            + cpty_score * self.WEIGHTS["counterparty"]
            + conc_score * self.WEIGHTS["concentration"]
        )
        composite = round(min(10.0, max(1.0, composite)), 2)

        tier = self._tier(composite)

        recommendation = self._generate_recommendation(strat.strategy_name, composite, tier, flags)

        return RiskReport(
            strategy_name=strat.strategy_name,
            composite_score=composite,
            risk_tier=tier,
            dimension_scores=DimensionScores(
                smart_contract=sc_score,
                liquidity=liq_score,
                oracle_market=oracle_score,
                counterparty=cpty_score,
                concentration=conc_score,
            ),
            flags=flags,
            recommendation=recommendation,
        )

    def score_concentration(
        self, portfolio: Dict[str, float],
    ) -> PortfolioConcentration:
        """
        Evaluate portfolio-level concentration risk.

        Args:
            portfolio: {strategy_name: allocation_usd}

        Returns:
            PortfolioConcentration with HHI, score, and breach flags.
        """
        total = sum(portfolio.values())
        if total == 0:
            return PortfolioConcentration(hhi=0.0, concentration_score=1.0, breaches=[])

        shares = {k: v / total for k, v in portfolio.items()}
        hhi = round(sum(s ** 2 for s in shares.values()), 4)

        # Score from HHI
        if hhi > 0.25:
            score = 8.0
        elif hhi > 0.15:
            score = 5.0
        else:
            score = 2.0

        breaches: List[str] = []

        # Single strategy > 40%
        for name, share in shares.items():
            if share > 0.40:
                breaches.append(
                    f"BREACH: {name} represents {share*100:.1f}% of portfolio "
                    f"(limit: 40%)"
                )

        # HHI flag
        if hhi > 0.25:
            breaches.append(
                f"BREACH: Portfolio HHI = {hhi:.4f} exceeds 0.25 threshold — "
                f"high concentration risk"
            )

        return PortfolioConcentration(hhi=hhi, concentration_score=score, breaches=breaches)

    def check_counterparty_concentration(
        self,
        strategies: List[dict | Strategy],
        portfolio: Dict[str, float],
    ) -> List[str]:
        """
        Check if any single counterparty_type exceeds 30% of portfolio.

        Args:
            strategies: List of strategy dicts/models (must include
                        strategy_name and counterparty_type).
            portfolio: {strategy_name: allocation_usd}

        Returns:
            List of breach description strings (empty if clean).
        """
        total = sum(portfolio.values())
        if total == 0:
            return []

        cpty_alloc: Dict[str, float] = {}
        for s in strategies:
            strat = Strategy(**s) if isinstance(s, dict) else s
            name = strat.strategy_name
            cpty = strat.counterparty_type.value
            alloc = portfolio.get(name, 0.0)
            cpty_alloc[cpty] = cpty_alloc.get(cpty, 0.0) + alloc

        breaches: List[str] = []
        for cpty, alloc in cpty_alloc.items():
            pct = alloc / total
            if pct > 0.30:
                breaches.append(
                    f"BREACH: Counterparty type '{cpty}' represents "
                    f"{pct*100:.1f}% of portfolio (limit: 30%)"
                )
        return breaches

    # ── private scoring methods ──────────────────────────────────────

    @staticmethod
    def _clamp(score: float) -> float:
        """Clamp score to [1, 10] range."""
        return min(10.0, max(1.0, score))

    def _score_smart_contract(self, s: Strategy, flags: List[str]) -> float:
        """
        Smart Contract Risk (weight 25%).

        Factors: audit_count, age_days, tvl_usd (battle-testing proxy).
        """
        score = 0.0

        # Audit factor
        if s.audit_count == 0:
            score += 4
            flags.append("No audits found — smart contract risk elevated")
        elif s.audit_count == 1:
            score += 2
            flags.append("Only 1 audit — consider additional review")
        # 2+ audits → +0

        # Age factor
        if s.age_days < 90:
            score += 3
            flags.append(f"Protocol age {s.age_days}d < 90d — very young protocol")
        elif s.age_days <= 365:
            score += 2
        # > 365 → +0

        # Battle-testing (TVL proxy)
        if s.tvl_usd < 10_000_000:
            score += 2
            flags.append(
                f"TVL ${s.tvl_usd/1e6:.1f}M < $10M — limited battle-testing"
            )
        elif s.tvl_usd > 100_000_000:
            score -= 1

        return self._clamp(score)

    def _score_liquidity(self, s: Strategy, flags: List[str]) -> float:
        """
        Liquidity Risk (weight 25%).

        Factors: liquidity_depth_usd, tvl_7d_change_pct, asset_type.
        """
        depth = s.liquidity_depth_usd

        # Base score from liquidity depth
        if depth < 1_000_000:
            score = 9.0
            flags.append(
                f"Liquidity depth ${depth/1e6:.1f}M < $1M — severe illiquidity"
            )
        elif depth < 10_000_000:
            score = 7.0
            flags.append(
                f"Liquidity depth ${depth/1e6:.1f}M < $10M — moderate illiquidity"
            )
        elif depth < 50_000_000:
            score = 4.0
        else:
            score = 2.0

        # TVL outflow signal
        if s.tvl_7d_change_pct < -20:
            score += 2
            flags.append(
                f"TVL dropped {s.tvl_7d_change_pct:.1f}% in 7 days — "
                f"significant outflow"
            )
        elif s.tvl_7d_change_pct < -10:
            score += 1
            flags.append(
                f"TVL dropped {s.tvl_7d_change_pct:.1f}% in 7 days — "
                f"moderate outflow"
            )

        # Impermanent loss risk
        if s.asset_type == AssetType.LP_TOKEN:
            score += 1
            flags.append("LP token — impermanent loss risk applies")

        return self._clamp(score)

    def _score_oracle_market(self, s: Strategy, flags: List[str]) -> float:
        """
        Oracle / Market Risk (weight 20%).

        Factors: has_oracle, oracle_provider, apy_pct.
        """
        if not s.has_oracle:
            score = 2.0
        else:
            provider = (s.oracle_provider or "").lower()
            if "chainlink" in provider:
                score = 2.0
            elif "twap" in provider or "uniswap" in provider:
                score = 5.0
                flags.append("Uses Uniswap TWAP oracle — manipulation risk exists")
            else:
                score = 8.0
                flags.append(
                    f"Custom oracle provider '{s.oracle_provider}' — "
                    f"high manipulation risk"
                )

        # Suspicious yield premium
        if s.apy_pct > 50:
            score += 3
            flags.append(
                f"APY {s.apy_pct:.1f}% > 50% — extremely high yield, "
                f"investigate sustainability"
            )
        elif s.apy_pct > 20:
            score += 2
            flags.append(
                f"APY {s.apy_pct:.1f}% > 20% — elevated yield, "
                f"verify source of return"
            )

        return self._clamp(score)

    def _score_counterparty(self, s: Strategy, flags: List[str]) -> float:
        """
        Counterparty Risk (weight 20%).

        Factors: counterparty_type, mcap_tvl_ratio.
        """
        cpty = s.counterparty_type
        if cpty == CounterpartyType.DECENTRALIZED:
            score = 2.0
        elif cpty == CounterpartyType.SEMI_CENTRALIZED:
            score = 5.0
        else:
            score = 8.0
            flags.append("Centralized counterparty — custodial risk elevated")

        # Under-collateralisation proxy
        if s.mcap_tvl_ratio < 0.3:
            score += 2
            flags.append(
                f"Mcap/TVL ratio {s.mcap_tvl_ratio:.2f} < 0.30 — "
                f"protocol may be undercollateralised relative to TVL"
            )

        return self._clamp(score)

    @staticmethod
    def _tier(composite: float) -> RiskTier:
        """Map composite score to risk tier."""
        if composite <= 3.0:
            return RiskTier.GREEN
        elif composite <= 6.0:
            return RiskTier.AMBER
        else:
            return RiskTier.RED

    @staticmethod
    def _generate_recommendation(
        name: str, composite: float, tier: RiskTier, flags: List[str],
    ) -> str:
        """Generate a one-sentence recommendation string."""
        flag_count = len(flags)
        if tier == RiskTier.GREEN:
            return (
                f"{name} scores {composite}/10 ({tier.value}) with "
                f"{flag_count} flag(s) — recommend APPROVE for allocation."
            )
        elif tier == RiskTier.AMBER:
            return (
                f"{name} scores {composite}/10 ({tier.value}) with "
                f"{flag_count} flag(s) — recommend CONDITIONAL APPROVE "
                f"with enhanced monitoring."
            )
        else:
            return (
                f"{name} scores {composite}/10 ({tier.value}) with "
                f"{flag_count} flag(s) — recommend REJECT or significant "
                f"risk mitigation before allocation."
            )


# ─────────────────────────────────────────────────────────────────────
# Quick self-test
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table

    console = Console()

    # Sample strategy
    sample = {
        "strategy_name": "Lido stETH Native Staking",
        "protocol_name": "lido",
        "tvl_usd": 14_000_000_000,
        "tvl_7d_change_pct": -1.2,
        "audit_count": 5,
        "age_days": 1200,
        "apy_pct": 3.8,
        "mcap_tvl_ratio": 0.15,
        "chain": "Ethereum",
        "has_oracle": True,
        "oracle_provider": "Chainlink",
        "counterparty_type": "decentralized",
        "liquidity_depth_usd": 500_000_000,
        "asset_type": "LST",
        "allocation_usd": 30_000_000,
    }

    sample_portfolio = {
        "Lido stETH Native Staking": 30_000_000,
        "Curve stETH/ETH Pool": 20_000_000,
        "Aave stETH Lending": 15_000_000,
        "Spark Protocol ETH": 10_000_000,
        "Morpho stETH Vault": 12_000_000,
        "Pendle stETH PT": 8_000_000,
        "EigenLayer Restaking": 5_000_000,
    }

    scorer = RiskScorer()
    report = scorer.score_strategy(sample, sample_portfolio)

    console.rule("[bold cyan]Risk Report[/bold cyan]")
    console.print(f"[bold]{report.strategy_name}[/bold]")
    console.print(f"Composite Score: {report.composite_score}/10")
    console.print(f"Risk Tier: {report.risk_tier.value}")

    table = Table(title="Dimension Scores")
    table.add_column("Dimension", style="cyan")
    table.add_column("Score", justify="right")
    for dim, val in report.dimension_scores.model_dump().items():
        table.add_row(dim.replace("_", " ").title(), f"{val}/10")
    console.print(table)

    console.print("\n[bold]Flags:[/bold]")
    for f in report.flags:
        console.print(f"  • {f}")
    console.print(f"\n[bold]Recommendation:[/bold] {report.recommendation}")