"""Paper-path scaffold: evaluate the live signal on public or sample data.

Does not place orders. Does not move funds off-exchange.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from alicia.calendar import calendar_from_settings
from alicia.config import Settings
from alicia.data import fetch_public_ohlcv, load_ohlcv
from alicia.indicators import attach_indicators
from alicia.strategy import EntryDecision, evaluate_entry, stop_price, take_profit_price


@dataclass(frozen=True)
class PaperSnapshot:
    timestamp: pd.Timestamp
    price: float
    decision: EntryDecision
    stop: float | None
    take_profit: float | None
    atr: float | None
    rsi: float | None
    prev_rsi: float | None
    ema200_4h: float | None
    volume: float
    volume_ma: float | None


def evaluate_latest(
    ohlcv_1h: pd.DataFrame,
    settings: Settings,
    *,
    has_open_position: bool = False,
) -> PaperSnapshot:
    frame = attach_indicators(ohlcv_1h)
    row = frame.iloc[-1]
    ts = frame.index[-1]
    calendar = calendar_from_settings(settings)
    event_reason = calendar.pause_reason(ts.tz_convert("UTC").date() if ts.tzinfo else ts.date())

    ema = None if pd.isna(row["ema200_4h"]) else float(row["ema200_4h"])
    rsi_v = None if pd.isna(row["rsi_14"]) else float(row["rsi_14"])
    rsi_p = None if pd.isna(row["rsi_14_prev"]) else float(row["rsi_14_prev"])
    vol_ma = None if pd.isna(row["volume_ma20"]) else float(row["volume_ma20"])
    atr_v = None if pd.isna(row["atr_14"]) else float(row["atr_14"])
    price = float(row["close"])

    decision = evaluate_entry(
        price=price,
        ema200_4h=ema,
        rsi_value=rsi_v,
        prev_rsi=rsi_p,
        volume=float(row["volume"]),
        volume_ma=vol_ma,
        has_open_position=has_open_position,
        paused=event_reason is not None,
        pause_reason=event_reason,
    )
    stop = take = None
    if atr_v is not None and atr_v > 0:
        stop = stop_price(price, atr_v)
        take = take_profit_price(price, atr_v)
    return PaperSnapshot(
        timestamp=ts,
        price=price,
        decision=decision,
        stop=stop,
        take_profit=take,
        atr=atr_v,
        rsi=rsi_v,
        prev_rsi=rsi_p,
        ema200_4h=ema,
        volume=float(row["volume"]),
        volume_ma=vol_ma,
    )


def load_paper_ohlcv(settings: Settings, csv_path: str | None = None, use_public: bool = False) -> pd.DataFrame:
    if csv_path:
        return load_ohlcv(csv_path)
    if use_public:
        return fetch_public_ohlcv(symbol=settings.symbol, exchange_id=settings.exchange_id)
    return load_ohlcv(synthetic=True)
