"""Public perpetual funding history. Filter-only; never invents a series."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pandas as pd

OKX_FUNDING = "https://www.okx.com/api/v5/public/funding-rate-history"
BINANCE_FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate"


def _get_json(url: str, timeout: float = 20.0) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "alicia-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_okx_funding(inst_id: str = "BTC-USDT-SWAP", limit: int = 100) -> pd.Series:
    """OKX public swap funding. ``limit`` max is 100 per page; paginate via after."""
    rows: list[tuple[pd.Timestamp, float]] = []
    after: str | None = None
    while True:
        url = f"{OKX_FUNDING}?instId={inst_id}&limit={int(limit)}"
        if after:
            url += f"&after={after}"
        payload = _get_json(url)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not data:
            break
        for item in data:
            ts = pd.Timestamp(int(item["fundingTime"]), unit="ms", tz="UTC")
            rows.append((ts, float(item["fundingRate"])))
        if len(data) < limit:
            break
        after = str(data[-1]["fundingTime"])
        if len(rows) > 4000:
            break
    if not rows:
        return pd.Series(dtype="float64")
    series = pd.Series({t: r for t, r in rows}, dtype="float64").sort_index()
    return series[~series.index.duplicated(keep="last")]


def fetch_binance_funding(symbol: str = "BTCUSDT", limit: int = 1000) -> pd.Series:
    """Binance USDT-M public funding. ``limit`` max 1000; paginate with startTime."""
    rows: list[tuple[pd.Timestamp, float]] = []
    start: int | None = None
    while True:
        url = f"{BINANCE_FUNDING}?symbol={symbol}&limit={int(limit)}"
        if start is not None:
            url += f"&startTime={start}"
        payload = _get_json(url)
        if not isinstance(payload, list) or not payload:
            break
        for item in payload:
            ts = pd.Timestamp(int(item["fundingTime"]), unit="ms", tz="UTC")
            rows.append((ts, float(item["fundingRate"])))
        last_ms = int(payload[-1]["fundingTime"])
        if len(payload) < limit:
            break
        nxt = last_ms + 1
        if start is not None and nxt <= start:
            break
        start = nxt
        if len(rows) > 4000:
            break
    if not rows:
        return pd.Series(dtype="float64")
    series = pd.Series({t: r for t, r in rows}, dtype="float64").sort_index()
    return series[~series.index.duplicated(keep="last")]


def try_fetch_funding(symbol: str = "BTC") -> tuple[pd.Series, str]:
    """Try OKX then Binance. Returns (series, source) or empty series + reason."""
    inst = "BTC-USDT-SWAP" if symbol.upper().startswith("BTC") else "ETH-USDT-SWAP"
    binance_sym = "BTCUSDT" if symbol.upper().startswith("BTC") else "ETHUSDT"
    try:
        series = fetch_okx_funding(inst)
        if not series.empty:
            return series, "okx-public"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as exc:
        okx_err = str(exc)
    else:
        okx_err = "empty"
    try:
        series = fetch_binance_funding(binance_sym)
        if not series.empty:
            return series, "binance-public"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return pd.Series(dtype="float64"), f"okx:{okx_err}; binance:{exc}"
    return pd.Series(dtype="float64"), f"okx:{okx_err}; binance:empty"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
