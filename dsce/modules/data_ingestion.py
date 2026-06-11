"""
Data Ingestion Module
=====================

Fetches live DeFi protocol data from the DefiLlama and CoinGecko APIs with
retry logic, file-based caching, and mock-data fallback.  All fetched data
is persisted as JSON in ``dsce/data/raw/``.

Public surface
--------------
* ``fetch_protocols``          – full protocol list from DefiLlama
* ``fetch_pools``              – yield-pool list from DefiLlama
* ``fetch_protocol_tvl``       – historical TVL for one protocol
* ``fetch_protocol_detail``    – detailed info for one protocol
* ``fetch_steth_price_history``– stETH/ETH price ratio from CoinGecko
* ``get_protocol_snapshot``    – curated metric snapshot for a protocol
* ``generate_mock_data``       – realistic offline dataset
* ``generate_mock_protocol_snapshot`` – offline snapshot for known slugs
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data" / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_SECONDS: int = 3600  # 1 hour

DEFILLAMA_BASE: str = "https://api.llama.fi"
COINGECKO_BASE: str = "https://api.coingecko.com/api/v3"

# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------


def _fetch_with_retry(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    retries: int = 3,
    backoff_base: int = 2,
) -> dict:
    """Make an HTTP GET request with exponential-backoff retry logic.

    Parameters
    ----------
    url : str
        The endpoint URL to fetch.
    params : dict, optional
        Query-string parameters forwarded to ``requests.get``.
    retries : int
        Maximum number of attempts before giving up.
    backoff_base : int
        Base for the exponential backoff (seconds).

    Returns
    -------
    dict
        Parsed JSON response body.

    Raises
    ------
    requests.RequestException
        Re-raised after all retries are exhausted.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            logger.info(
                "Attempt %d/%d – GET %s (params=%s)",
                attempt,
                retries,
                url,
                params,
            )
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            wait = backoff_base ** attempt
            logger.warning(
                "Attempt %d/%d for %s failed: %s – retrying in %ds …",
                attempt,
                retries,
                url,
                exc,
                wait,
            )
            if attempt < retries:
                time.sleep(wait)

    logger.error("All %d retries exhausted for %s", retries, url)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_path(key: str) -> Path:
    """Return the JSON file path for a cache key.

    Parameters
    ----------
    key : str
        Logical cache key (e.g. ``'protocols'``, ``'tvl_lido'``).

    Returns
    -------
    Path
        ``data/raw/{key}.json``
    """
    safe_key = key.replace("/", "_").replace("?", "_").replace("=", "_")
    return DATA_DIR / f"{safe_key}.json"


def _read_cache(key: str) -> Optional[dict]:
    """Read cached data if the file exists and is younger than *CACHE_TTL_SECONDS*.

    Parameters
    ----------
    key : str
        Logical cache key.

    Returns
    -------
    dict or None
        Parsed JSON data, or ``None`` if the cache is stale / missing.
    """
    path = _cache_path(key)
    if not path.exists():
        return None
    age_seconds = time.time() - path.stat().st_mtime
    if age_seconds >= CACHE_TTL_SECONDS:
        logger.info("Cache expired for '%s' (%.0fs old)", key, age_seconds)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.info("Cache hit for '%s'", key)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Corrupt cache file %s: %s", path, exc)
        return None


def _write_cache(key: str, data: dict) -> None:
    """Write *data* to the cache as a JSON file.

    Parameters
    ----------
    key : str
        Logical cache key.
    data : dict
        Serialisable data to persist.
    """
    path = _cache_path(key)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("Cached data → %s", path.name)


# ---------------------------------------------------------------------------
# DefiLlama client
# ---------------------------------------------------------------------------


