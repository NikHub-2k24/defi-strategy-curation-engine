"""Incident response runbook data structures and simulation logic.

This module defines structured runbook entries for DeFi incident scenarios,
provides a simulation engine that walks through each incident phase, and
exposes a summary table suitable for dashboard rendering.
"""

from __future__ import annotations

import logging
import textwrap
from datetime import datetime
from typing import Dict, List, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class RunbookEntry(BaseModel):
    """A single incident-response runbook entry.

    Attributes:
        trigger: Human-readable condition that activates this runbook.
        severity: Priority level – P1 (critical), P2 (high), P3 (moderate).
        detection_method: How the incident is typically detected.
        immediate_actions: Ordered list of steps to execute on detection.
        escalation_path: Ordered list of roles / contacts to escalate to.
        resolution_criteria: Condition(s) that must be met to close the incident.
        post_mortem_required: Whether a formal post-mortem is mandated.
    """

    trigger: str = Field(..., description="Condition that triggers this runbook")
    severity: Literal["P1", "P2", "P3"] = Field(
        ..., description="Incident priority level"
    )
    detection_method: str = Field(
        ..., description="How the incident is typically detected"
    )
    immediate_actions: List[str] = Field(
        ..., description="Ordered steps to execute immediately"
    )
    escalation_path: List[str] = Field(
        ..., description="Ordered list of escalation contacts"
    )
    resolution_criteria: str = Field(
        ..., description="Criteria that must be met to close the incident"
    )
    post_mortem_required: bool = Field(
        ..., description="Whether a post-mortem review is required"
    )


# ---------------------------------------------------------------------------
# Runbook catalogue
# ---------------------------------------------------------------------------


