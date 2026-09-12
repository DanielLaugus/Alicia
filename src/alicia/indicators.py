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


def resample_ohlcv_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """UTC 4h candles from 1h OHLCV. Index must be timezone-aware UTC or naive UTC."""
    frame = df_1h.copy()
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
    out = frame.resample("4h", label="left", closed="left").agg(agg).dropna(subset=["close"])
    return out


def attach_indicators(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Add 1h RSI/ATR/volume MA and completed-4h EMA200 (forward-filled, no lookahead)."""
    if df_1h.empty:
        raise ValueError("OHLCV frame is empty")

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df_1h.columns)
    if missing:
        raise ValueError(f"OHLCV missing columns: {sorted(missing)}")

    frame = df_1h.copy().sort_index()
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    else:
        frame.index = frame.index.tz_convert("UTC")

    frame["rsi_14"] = rsi(frame["close"], 14)
    frame["rsi_14_prev"] = frame["rsi_14"].shift(1)
    frame["atr_14"] = atr(frame["high"], frame["low"], frame["close"], 14)
    frame["volume_ma20"] = sma(frame["volume"], 20)

    h4 = resample_ohlcv_4h(frame[["open", "high", "low", "close", "volume"]])
    h4["ema200_4h"] = ema(h4["close"], 200)
    # A 4h bar that starts at T is complete at T+4h. Only then may 1h bars see it.
    h4_complete = h4.copy()
    h4_complete.index = h4_complete.index + pd.Timedelta(hours=4)
    aligned = h4_complete[["ema200_4h"]].reindex(frame.index, method="ffill")
    frame["ema200_4h"] = aligned["ema200_4h"]
    return frame