def fetch_protocols() -> list[dict]:
    """Fetch the full protocol list from DefiLlama ``/protocols``.

    Returns
    -------
    list[dict]
        One dict per protocol.  Falls back to mock data on failure.
    """
    cache_key = "protocols"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached

    try:
        data = _fetch_with_retry(f"{DEFILLAMA_BASE}/protocols")
        _write_cache(cache_key, data)
        return data
    except requests.RequestException:
        logger.warning("DefiLlama /protocols unreachable – using mock data")
        mock = generate_mock_data()["protocols"]
        _write_cache(cache_key, mock)
        return mock


def fetch_pools() -> list[dict]:
    """Fetch yield pools from DefiLlama ``/pools``.

    The API returns ``{"data": [...]}``.  This function extracts and returns
    the inner ``data`` list.

    Returns
    -------
    list[dict]
        Pool records.  Falls back to mock data on failure.
    """
    cache_key = "pools"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached

    try:
        raw = _fetch_with_retry(f"{DEFILLAMA_BASE}/pools")
        pools: list[dict] = raw.get("data", raw) if isinstance(raw, dict) else raw
        _write_cache(cache_key, pools)
        return pools
    except requests.RequestException:
        logger.warning("DefiLlama /pools unreachable – using mock data")
        mock = generate_mock_data()["pools"]
        _write_cache(cache_key, mock)
        return mock


def fetch_protocol_tvl(protocol_slug: str) -> list[dict]:
    """Fetch historical TVL for a specific protocol.

    Parameters
    ----------
    protocol_slug : str
        DefiLlama slug, e.g. ``"lido"``.

    Returns
    -------
    list[dict]
        Daily TVL entries.
    """
    cache_key = f"tvl_{protocol_slug}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached

    try:
        data = _fetch_with_retry(f"{DEFILLAMA_BASE}/tvl/{protocol_slug}")
        if isinstance(data, list):
            _write_cache(cache_key, data)
            return data
        # API may return a single number – wrap it
        wrapped: list[dict] = [{"date": int(time.time()), "totalLiquidityUSD": data}]
        _write_cache(cache_key, wrapped)
        return wrapped
    except requests.RequestException:
        logger.warning("DefiLlama /tvl/%s unreachable – returning empty list", protocol_slug)
        return []


def fetch_protocol_detail(protocol_slug: str) -> dict:
    """Fetch detailed protocol info from DefiLlama ``/protocol/{slug}``.

    Parameters
    ----------
    protocol_slug : str
        DefiLlama slug, e.g. ``"lido"``.

    Returns
    -------
    dict
        Full protocol detail including chain TVLs, audits, etc.
    """
    cache_key = f"protocol_detail_{protocol_slug}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached

    try:
        data = _fetch_with_retry(f"{DEFILLAMA_BASE}/protocol/{protocol_slug}")
        _write_cache(cache_key, data)
        return data
    except requests.RequestException:
        logger.warning(
            "DefiLlama /protocol/%s unreachable – returning empty dict",
            protocol_slug,
        )
        return {}


# ---------------------------------------------------------------------------
# CoinGecko client
# ---------------------------------------------------------------------------


def fetch_steth_price_history(days: int = 90) -> list[dict]:
    """Fetch stETH/ETH price-ratio history from CoinGecko.

    Parameters
    ----------
    days : int
        Number of historical days to fetch (default 90).

    Returns
    -------
    list[dict]
        ``[{"timestamp": <ms>, "price_ratio": <float>}, ...]``
    """
    cache_key = "steth_eth_history"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached

    try:
        raw = _fetch_with_retry(
            f"{COINGECKO_BASE}/coins/staked-ether/market_chart",
            params={"vs_currency": "eth", "days": days},
        )
        prices_raw: list[list[float]] = raw.get("prices", [])
        prices = [
            {"timestamp": int(entry[0]), "price_ratio": entry[1]}
            for entry in prices_raw
        ]
        _write_cache(cache_key, prices)
        return prices
    except requests.RequestException:
        logger.warning("CoinGecko stETH data unreachable – using mock data")
        mock = generate_mock_data()["steth_history"]
        _write_cache(cache_key, mock)
        return mock


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

