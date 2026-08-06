"""
Data Fetcher Module
===================

Fetches and caches historical DeFi data from DeFiLlama and CoinGecko APIs
for a backtest covering ~18 months (Jan 2025 to Aug 2026).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
BACKTEST_DIR = Path(__file__).resolve().parent
CACHE_DIR = BACKTEST_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days

DEFILLAMA_BASE = "https://api.llama.fi"
YIELDS_BASE = "https://yields.llama.fi"
COINS_BASE = "https://coins.llama.fi"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Internal protocol names (matching portfolio_config.json)
PROTOCOL_NAMES = [
    "lido",
    "curve-dex",
    "aave",
    "spark",
    "morpho",
    "pendle",
    "eigenlayer"
]

# DeFiLlama API slugs may differ from internal names.
# Map: internal_name -> [list of DeFiLlama project slugs to try]
DEFILLAMA_SLUG_MAP = {
    "lido": ["lido"],
    "curve-dex": ["curve-dex", "curve"],
    "aave": ["aave-v3", "aave-v2", "aave"],
    "spark": ["spark", "spark-lend"],
    "morpho": ["morpho-blue", "morpho", "morpho-aave"],
    "pendle": ["pendle"],
    "eigenlayer": ["eigenlayer"],
}

# DeFiLlama TVL protocol slugs (for /protocol/{slug} endpoint)
DEFILLAMA_TVL_SLUGS = {
    "lido": "lido",
    "curve-dex": "curve-dex",
    "aave": "aave",
    "spark": "spark",
    "morpho": "morpho",
    "pendle": "pendle",
    "eigenlayer": "eigenlayer",
}

@dataclass
class BacktestDataset:
    protocol_tvl: Dict[str, pd.DataFrame]
    pool_apy: Dict[str, pd.DataFrame]
    eth_price: pd.DataFrame
    steth_ratio: pd.DataFrame
    pool_metadata: Dict[str, dict]
    data_start: datetime
    data_end: datetime

def _fetch_with_retry(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    retries: int = 3,
    backoff_base: int = 2,
    delay: float = 0.0,
) -> dict:
    """Make an HTTP GET request with exponential-backoff retry logic."""
    if delay > 0:
        time.sleep(delay)
        
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            logger.info("GET %s", url)
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            wait = backoff_base ** attempt
            logger.warning("Attempt %d/%d for %s failed: %s - retrying in %ds...", attempt, retries, url, exc, wait)
            if attempt < retries:
                time.sleep(wait)

    logger.error("All %d retries exhausted for %s", retries, url)
    raise last_exc  # type: ignore

def _cache_path(key: str) -> Path:
    safe_key = key.replace("/", "_").replace("?", "_").replace("=", "_").replace(":", "_")
    return CACHE_DIR / f"{safe_key}.json"

def _read_cache(key: str) -> Optional[dict]:
    path = _cache_path(key)
    if not path.exists():
        return None
    age_seconds = time.time() - path.stat().st_mtime
    if age_seconds >= CACHE_TTL_SECONDS:
        logger.info("Cache expired for '%s'", key)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.info("Cache hit for '%s'", key)
        return data
    except (json.JSONDecodeError, OSError):
        return None

def _write_cache(key: str, data: dict) -> None:
    path = _cache_path(key)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("Cached data -> %s", path.name)

def get_pool_ids() -> Dict[str, str]:
    """Discover and map protocol names to their representative pool UUIDs.
    
    Fetches the full pool list from DeFiLlama yields API, then for each
    protocol finds the most relevant ETH/stETH pool on Ethereum.
    Returns: {internal_protocol_name: pool_uuid}
    """
    cache_key = "pool_ids_mapping"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached

    raw = _fetch_with_retry(f"{YIELDS_BASE}/pools", delay=0.3)
    pools_data = raw.get("data", []) if isinstance(raw, dict) else []
    
    # Also cache the full pools list for metadata lookups
    _write_cache("pools_full_list", pools_data)
    
    mapping = {}
    keywords = ["steth", "wsteth", "eth"]
    
    for name in PROTOCOL_NAMES:
        aliases = DEFILLAMA_SLUG_MAP.get(name, [name])
        
        # Find pools matching any alias on Ethereum
        project_pools = [
            p for p in pools_data 
            if p.get("project", "").lower() in [a.lower() for a in aliases] 
            and p.get("chain", "").lower() == "ethereum"
        ]
        
        if not project_pools:
            logger.warning("No Ethereum pools found for %s (tried: %s)", name, aliases)
            continue
            
        # Try to find a pool matching stETH/wstETH keywords
        selected_pool = None
        for kw in keywords:
            for p in project_pools:
                symbol = p.get("symbol", "").lower()
                if kw in symbol:
                    selected_pool = p
                    break
            if selected_pool:
                break
                
        if not selected_pool:
            # Fallback to the largest pool by TVL
            selected_pool = sorted(project_pools, key=lambda x: x.get("tvlUsd", 0), reverse=True)[0]
            
        mapping[name] = selected_pool["pool"]
        logger.info("Mapped %s -> pool %s (%s)", name, selected_pool["pool"], selected_pool.get("symbol", "?"))

    _write_cache(cache_key, mapping)
    return mapping

def fetch_protocol_tvl(slug: str) -> pd.DataFrame:
    """Fetch historical daily TVL for a protocol via /protocol/{slug}.

    The /protocol/{slug} endpoint returns full protocol detail including
    a 'tvl' array of daily {date, totalLiquidityUSD} entries.
    We extract that array rather than using /tvl/{slug} which only
    returns the current TVL number.
    """
    cache_key = f"tvl_{slug}"
    cached = _read_cache(cache_key)
    if cached is None:
        try:
            data = _fetch_with_retry(f"{DEFILLAMA_BASE}/protocol/{slug}", delay=0.3)
            # Extract the tvl array from the full protocol detail response
            tvl_array = data.get("tvl", []) if isinstance(data, dict) else []
            _write_cache(cache_key, tvl_array)
            cached = tvl_array
        except Exception:
            logger.error("Failed to fetch TVL for %s", slug)
            return pd.DataFrame(columns=["date", "tvl_usd"]).set_index("date")

    if not isinstance(cached, list) or not cached:
        return pd.DataFrame(columns=["date", "tvl_usd"]).set_index("date")
        
    df = pd.DataFrame(cached)
    if df.empty:
        return pd.DataFrame(columns=["date", "tvl_usd"]).set_index("date")
        
    df["date"] = pd.to_datetime(df["date"], unit="s", utc=True).dt.floor("D")
    df = df.rename(columns={"totalLiquidityUSD": "tvl_usd"})
    df = df.groupby("date")["tvl_usd"].mean().to_frame()
    return df

def fetch_pool_apy(pool_id: str) -> pd.DataFrame:
    cache_key = f"yield_{pool_id}"
    cached = _read_cache(cache_key)
    if cached is None:
        try:
            data = _fetch_with_retry(f"{YIELDS_BASE}/chart/{pool_id}", delay=0.3)
            cached = data.get("data", []) if isinstance(data, dict) else data
            _write_cache(cache_key, cached)
        except Exception:
            logger.error("Failed to fetch pool yield for %s", pool_id)
            return pd.DataFrame(columns=["date", "apy", "apy_base", "apy_reward", "tvl_usd", "il_7d"]).set_index("date")

    if not cached:
        return pd.DataFrame(columns=["date", "apy", "apy_base", "apy_reward", "tvl_usd", "il_7d"]).set_index("date")

    df = pd.DataFrame(cached)
    if df.empty:
        return pd.DataFrame(columns=["date", "apy", "apy_base", "apy_reward", "tvl_usd", "il_7d"]).set_index("date")
        
    df["date"] = pd.to_datetime(df["timestamp"], format="mixed", utc=True).dt.floor("D")
    df = df.rename(columns={"tvlUsd": "tvl_usd", "apyBase": "apy_base", "apyReward": "apy_reward", "il7d": "il_7d"})
    
    cols = ["date", "apy", "apy_base", "apy_reward", "tvl_usd", "il_7d"]
    for c in cols:
        if c not in df.columns:
            df[c] = 0.0
            
    df = df[cols].groupby("date").mean()
    return df

def fetch_eth_price() -> pd.DataFrame:
    cache_key = "eth_price"
    cached = _read_cache(cache_key)
    if cached is None:
        # Try DefiLlama fallback to CoinGecko
        try:
            raw = _fetch_with_retry(f"{COINGECKO_BASE}/coins/ethereum/market_chart", params={"vs_currency": "usd", "days": "365"}, delay=1.0)
            prices = raw.get("prices", [])
            cached = [{"timestamp": p[0], "price_usd": p[1]} for p in prices]
            _write_cache(cache_key, cached)
        except Exception:
            logger.error("Failed to fetch ETH price")
            return pd.DataFrame(columns=["date", "price_usd"]).set_index("date")

    df = pd.DataFrame(cached)
    if df.empty:
        return pd.DataFrame(columns=["date", "price_usd"]).set_index("date")
        
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.floor("D")
    df = df.groupby("date")["price_usd"].mean().to_frame()
    return df

def fetch_steth_ratio() -> pd.DataFrame:
    cache_key = "steth_ratio"
    cached = _read_cache(cache_key)
    if cached is None:
        try:
            raw = _fetch_with_retry(f"{COINGECKO_BASE}/coins/staked-ether/market_chart", params={"vs_currency": "eth", "days": "365"}, delay=1.0)
            prices = raw.get("prices", [])
            cached = [{"timestamp": p[0], "ratio": p[1]} for p in prices]
            _write_cache(cache_key, cached)
        except Exception:
            logger.error("Failed to fetch stETH ratio")
            return pd.DataFrame(columns=["date", "ratio"]).set_index("date")

    df = pd.DataFrame(cached)
    if df.empty:
        return pd.DataFrame(columns=["date", "ratio"]).set_index("date")
        
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.floor("D")
    df = df.groupby("date")["ratio"].mean().to_frame()
    return df

def fetch_all_data() -> BacktestDataset:
    """Fetch and assemble all historical backtest data."""
    logger.info("Starting historical data fetch...")
    
    pool_mapping = get_pool_ids()
    protocol_tvl = {}
    pool_apy = {}
    pool_metadata = {}
    
    # Load full pools list for metadata lookups
    full_pools_list = _read_cache("pools_full_list")
    if full_pools_list and isinstance(full_pools_list, list):
        pools_by_id = {p["pool"]: p for p in full_pools_list if "pool" in p}
    else:
        pools_by_id = {}
    
    for name in PROTOCOL_NAMES:
        # TVL uses the DeFiLlama protocol slug
        tvl_slug = DEFILLAMA_TVL_SLUGS.get(name, name)
        logger.info("Fetching TVL for %s (slug: %s)", name, tvl_slug)
        protocol_tvl[name] = fetch_protocol_tvl(tvl_slug)
        
        pool_id = pool_mapping.get(name)
        if pool_id:
            logger.info("Fetching APY for %s (pool %s)", name, pool_id)
            pool_apy[name] = fetch_pool_apy(pool_id)
            p_data = pools_by_id.get(pool_id, {})
            pool_metadata[name] = {
                "pool_id": pool_id,
                "symbol": p_data.get("symbol", ""),
                "project": p_data.get("project", name)
            }
        else:
            logger.warning("No pool mapping found for %s", name)
            pool_apy[name] = pd.DataFrame(columns=["apy", "apy_base", "apy_reward", "tvl_usd", "il_7d"])
            pool_metadata[name] = {}

    logger.info("Fetching ETH price")
    eth_price = fetch_eth_price()
    
    logger.info("Fetching stETH ratio")
    steth_ratio = fetch_steth_ratio()
    
    # Determine date range
    all_dates = pd.Index([])
    for df in protocol_tvl.values():
        all_dates = all_dates.union(df.index)
    for df in pool_apy.values():
        all_dates = all_dates.union(df.index)
        
    all_dates = all_dates.union(eth_price.index).union(steth_ratio.index)
    
    start_date = all_dates.min() if not all_dates.empty else pd.Timestamp.now(tz="UTC")
    end_date = all_dates.max() if not all_dates.empty else pd.Timestamp.now(tz="UTC")
    
    # Forward fill indexing
    full_idx = pd.date_range(start=start_date, end=end_date, freq="D", tz="UTC")
    
    def align_and_ffill(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        df = df[~df.index.duplicated(keep='last')]
        df = df.reindex(full_idx)
        df = df.ffill().bfill()
        return df

    protocol_tvl = {k: align_and_ffill(v) for k, v in protocol_tvl.items()}
    pool_apy = {k: align_and_ffill(v) for k, v in pool_apy.items()}
    eth_price = align_and_ffill(eth_price)
    steth_ratio = align_and_ffill(steth_ratio)

    logger.info("Finished data fetch. Date range: %s to %s", start_date.date(), end_date.date())

    return BacktestDataset(
        protocol_tvl=protocol_tvl,
        pool_apy=pool_apy,
        eth_price=eth_price,
        steth_ratio=steth_ratio,
        pool_metadata=pool_metadata,
        data_start=start_date,
        data_end=end_date
    )
