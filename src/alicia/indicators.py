"""EMA, RSI (Wilder), ATR (Wilder), volume SMA — no lookahead helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(values: pd.Series | np.ndarray, period: int) -> pd.Series:
    series = pd.Series(values, dtype="float64")
    out = series.ewm(span=period, adjust=False).mean()
    out.iloc[: period - 1] = np.nan
    return out


def wilder_smooth(values: pd.Series | np.ndarray, period: int) -> pd.Series:
    """RMA / Wilder moving average (used by RSI and ATR)."""
    series = pd.Series(values, dtype="float64")
    out = series.ewm(alpha=1.0 / period, adjust=False).mean()
    out.iloc[: period - 1] = np.nan
    return out


def rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.astype("float64").diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = wilder_smooth(gain, period)
    avg_loss = wilder_smooth(loss, period)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.where(avg_loss != 0.0, 100.0)
    out = out.where(avg_gain != 0.0, 0.0)
    # both zero → flat, RSI 50
    both_zero = (avg_gain == 0.0) & (avg_loss == 0.0)
    out = out.where(~both_zero, 50.0)
    return out


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    return wilder_smooth(true_range(high, low, close), period)


def sma(values: pd.Series, period: int) -> pd.Series:
    return values.astype("float64").rolling(window=period, min_periods=period).mean()


PANDAS_RULES = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
}

TREND_COMPLETE = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
}


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """UTC OHLCV resample. Index must be timezone-aware UTC or naive UTC."""
    if timeframe not in PANDAS_RULES:
        raise ValueError(f"Unsupported resample timeframe: {timeframe}")
    frame = df.copy()
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    else:
        frame.index = frame.index.tz_convert("UTC")
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    rule = PANDAS_RULES[timeframe]
    return frame.resample(rule, label="left", closed="left").agg(agg).dropna(subset=["close"])


def resample_ohlcv_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """UTC 4h candles from 1h OHLCV (product-default trend TF)."""
    return resample_ohlcv(df_1h, "4h")


def attach_indicators(df: pd.DataFrame, *, trend_timeframe: str = "4h") -> pd.DataFrame:
    """Add RSI/ATR/volume MA on the bar TF and completed-trend EMA200 (no lookahead).

    Product default is 1h bars + 4h EMA200. The 1m experiment uses 1m bars + 1h EMA200.
    The column name ``ema200_4h`` is kept as the trend-EMA series for callers.
    """
    if df.empty:
        raise ValueError("OHLCV frame is empty")

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"OHLCV missing columns: {sorted(missing)}")
    if trend_timeframe not in TREND_COMPLETE:
        raise ValueError(f"Unsupported trend timeframe: {trend_timeframe}")

    frame = df.copy().sort_index()
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    else:
        frame.index = frame.index.tz_convert("UTC")

    frame["rsi_14"] = rsi(frame["close"], 14)
    frame["rsi_14_prev"] = frame["rsi_14"].shift(1)
    frame["atr_14"] = atr(frame["high"], frame["low"], frame["close"], 14)
    frame["volume_ma20"] = sma(frame["volume"], 20)

    trend = resample_ohlcv(frame[["open", "high", "low", "close", "volume"]], trend_timeframe)
    trend["ema200_4h"] = ema(trend["close"], 200)
    # A trend bar that starts at T is complete at T+len; only then may entry bars see it.
    complete = trend.copy()
    complete.index = complete.index + TREND_COMPLETE[trend_timeframe]
    aligned = complete[["ema200_4h"]].reindex(frame.index, method="ffill")
    frame["ema200_4h"] = aligned["ema200_4h"]
    return frame