_MOCK_LISTED_AT: Dict[str, int] = {
    "lido": 1608163200,        # 2020-12-17
    "aave": 1578528000,        # 2020-01-09
    "curve-dex": 1578268800,   # 2020-01-06
    "morpho": 1667260800,      # 2022-11-01
    "pendle": 1624406400,      # 2021-06-23
    "spark": 1683849600,       # 2023-05-12
    "eigenlayer": 1686700800,  # 2023-06-14
}


def generate_mock_data() -> dict:
    """Return a complete mock dataset for offline / test use.

    The returned dict has three keys:

    * ``protocols`` – list of protocol dicts (lido, aave, curve-dex, morpho,
      pendle, spark, eigenlayer).
    * ``pools`` – 10 realistic LST/ETH yield pools.
    * ``steth_history`` – 90 daily stETH/ETH price-ratio data-points.

    Returns
    -------
    dict
        ``{"protocols": [...], "pools": [...], "steth_history": [...]}``
    """
    # ----- Protocols --------------------------------------------------------
    protocols: list[dict] = [
        {
            "name": "Lido",
            "slug": "lido",
            "tvl": 30_500_000_000,
            "chain": "Ethereum",
            "category": "Liquid Staking",
            "audits": [
                {"auditor": "MixBytes", "date": "2021-04-15"},
                {"auditor": "Quantstamp", "date": "2021-06-01"},
                {"auditor": "Sigma Prime", "date": "2022-03-10"},
                {"auditor": "Statemind", "date": "2022-09-20"},
                {"auditor": "ChainSecurity", "date": "2023-05-05"},
            ],
            "listedAt": _MOCK_LISTED_AT["lido"],
            "mcap": 2_400_000_000,
            "change_7d": 2.3,
        },
        {
            "name": "Aave",
            "slug": "aave",
            "tvl": 12_800_000_000,
            "chain": "Multi-Chain",
            "category": "Lending",
            "audits": [
                {"auditor": "Trail of Bits", "date": "2020-01-10"},
                {"auditor": "OpenZeppelin", "date": "2020-09-05"},
                {"auditor": "SigmaPrime", "date": "2021-03-22"},
                {"auditor": "Certora", "date": "2021-12-01"},
                {"auditor": "PeckShield", "date": "2022-06-15"},
                {"auditor": "Spearbit", "date": "2023-02-28"},
            ],
            "listedAt": _MOCK_LISTED_AT["aave"],
            "mcap": 1_500_000_000,
            "change_7d": -1.2,
        },
        {
            "name": "Curve DEX",
            "slug": "curve-dex",
            "tvl": 2_100_000_000,
            "chain": "Multi-Chain",
            "category": "DEX",
            "audits": [
                {"auditor": "Trail of Bits", "date": "2020-04-01"},
                {"auditor": "Quantstamp", "date": "2020-08-20"},
                {"auditor": "MixBytes", "date": "2021-05-15"},
                {"auditor": "ChainSecurity", "date": "2023-08-01"},
            ],
            "listedAt": _MOCK_LISTED_AT["curve-dex"],
            "mcap": 600_000_000,
            "change_7d": 0.5,
        },
        {
            "name": "Morpho",
            "slug": "morpho",
            "tvl": 2_500_000_000,
            "chain": "Ethereum",
            "category": "Lending",
            "audits": [
                {"auditor": "Spearbit", "date": "2022-10-12"},
                {"auditor": "Trail of Bits", "date": "2023-01-20"},
                {"auditor": "Cantina", "date": "2023-07-08"},
            ],
            "listedAt": _MOCK_LISTED_AT["morpho"],
            "mcap": 350_000_000,
            "change_7d": 5.1,
        },
        {
            "name": "Pendle",
            "slug": "pendle",
            "tvl": 1_200_000_000,
            "chain": "Ethereum",
            "category": "Yield",
            "audits": [
                {"auditor": "Ackee Blockchain", "date": "2022-02-10"},
                {"auditor": "Dingbats", "date": "2022-08-01"},
                {"auditor": "Dedaub", "date": "2023-03-18"},
                {"auditor": "Watchpug", "date": "2023-09-25"},
            ],
            "listedAt": _MOCK_LISTED_AT["pendle"],
            "mcap": 400_000_000,
            "change_7d": 8.2,
        },
        {
            "name": "Spark",
            "slug": "spark",
            "tvl": 1_800_000_000,
            "chain": "Ethereum",
            "category": "Lending",
            "audits": [
                {"auditor": "ChainSecurity", "date": "2023-04-10"},
                {"auditor": "Cantina", "date": "2023-07-20"},
                {"auditor": "ABDK", "date": "2024-01-15"},
            ],
            "listedAt": _MOCK_LISTED_AT["spark"],
            "mcap": 0,
            "change_7d": -0.8,
        },
        {
            "name": "EigenLayer",
            "slug": "eigenlayer",
            "tvl": 15_000_000_000,
            "chain": "Ethereum",
            "category": "Restaking",
            "audits": [
                {"auditor": "Sigma Prime", "date": "2023-05-01"},
                {"auditor": "Consensys Diligence", "date": "2023-08-10"},
                {"auditor": "Trail of Bits", "date": "2023-11-20"},
                {"auditor": "Dedaub", "date": "2024-02-05"},
            ],
            "listedAt": _MOCK_LISTED_AT["eigenlayer"],
            "mcap": 0,
            "change_7d": -2.5,
        },
    ]

    # ----- Pools (10 realistic LST / ETH pools) ----------------------------
    pools: list[dict] = [
        {"pool": "stETH-ETH", "project": "curve-dex", "chain": "Ethereum",
         "tvl": 800_000_000, "apy": 3.45, "apyBase": 0.85, "apyReward": 2.60,
         "symbol": "stETH-ETH", "rewardTokens": ["LDO", "CRV"]},
        {"pool": "wstETH-ETH", "project": "balancer-v2", "chain": "Ethereum",
         "tvl": 450_000_000, "apy": 3.12, "apyBase": 1.10, "apyReward": 2.02,
         "symbol": "wstETH-ETH", "rewardTokens": ["BAL", "LDO"]},
        {"pool": "rETH-ETH", "project": "balancer-v2", "chain": "Ethereum",
         "tvl": 320_000_000, "apy": 2.95, "apyBase": 1.25, "apyReward": 1.70,
         "symbol": "rETH-ETH", "rewardTokens": ["BAL"]},
        {"pool": "cbETH-ETH", "project": "uniswap-v3", "chain": "Ethereum",
         "tvl": 180_000_000, "apy": 2.50, "apyBase": 2.50, "apyReward": 0.0,
         "symbol": "cbETH-ETH", "rewardTokens": []},
        {"pool": "wstETH-WETH", "project": "aave-v3", "chain": "Ethereum",
         "tvl": 2_500_000_000, "apy": 1.85, "apyBase": 1.85, "apyReward": 0.0,
         "symbol": "wstETH", "rewardTokens": []},
        {"pool": "stETH-frxETH", "project": "curve-dex", "chain": "Ethereum",
         "tvl": 120_000_000, "apy": 4.10, "apyBase": 0.60, "apyReward": 3.50,
         "symbol": "stETH-frxETH", "rewardTokens": ["CRV", "CVX"]},
        {"pool": "wstETH-USDC", "project": "morpho", "chain": "Ethereum",
         "tvl": 350_000_000, "apy": 5.20, "apyBase": 5.20, "apyReward": 0.0,
         "symbol": "wstETH", "rewardTokens": []},
        {"pool": "PT-stETH-26DEC", "project": "pendle", "chain": "Ethereum",
         "tvl": 210_000_000, "apy": 4.80, "apyBase": 4.80, "apyReward": 0.0,
         "symbol": "PT-stETH", "rewardTokens": []},
        {"pool": "weETH-wstETH", "project": "balancer-v2", "chain": "Ethereum",
         "tvl": 95_000_000, "apy": 3.75, "apyBase": 1.50, "apyReward": 2.25,
         "symbol": "weETH-wstETH", "rewardTokens": ["BAL"]},
        {"pool": "wstETH-sDAI", "project": "spark", "chain": "Ethereum",
         "tvl": 600_000_000, "apy": 2.30, "apyBase": 2.30, "apyReward": 0.0,
         "symbol": "wstETH", "rewardTokens": []},
    ]

    # ----- stETH / ETH ratio history (90 data-points) ----------------------
    steth_history: list[dict] = []
    now_utc = datetime.now(timezone.utc)
    rng = random.Random(42)  # deterministic seed
    for day_offset in range(90, 0, -1):
        ts_ms = int((now_utc - timedelta(days=day_offset)).timestamp() * 1000)
        ratio = round(rng.uniform(0.9995, 1.0005), 6)
        steth_history.append({"timestamp": ts_ms, "price_ratio": ratio})

    return {
        "protocols": protocols,
        "pools": pools,
        "steth_history": steth_history,
    }


