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


def donchian_prior_high(high: pd.Series, period: int = 20) -> pd.Series:
    """Prior N-bar high: rolling max of high, shifted 1 so the current bar is excluded."""
    if period < 1:
        raise ValueError("Donchian period must be >= 1")
    return high.astype("float64").rolling(window=period, min_periods=period).max().shift(1)


def donchian_prior_low(low: pd.Series, period: int = 20) -> pd.Series:
    """Prior N-bar low: rolling min of low, shifted 1 so the current bar is excluded."""
    if period < 1:
        raise ValueError("Donchian period must be >= 1")
    return low.astype("float64").rolling(window=period, min_periods=period).min().shift(1)


def adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Wilder ADX / +DI / −DI. First ~2×period bars are NaN (warmup)."""
    up = high.astype("float64").diff()
    down = -low.astype("float64").diff()
    plus_dm = up.where((up > down) & (up > 0.0), 0.0)
    minus_dm = down.where((down > up) & (down > 0.0), 0.0)
    atr_v = atr(high, low, close, period)
    plus_di = 100.0 * wilder_smooth(plus_dm, period) / atr_v.replace(0.0, np.nan)
    minus_di = 100.0 * wilder_smooth(minus_dm, period) / atr_v.replace(0.0, np.nan)
    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    return wilder_smooth(dx, period), plus_di, minus_di


PANDAS_RULES = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1D",
}

TREND_COMPLETE = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "1h": pd.Timedelta(hours=1),
    "2h": pd.Timedelta(hours=2),
    "4h": pd.Timedelta(hours=4),
    "8h": pd.Timedelta(hours=8),
    "12h": pd.Timedelta(hours=12),
    "1d": pd.Timedelta(days=1),
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


def attach_indicators(
    df: pd.DataFrame,
    *,
    trend_timeframe: str = "4h",
    donchian_n: int = 20,
) -> pd.DataFrame:
    """Add RSI/ATR/volume MA on the bar TF and completed-trend EMA200 (no lookahead).

    Product default is 1h bars + 4h EMA200. Experiments: 1m+1h, 2h+8h, 4h+12h EMA200.
    The column name ``ema200_4h`` is kept as the trend-EMA series for callers.
    Also attaches EMA20 and a no-lookahead Donchian prior-N high (breakout family).
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
    frame["atr_pct"] = frame["atr_14"] / frame["close"].replace(0.0, np.nan)
    frame["atr_pct_q25"] = frame["atr_pct"].rolling(window=200, min_periods=50).quantile(0.25)
    frame["volume_ma20"] = sma(frame["volume"], 20)
    frame["ema20"] = ema(frame["close"], 20)
    frame["ema50"] = ema(frame["close"], 50)
    frame["close_prev"] = frame["close"].shift(1)
    frame["donchian_high"] = donchian_prior_high(frame["high"], donchian_n)
    frame["donchian_low"] = donchian_prior_low(frame["low"], donchian_n)
    adx_v, plus_di, minus_di = adx(frame["high"], frame["low"], frame["close"], 14)
    frame["adx_14"] = adx_v
    frame["plus_di"] = plus_di
    frame["minus_di"] = minus_di
    frame["atr_pct_q90"] = frame["atr_pct"].rolling(window=200, min_periods=50).quantile(0.90)
    frame["atr_pct_med"] = frame["atr_pct"].rolling(window=200, min_periods=50).median()

    trend = resample_ohlcv(frame[["open", "high", "low", "close", "volume"]], trend_timeframe)
    trend["ema200_4h"] = ema(trend["close"], 200)
    # A trend bar that starts at T is complete at T+len; only then may entry bars see it.
    complete = trend.copy()
    complete.index = complete.index + TREND_COMPLETE[trend_timeframe]
    aligned = complete[["ema200_4h"]].reindex(frame.index, method="ffill")
    frame["ema200_4h"] = aligned["ema200_4h"]
    frame["ema200_prev"] = frame["ema200_4h"].shift(1)
    return frame