def get_runbook() -> Dict[str, RunbookEntry]:
    """Return the full incident-response runbook catalogue.

    Returns:
        Dict mapping incident-type keys to their corresponding
        :class:`RunbookEntry` definitions.  The catalogue ships with
        seven pre-defined entries covering the most common DeFi risk
        scenarios.
    """

    runbook: Dict[str, RunbookEntry] = {
        # ── P1 ────────────────────────────────────────────────────────
        "smart_contract_exploit": RunbookEntry(
            trigger="Smart contract exploit detected or reported",
            severity="P1",
            detection_method=(
                "On-chain monitoring alerts, social media reports, "
                "anomalous fund flows"
            ),
            immediate_actions=[
                "Pause all deposits to affected protocol",
                "Initiate emergency withdrawal of all funds",
                "Notify risk committee within 15 minutes",
                "Engage protocol team for technical details",
                "Monitor on-chain for further exploit transactions",
            ],
            escalation_path=[
                "Curation Team Lead",
                "Head of Risk",
                "CTO",
                "Legal Counsel",
            ],
            resolution_criteria=(
                "All funds secured, root cause identified, protocol team "
                "published fix and post-mortem"
            ),
            post_mortem_required=True,
        ),
        "stablecoin_depeg": RunbookEntry(
            trigger="Stablecoin depegs >5% from target price",
            severity="P1",
            detection_method="Price feed monitoring, DEX pool ratio alerts",
            immediate_actions=[
                "Verify depeg across multiple price sources",
                "Calculate portfolio exposure to affected stablecoin",
                "Reduce exposure by 50% within 1 hour",
                "Switch to alternative stablecoin pairs if available",
                "Alert all stakeholders with exposure report",
            ],
            escalation_path=[
                "Curation Team Lead",
                "Head of Risk",
                "Portfolio Manager",
            ],
            resolution_criteria=(
                "Stablecoin re-pegs within 2% of target OR full exit completed"
            ),
            post_mortem_required=True,
        ),
        "oracle_manipulation": RunbookEntry(
            trigger=(
                "Oracle price feed shows anomalous values or "
                "staleness >30 minutes"
            ),
            severity="P1",
            detection_method=(
                "Oracle heartbeat monitoring, price deviation alerts "
                "(>5% from market)"
            ),
            immediate_actions=[
                "Cross-reference price with 3+ independent sources",
                "Pause any strategies dependent on affected oracle",
                "Initiate emergency withdrawal from affected protocols",
                "Contact oracle provider for incident confirmation",
                "Document all anomalous price points with timestamps",
            ],
            escalation_path=[
                "Curation Team Lead",
                "Head of Risk",
                "CTO",
                "Oracle Provider Contact",
            ],
            resolution_criteria=(
                "Oracle feed resumes accurate pricing, provider publishes "
                "incident report"
            ),
            post_mortem_required=True,
        ),
        # ── P2 ────────────────────────────────────────────────────────
        "tvl_drop": RunbookEntry(
            trigger="TVL drops >30% in 24 hours",
            severity="P2",
            detection_method=(
                "DefiLlama TVL monitoring, protocol dashboard alerts"
            ),
            immediate_actions=[
                "Identify root cause (whale withdrawal vs systemic)",
                "Check for correlated drops across protocols",
                "Reduce allocation to 50% of current",
                "Monitor withdrawal queue depth",
                "Prepare full exit plan if decline continues",
            ],
            escalation_path=["Curation Team Lead", "Head of Risk"],
            resolution_criteria=(
                "TVL stabilizes for 48+ hours and root cause is non-systemic"
            ),
            post_mortem_required=True,
        ),
        "counterparty_insolvency": RunbookEntry(
            trigger=(
                "Counterparty shows signs of insolvency or inability "
                "to meet obligations"
            ),
            severity="P2",
            detection_method=(
                "On-chain treasury monitoring, governance forum analysis, "
                "social signals"
            ),
            immediate_actions=[
                "Freeze new allocations to affected counterparty",
                "Begin orderly withdrawal of all funds",
                "Assess contagion risk to other portfolio positions",
                "Engage legal team for recovery options",
                "Notify stakeholders of exposure and action plan",
            ],
            escalation_path=[
                "Curation Team Lead",
                "Head of Risk",
                "Legal Counsel",
                "Board",
            ],
            resolution_criteria=(
                "Full fund recovery confirmed OR loss quantified and reported"
            ),
            post_mortem_required=True,
        ),
        "liquidity_crunch": RunbookEntry(
            trigger=(
                "Withdrawal queue exceeds 48 hours or liquidity depth "
                "drops >60%"
            ),
            severity="P2",
            detection_method=(
                "Protocol withdrawal queue monitoring, liquidity depth tracking"
            ),
            immediate_actions=[
                "Assess current withdrawal capacity and queue position",
                "Submit withdrawal request immediately to secure queue position",
                "Diversify exit routes (DEX, OTC, cross-chain bridges)",
                "Reduce future allocation cap for affected strategy",
                "Alert portfolio manager of potential delayed settlement",
            ],
            escalation_path=[
                "Curation Team Lead",
                "Head of Risk",
                "Portfolio Manager",
            ],
            resolution_criteria=(
                "Withdrawal completed successfully OR alternative exit executed"
            ),
            post_mortem_required=True,
        ),
        # ── P3 ────────────────────────────────────────────────────────
        "apy_anomaly": RunbookEntry(
            trigger="APY exceeds 3x expected value for >6 hours",
            severity="P3",
            detection_method=(
                "Yield monitoring dashboard, automated APY deviation alerts"
            ),
            immediate_actions=[
                "Verify APY source (genuine yield vs token emissions)",
                "Check for temporary market conditions "
                "(maturity rollover, incentive program)",
                "Document the anomaly with supporting data",
                "Maintain current position if explained, reduce if unexplained",
            ],
            escalation_path=["Curation Team Lead"],
            resolution_criteria=(
                "APY returns to expected range OR anomaly fully explained"
            ),
            post_mortem_required=False,
        ),
    }

    logger.debug("Loaded %d runbook entries", len(runbook))
    return runbook


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

_SEVERITY_CHANNELS: Dict[str, str] = {
    "P1": "emergency war-room channel",
    "P2": "dedicated incident Slack channel",
    "P3": "team Slack channel",
}