# ---------------------------------------------------------------------------
# Protocol snapshot
# ---------------------------------------------------------------------------


def get_protocol_snapshot(protocol_slug: str) -> dict:
    """Fetch protocol detail and compute a curated metrics snapshot.

    Tries live DefiLlama data first; falls back to
    ``generate_mock_protocol_snapshot`` on any failure.

    Parameters
    ----------
    protocol_slug : str
        DefiLlama slug, e.g. ``"lido"``.

    Returns
    -------
    dict
        ``{name, tvl, tvl_7d_change_pct, chain, category,
          audit_count, age_days, mcap_tvl_ratio}``
    """
    try:
        detail = fetch_protocol_detail(protocol_slug)
        if not detail:
            raise ValueError(f"Empty response for slug '{protocol_slug}'")
        return _build_snapshot(detail)
    except Exception as exc:
        logger.warning(
            "Live snapshot for '%s' failed (%s) – falling back to mock",
            protocol_slug,
            exc,
        )
        return generate_mock_protocol_snapshot(protocol_slug)


def _build_snapshot(detail: dict) -> dict:
    """Build a snapshot dict from a raw DefiLlama protocol-detail response.

    Parameters
    ----------
    detail : dict
        Full protocol detail as returned by ``/protocol/{slug}``.

    Returns
    -------
    dict
        Curated metrics snapshot.
    """
    tvl = float(detail.get("tvl", 0) or 0)
    mcap = float(detail.get("mcap", 0) or 0)

    # ---- tvl_7d_change_pct -------------------------------------------------
    tvl_7d_change: float = 0.0
    change_7d_val = detail.get("change_7d")
    if change_7d_val is not None:
        try:
            tvl_7d_change = float(change_7d_val)
        except (TypeError, ValueError):
            tvl_7d_change = 0.0

    # If change_7d not available, attempt to derive from chainTvls history
    if tvl_7d_change == 0.0:
        chain_tvls = detail.get("chainTvls", {})
        for _chain_name, chain_data in chain_tvls.items():
            tvl_history = chain_data if isinstance(chain_data, list) else chain_data.get("tvl", [])
            if len(tvl_history) >= 7:
                recent = tvl_history[-1].get("totalLiquidityUSD", 0)
                week_ago = tvl_history[-7].get("totalLiquidityUSD", 0)
                if week_ago > 0:
                    tvl_7d_change = round((recent - week_ago) / week_ago * 100, 2)
            break  # use first chain found

    # ---- audit_count -------------------------------------------------------
    audits_field = detail.get("audits", [])
    if isinstance(audits_field, list):
        audit_count = len(audits_field)
    elif isinstance(audits_field, (int, float)):
        audit_count = int(audits_field)
    elif isinstance(audits_field, str):
        try:
            audit_count = int(audits_field)
        except ValueError:
            audit_count = 0
    else:
        audit_count = 0

    # ---- age_days ----------------------------------------------------------
    listed_at = detail.get("listedAt")
    if listed_at is not None:
        try:
            listed_dt = datetime.fromtimestamp(int(listed_at), tz=timezone.utc)
            age_days = (datetime.now(timezone.utc) - listed_dt).days
        except (TypeError, ValueError, OSError):
            age_days = 0
    else:
        age_days = 0

    # ---- mcap_tvl_ratio ----------------------------------------------------
    mcap_tvl_ratio = round(mcap / tvl, 4) if tvl > 0 else 0.0

    return {
        "name": detail.get("name", "Unknown"),
        "tvl": tvl,
        "tvl_7d_change_pct": tvl_7d_change,
        "chain": detail.get("chain", "Unknown"),
        "category": detail.get("category", "Unknown"),
        "audit_count": audit_count,
        "age_days": age_days,
        "mcap_tvl_ratio": mcap_tvl_ratio,
    }


