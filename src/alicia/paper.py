"""Paper-path: evaluate the latest closed-bar signal. Never places orders."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from alicia.calendar import calendar_from_settings
from alicia.config import Settings
from alicia.data import PUBLIC_FALLBACKS, fetch_public_ohlcv, load_ohlcv
from alicia.indicators import attach_indicators
from alicia.orderbook import (
    BookDecision,
    BookSnapshot,
    apply_orderbook_gate,
    evaluate_book_from_settings,
)
from alicia.session import StrategyProfile, session_allows_signal
from alicia.strategy import (
    TP_ATR_MULT,
    ExtraFilters,
    EntryDecision,
    decide_entry,
    evaluate_entry,
    stop_price,
    take_profit_price,
)


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
    book: BookDecision | None = None
    estimated_cross_slippage_bps: float | None = None
    book_venue: str | None = None
    profile: str = "default"
    symbol: str | None = None
    signal: str = "rsi"
    adx: float | None = None


def _atr_multiples(profile: StrategyProfile | None) -> tuple[float, float]:
    if profile is None:
        return 1.5, TP_ATR_MULT
    stop = profile.stop_atr if profile.stop_atr else 1.5
    if profile.reward_risk is not None and profile.reward_risk > 0:
        return stop, stop * float(profile.reward_risk)
    return stop, TP_ATR_MULT


def evaluate_latest(
    ohlcv_1h: pd.DataFrame,
    settings: Settings,
    *,
    has_open_position: bool = False,
    book: BookSnapshot | None = None,
    book_venue: str | None = None,
    profile: StrategyProfile | None = None,
    symbol: str | None = None,
) -> PaperSnapshot:
    """Evaluate the last closed bar.

    ``profile=None`` keeps the product RSI 1h/4h path (unit tests / dry checks).
    The paper CLI passes ``paper-eth`` / ``regime-20`` for the locked ETH profile.
    """
    trend_tf = profile.trend_timeframe if profile is not None else "4h"
    entry_tf = profile.entry_timeframe if profile is not None else "1h"
    extra = profile.extra if profile is not None else ExtraFilters()
    signal = profile.signal if profile is not None else "rsi"
    donchian_n = profile.donchian_n if profile is not None else 20
    session = profile.session if profile is not None else None
    stop_atr, tp_atr = _atr_multiples(profile)

    frame = attach_indicators(ohlcv_1h, trend_timeframe=trend_tf, donchian_n=donchian_n)
    row = frame.iloc[-1]
    ts = frame.index[-1]
    calendar = calendar_from_settings(settings)
    event_reason = calendar.pause_reason(ts.tz_convert("UTC").date() if ts.tzinfo else ts.date())
    session_ok = session_allows_signal(ts, entry_tf, session)

    def _f(key: str) -> float | None:
        if key not in frame.columns or pd.isna(row[key]):
            return None
        return float(row[key])

    ema = _f("ema200_4h")
    rsi_v = _f("rsi_14")
    rsi_p = _f("rsi_14_prev")
    vol_ma = _f("volume_ma20")
    atr_v = _f("atr_14")
    price = float(row["close"])
    adx_v = _f("adx_14")

    shared = dict(
        price=price,
        ema200_4h=ema,
        has_open_position=has_open_position,
        paused=event_reason is not None,
        pause_reason=event_reason,
        session_ok=session_ok,
        extra=extra,
        ema200_prev=_f("ema200_prev"),
        ema50=_f("ema50"),
        atr_pct=_f("atr_pct"),
        atr_pct_q25=_f("atr_pct_q25"),
        adx=adx_v,
        plus_di=_f("plus_di"),
        minus_di=_f("minus_di"),
        atr_pct_halt=_f("atr_pct_q90"),
    )
    if profile is None:
        candle = evaluate_entry(
            **shared,
            rsi_value=rsi_v,
            prev_rsi=rsi_p,
            volume=float(row["volume"]),
            volume_ma=vol_ma,
        )
    else:
        candle = decide_entry(
            signal,
            **shared,
            rsi_value=rsi_v,
            prev_rsi=rsi_p,
            volume=float(row["volume"]),
            volume_ma=vol_ma,
            prev_close=_f("close_prev"),
            donchian_high=_f("donchian_high"),
            donchian_low=_f("donchian_low"),
            donchian_n=donchian_n,
            ema20=_f("ema20"),
            side=profile.side,
        )
    book_decision = None
    slip_bps = None
    if settings.orderbook_enabled:
        book_decision = evaluate_book_from_settings(book, settings)
        if book_decision.metrics is not None:
            slip_bps = book_decision.metrics.half_spread_bps
        candle = apply_orderbook_gate(candle, book, settings, apply=True)
    stop = take = None
    if atr_v is not None and atr_v > 0:
        stop = stop_price(price, atr_v, atr_mult=stop_atr)
        take = take_profit_price(price, atr_v, atr_mult=tp_atr)
    return PaperSnapshot(
        timestamp=ts,
        price=price,
        decision=candle,
        stop=stop,
        take_profit=take,
        atr=atr_v,
        rsi=rsi_v,
        prev_rsi=rsi_p,
        ema200_4h=ema,
        volume=float(row["volume"]),
        volume_ma=vol_ma,
        book=book_decision,
        estimated_cross_slippage_bps=slip_bps,
        book_venue=book_venue,
        profile=profile.name if profile is not None else "default",
        symbol=symbol or (profile.symbol if profile is not None else None) or settings.symbol,
        signal=signal,
        adx=adx_v,
    )


def load_paper_ohlcv(
    settings: Settings,
    csv_path: str | None = None,
    use_public: bool = False,
    *,
    timeframe: str = "1h",
    symbol: str | None = None,
) -> pd.DataFrame:
    if csv_path:
        return load_ohlcv(csv_path)
    pair = symbol or settings.symbol
    if use_public:
        last_err: Exception | None = None
        seen: set[str] = set()
        venues = [
            settings.exchange_id,
            settings.orderbook_venue,
            *PUBLIC_FALLBACKS,
        ]
        for venue in venues:
            if not venue or venue in seen:
                continue
            seen.add(venue)
            try:
                return fetch_public_ohlcv(
                    symbol=pair,
                    exchange_id=venue,
                    timeframe=timeframe,
                    limit=1000,
                )
            except Exception as exc:  # pragma: no cover - network
                last_err = exc
        raise RuntimeError(
            f"Public {pair} {timeframe} fetch failed on {sorted(seen)}: {last_err}"
        )
    return load_ohlcv(synthetic=True)