def simulate_incident(incident_type: str) -> str:
    """Simulate an incident response walkthrough for a given incident type.

    Produces a formatted, multi-line report that steps through detection,
    triage, immediate action, communications, and resolution phases.

    Args:
        incident_type: Key matching one of the entries returned by
            :func:`get_runbook`.

    Returns:
        A human-readable, multi-line simulation walkthrough string.
        If *incident_type* is not recognised, returns a help message
        listing valid incident types.
    """

    runbook = get_runbook()

    if incident_type not in runbook:
        valid_types = ", ".join(sorted(runbook.keys()))
        return (
            f"Unknown incident type: '{incident_type}'.\n"
            f"Valid types are: {valid_types}"
        )

    entry = runbook[incident_type]
    title = incident_type.upper().replace("_", " ")
    channel = _SEVERITY_CHANNELS.get(entry.severity, "team channel")

    # Build numbered action list
    actions_block = "\n".join(
        f"       {i}. {action}"
        for i, action in enumerate(entry.immediate_actions, start=1)
    )

    # Build escalation list
    escalation_str = " → ".join(entry.escalation_path)

    simulation = textwrap.dedent(f"""\
        ══════════════════════════════════════════════════════
        INCIDENT SIMULATION: {title}
        Severity: {entry.severity}
        ══════════════════════════════════════════════════════

        ▶ PHASE 1: DETECTION (T+0)
          {entry.detection_method}
          Status: Incident detected and logged

        ▶ PHASE 2: TRIAGE (T+15m)
          Severity classified as {entry.severity}
          Escalation initiated: {escalation_str}

        ▶ PHASE 3: IMMEDIATE ACTION (T+30m)
{actions_block}

        ▶ PHASE 4: COMMUNICATIONS (T+1h)
          • Internal stakeholders notified via {channel}
          • Risk committee briefed on exposure and actions taken
          • Status page updated (if applicable)

        ▶ PHASE 5: RESOLUTION
          Resolution criteria: {entry.resolution_criteria}
          Post-mortem required: {"Yes" if entry.post_mortem_required else "No"}\
    """)

    logger.info("Simulated incident: %s", incident_type)
    return simulation


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------


def get_incident_summary_table() -> list[dict]:
    """Return a lightweight summary of every runbook entry.

    Each element contains:

    * **type** – incident-type key
    * **trigger** – human-readable trigger description
    * **severity** – P1 / P2 / P3
    * **post_mortem_required** – boolean flag

    This is intentionally simple so it can be serialised straight into a
    dashboard component or API response.

    Returns:
        A list of dicts, one per runbook entry.
    """

    runbook = get_runbook()
    table: list[dict] = [
        {
            "type": key,
            "trigger": entry.trigger,
            "severity": entry.severity,
            "post_mortem_required": entry.post_mortem_required,
        }
        for key, entry in runbook.items()
    ]

    logger.debug("Built summary table with %d rows", len(table))
    return table


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        from rich.console import Console
        from rich.table import Table as RichTable

        console = Console()

        # ── Table of all runbook entries ──────────────────────────────
        rich_table = RichTable(
            title="DeFi Incident Response Runbook",
            show_lines=True,
        )
        rich_table.add_column("Incident Type", style="cyan", no_wrap=True)
        rich_table.add_column("Severity", justify="center")
        rich_table.add_column("Trigger")
        rich_table.add_column("Post-Mortem", justify="center")

        severity_style = {"P1": "bold red", "P2": "yellow", "P3": "green"}

        for row in get_incident_summary_table():
            sev = row["severity"]
            rich_table.add_row(
                row["type"],
                f"[{severity_style.get(sev, '')}]{sev}[/]",
                row["trigger"],
                "Yes" if row["post_mortem_required"] else "No",
            )

        console.print(rich_table)
        console.print()

        # ── Simulate one incident ─────────────────────────────────────
        console.print(simulate_incident("smart_contract_exploit"))

    except ImportError:
        # Graceful fallback when rich is not installed
        print("=" * 55)
        print("DeFi Incident Response Runbook (plain-text fallback)")
        print("=" * 55)
        for row in get_incident_summary_table():
            pm = "Yes" if row["post_mortem_required"] else "No"
            print(
                f"  [{row['severity']}] {row['type']:<30s} "
                f"Post-Mortem: {pm}"
            )
            print(f"        Trigger: {row['trigger']}")
        print()
        print(simulate_incident("smart_contract_exploit"))