def generate_mock_protocol_snapshot(protocol_slug: str) -> dict:
    """Return a realistic snapshot for well-known mock protocol slugs.

    Parameters
    ----------
    protocol_slug : str
        One of the known mock slugs (``lido``, ``aave``, …).

    Returns
    -------
    dict
        Same shape as ``get_protocol_snapshot`` output.
    """
    mock = generate_mock_data()
    match: Optional[dict] = None
    for p in mock["protocols"]:
        if p["slug"].lower() == protocol_slug.lower():
            match = p
            break

    if match is None:
        logger.warning("No mock data for slug '%s'", protocol_slug)
        return {
            "name": protocol_slug,
            "tvl": 0.0,
            "tvl_7d_change_pct": 0.0,
            "chain": "Unknown",
            "category": "Unknown",
            "audit_count": 0,
            "age_days": 0,
            "mcap_tvl_ratio": 0.0,
        }

    return _build_snapshot(match)


# ---------------------------------------------------------------------------
# __main__  – quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
    except ImportError:
        console = None  # type: ignore[assignment]

    # ---- Protocol snapshot --------------------------------------------------
    print("=" * 60)
    print("  Protocol Snapshot: Lido")
    print("=" * 60)

    snapshot = get_protocol_snapshot("lido")

    if console is not None:
        table = Table(title="Lido Snapshot", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        for key, value in snapshot.items():
            table.add_row(key, str(value))
        console.print(table)
    else:
        print(json.dumps(snapshot, indent=2))

    # ---- stETH price ratio stats -------------------------------------------
    print("\n" + "=" * 60)
    print("  stETH / ETH Price Ratio Stats")
    print("=" * 60)

    steth_data = fetch_steth_price_history(days=90)
    if steth_data:
        ratios = [entry["price_ratio"] for entry in steth_data]
        avg_ratio = sum(ratios) / len(ratios)
        min_ratio = min(ratios)
        max_ratio = max(ratios)

        if console is not None:
            stats_table = Table(
                title="stETH/ETH Ratio (90 days)",
                show_header=True,
                header_style="bold green",
            )
            stats_table.add_column("Statistic", style="bold")
            stats_table.add_column("Value", justify="right")
            stats_table.add_row("Data points", str(len(ratios)))
            stats_table.add_row("Average", f"{avg_ratio:.6f}")
            stats_table.add_row("Min", f"{min_ratio:.6f}")
            stats_table.add_row("Max", f"{max_ratio:.6f}")
            console.print(stats_table)
        else:
            print(f"  Data points : {len(ratios)}")
            print(f"  Average     : {avg_ratio:.6f}")
            print(f"  Min         : {min_ratio:.6f}")
            print(f"  Max         : {max_ratio:.6f}")
    else:
        print("  (no stETH data available)")

    print(f"\nTotal protocols loaded: {len(fetch_protocols())}")