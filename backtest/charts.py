"""
Backtest Charts Module
======================

Generates two presentation-ready charts:
1. Equity curve comparison (all three strategies)
2. Annotated trigger chart (Strategy 1 with trigger fire markers)

Charts are saved as PNG files in backtest/output/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for file output
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Colour palette — professional, accessible
COLOURS = {
    "DSCE System": "#2563EB",          # Blue
    "Naive Yield-Chaser": "#DC2626",   # Red
    "ETH Staking": "#059669",          # Green
}

TRIGGER_COLOURS = {
    "tvl_drop": "#DC2626",        # Red
    "apy_anomaly": "#F59E0B",     # Amber/orange
    "tier_migration": "#7C3AED",  # Purple
}

TRIGGER_LABELS = {
    "tvl_drop": "TVL Drop >15%/7d",
    "apy_anomaly": "APY Change >20%",
    "tier_migration": "Tier Migration ^",
}


# ─────────────────────────────────────────────────────────────────────
# Chart 1: Equity Curve Comparison
# ─────────────────────────────────────────────────────────────────────

def plot_equity_curves(
    equity_curves: Dict[str, pd.Series],
    initial_capital: float = 100_000_000,
    save_path: Optional[Path] = None,
) -> Path:
    """
    Plot equity curves for all three strategies, normalised to $100 base.

    Args:
        equity_curves: {strategy_name: daily NAV Series with DatetimeIndex}.
        initial_capital: Starting capital (used for normalisation label).
        save_path: Optional custom file path. Defaults to output/equity_curves.png.

    Returns:
        Path to the saved PNG file.
    """
    if save_path is None:
        save_path = OUTPUT_DIR / "equity_curves.png"

    fig, ax = plt.subplots(figsize=(14, 7))

    for name, curve in equity_curves.items():
        if len(curve) == 0:
            continue
        # Normalise to $100 starting value for comparability
        normalised = curve / curve.iloc[0] * 100
        colour = COLOURS.get(name, "#6B7280")
        ax.plot(
            normalised.index,
            normalised.values,
            label=f"{name}  (final: ${curve.iloc[-1]/1e6:.1f}M, "
                  f"return: {(curve.iloc[-1]/curve.iloc[0]-1)*100:+.2f}%)",
            color=colour,
            linewidth=1.8,
            alpha=0.9,
        )

    # Formatting
    ax.set_title(
        "Backtest: Equity Curve Comparison",
        fontsize=16, fontweight="bold", pad=15,
    )
    ax.set_xlabel("Date", fontsize=12)
    ax.set_ylabel("Portfolio Value (normalised to $100)", fontsize=12)
    ax.legend(loc="upper left", fontsize=10, framealpha=0.9)
    ax.grid(True, alpha=0.3, linestyle="--")

    # Date formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=45, ha="right")

    # Y-axis formatting
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("$%.0f"))

    # Baseline reference line at $100
    ax.axhline(y=100, color="#9CA3AF", linestyle=":", alpha=0.5, linewidth=1)

    plt.tight_layout()
    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"  [OK] Equity curve chart saved -> {save_path}")
    return save_path


# ─────────────────────────────────────────────────────────────────────
# Chart 2: Annotated Trigger Chart
# ─────────────────────────────────────────────────────────────────────

def plot_trigger_annotations(
    equity_curve: pd.Series,
    trigger_log: List[dict],
    trigger_analysis: Optional[List] = None,
    save_path: Optional[Path] = None,
) -> Path:
    """
    Plot the DSCE System equity curve with trigger fire annotations.

    Each trigger fire is marked with a vertical line and annotated with
    the protocol name. Markers are colour-coded by trigger type and
    differentiated by outcome (filled = true positive, hollow = false alarm).

    Args:
        equity_curve: DSCE System daily NAV Series.
        trigger_log: List of trigger event dicts from the engine.
        trigger_analysis: Optional list of TriggerAnalysisEntry objects
                         for true positive / false alarm classification.
        save_path: Optional custom file path. Defaults to output/trigger_annotations.png.

    Returns:
        Path to the saved PNG file.
    """
    if save_path is None:
        save_path = OUTPUT_DIR / "trigger_annotations.png"

    fig, ax = plt.subplots(figsize=(16, 8))

    # Plot equity curve
    normalised = equity_curve / equity_curve.iloc[0] * 100
    ax.plot(
        normalised.index,
        normalised.values,
        color=COLOURS["DSCE System"],
        linewidth=1.8,
        alpha=0.9,
        label="DSCE System",
    )

    # Build outcome lookup from trigger_analysis if available
    outcome_lookup: Dict[str, str] = {}
    if trigger_analysis:
        for entry in trigger_analysis:
            key = f"{entry.date}_{entry.protocol}_{entry.trigger_type}"
            outcome_lookup[key] = entry.outcome

    # Plot trigger markers
    plotted_types = set()
    for trigger in trigger_log:
        trigger_date = pd.Timestamp(trigger.get("date"))
        protocol = trigger.get("protocol", "")
        trigger_type = trigger.get("trigger_type", "")
        colour = TRIGGER_COLOURS.get(trigger_type, "#6B7280")

        # Determine outcome
        key = f"{trigger_date.strftime('%Y-%m-%d')}_{protocol}_{trigger_type}"
        outcome = outcome_lookup.get(key, "unknown")

        # Vertical line at trigger date
        ax.axvline(
            x=trigger_date,
            color=colour,
            alpha=0.3,
            linewidth=1,
            linestyle="--",
        )

        # Get NAV at trigger date for marker placement
        if trigger_date in normalised.index:
            nav_at_trigger = normalised.loc[trigger_date]
        else:
            # Find nearest date
            nearest_idx = normalised.index.get_indexer([trigger_date], method="nearest")[0]
            nav_at_trigger = normalised.iloc[nearest_idx]

        # Marker style: filled for true positive, hollow for false alarm
        if outcome == "true_positive":
            marker_style = "o"
            facecolor = colour
            edgecolor = colour
        else:
            marker_style = "o"
            facecolor = "white"
            edgecolor = colour

        label = TRIGGER_LABELS.get(trigger_type, trigger_type)
        if trigger_type not in plotted_types:
            ax.scatter(
                [trigger_date], [nav_at_trigger],
                color=facecolor,
                edgecolors=edgecolor,
                marker=marker_style,
                s=60,
                linewidths=1.5,
                zorder=5,
                label=f"{label} ({'●' if outcome == 'true_positive' else '○'})",
            )
            plotted_types.add(trigger_type)
        else:
            ax.scatter(
                [trigger_date], [nav_at_trigger],
                color=facecolor,
                edgecolors=edgecolor,
                marker=marker_style,
                s=60,
                linewidths=1.5,
                zorder=5,
            )

        # Annotate with protocol name (staggered to avoid overlap)
        ax.annotate(
            protocol,
            xy=(trigger_date, nav_at_trigger),
            xytext=(5, 12),
            textcoords="offset points",
            fontsize=7,
            color=colour,
            alpha=0.8,
            fontweight="bold",
            rotation=30,
        )

    # Legend entries for outcome markers
    ax.scatter([], [], color="#333", marker="o", s=40, label="● = True Positive (loss avoided)")
    ax.scatter([], [], facecolors="white", edgecolors="#333", marker="o",
               s=40, linewidths=1.5, label="○ = False Alarm (missed yield)")

    # Formatting
    ax.set_title(
        "DSCE System: Trigger Fire Annotations",
        fontsize=16, fontweight="bold", pad=15,
    )
    ax.set_xlabel("Date", fontsize=12)
    ax.set_ylabel("Portfolio Value (normalised to $100)", fontsize=12)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9, ncol=2)
    ax.grid(True, alpha=0.3, linestyle="--")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=45, ha="right")

    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("$%.0f"))
    ax.axhline(y=100, color="#9CA3AF", linestyle=":", alpha=0.5, linewidth=1)

    plt.tight_layout()
    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"  [OK] Trigger annotation chart saved -> {save_path}")
    return save_path
