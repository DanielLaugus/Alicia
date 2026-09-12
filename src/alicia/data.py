"""OHLCV loaders. Public fetch is optional (ccxt) and never needs private keys."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from alicia.sample_data import generate_sample_ohlcv, ohlcv_from_csv


def load_ohlcv(csv_path: str | Path | None = None) -> pd.DataFrame:
    if csv_path:
        return ohlcv_from_csv(csv_path)
    return generate_sample_ohlcv()


def fetch_public_ohlcv(
    symbol: str = "BTC/USDT",
    exchange_id: str = "binance",
    timeframe: str = "1h",
    limit: int = 1000,
) -> pd.DataFrame:
    """Public market data only. No API key. Raises if ccxt is not installed."""
    try:
        import ccxt  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "ccxt is not installed. Run: pip install 'alicia[exchange]' "
            "or use sample data / a CSV."
        ) from exc

    exchange_cls = getattr(ccxt, exchange_id)
    exchange = exchange_cls({"enableRateLimit": True})
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    frame = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    return frame.set_index("timestamp")
