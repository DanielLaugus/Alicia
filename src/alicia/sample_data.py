"""Deterministic synthetic BTC/USDT 1h OHLCV for offline backtests and tests."""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_sample_ohlcv(
    n_1h: int = 1800,
    seed: int = 7,
    start: str = "2024-01-01 00:00:00",
    dip_start: int = 1200,
) -> pd.DataFrame:
    """Uptrend warmup, then a selloff and a high-volume bounce (RSI cross)."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, periods=n_1h, freq="1h", tz="UTC")

    returns = rng.normal(0.00018, 0.0032, n_1h)
    # Persist an uptrend so price stays above a lagging EMA200(4h).
    returns[:800] += 0.00035

    selloff = 16
    bounce = 8
    if dip_start + selloff + bounce < n_1h:
        returns[dip_start : dip_start + selloff] = -0.011
        returns[dip_start + selloff : dip_start + selloff + bounce] = 0.016

    close = 40_000.0 * np.exp(np.cumsum(returns))
    open_ = np.empty_like(close)
    open_[0] = close[0]
    open_[1:] = close[:-1]

    wick = np.abs(rng.normal(0.0, 0.0018, n_1h))
    high = np.maximum(open_, close) * (1.0 + wick)
    low = np.minimum(open_, close) * (1.0 - wick)

    volume = rng.uniform(80.0, 160.0, n_1h)
    if dip_start + selloff + bounce < n_1h:
        volume[dip_start + selloff : dip_start + selloff + bounce] = rng.uniform(
            400.0, 520.0, bounce
        )

    frame = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=index,
    )
    frame.index.name = "timestamp"
    return frame


def ohlcv_to_csv(df: pd.DataFrame, path) -> None:
    out = df.copy()
    out.index.name = "timestamp"
    out.to_csv(path)


def ohlcv_from_csv(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.set_index("timestamp")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df
