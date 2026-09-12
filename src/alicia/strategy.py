"""Explicit LONG-only entry and exit rules (see docs/SPEC.md)."""

from __future__ import annotations

from dataclasses import dataclass

RSI_CROSS_LEVEL = 40.0
STOP_ATR_MULT = 1.5
TP_ATR_MULT = 2.0  # product default (~1:1.33 RR). Experiments may use 3.0 for 1:2.
DONCHIAN_N = 20
SIGNALS = ("rsi", "breakout", "pullback")
STOP_MODES = ("atr", "bar-low")


@dataclass(frozen=True)
class ExtraFilters:
    """Optional entry gates. All off = product default."""

    require_ema_slope: bool = False
    require_ema50: bool = False
    chop_filter: bool = False
    rsi_from: float | None = None


@dataclass(frozen=True)
class EntryDecision:
    enter: bool
    reason: str


def rsi_crosses_up_through(prev_rsi: float, rsi_value: float, level: float = RSI_CROSS_LEVEL) -> bool:
    return prev_rsi < level < rsi_value


def volume_above_average(volume: float, volume_ma: float) -> bool:
    return volume_ma > 0 and volume > volume_ma


def trend_allows_long(price: float, ema200_4h: float) -> bool:
    return price > ema200_4h


def stop_price(entry: float, atr_value: float, *, atr_mult: float = STOP_ATR_MULT) -> float:
    if atr_value <= 0:
        raise ValueError("ATR must be positive to place a stop")
    if atr_mult <= 0:
        raise ValueError("Stop ATR multiple must be positive")
    return entry - atr_mult * atr_value


def take_profit_price(entry: float, atr_value: float, *, atr_mult: float = TP_ATR_MULT) -> float:
    if atr_value <= 0:
        raise ValueError("ATR must be positive to place a take-profit")
    if atr_mult <= 0:
        raise ValueError("Take-profit ATR multiple must be positive")
    return entry + atr_mult * atr_value


def common_long_gates(
    *,
    price: float,
    ema200_4h: float | None,
    has_open_position: bool,
    paused: bool = False,
    pause_reason: str | None = None,
    session_ok: bool = True,
    extra: ExtraFilters | None = None,
    ema200_prev: float | None = None,
    ema50: float | None = None,
    atr_pct: float | None = None,
    atr_pct_q25: float | None = None,
) -> EntryDecision | None:
    """Shared pause / one-position / session / EMA200 (+ optional extras).

    Returns a blocking decision, or None when the common gates pass.
    """
    extra = extra or ExtraFilters()
    if paused:
        return EntryDecision(False, pause_reason or "kill-switch / pause is active")
    if has_open_position:
        return EntryDecision(False, "max one open position; no averaging down")
    if not session_ok:
        return EntryDecision(False, "outside session window (no new entries off-hours)")
    if ema200_4h is None or not np_finite(ema200_4h):
        return EntryDecision(False, "EMA200(4h) not ready")
    if not trend_allows_long(price, ema200_4h):
        return EntryDecision(False, "price is not above EMA200(4h)")
    if extra.require_ema_slope:
        if ema200_prev is None or not np_finite(ema200_prev):
            return EntryDecision(False, "EMA200 slope not ready")
        if ema200_4h <= ema200_prev:
            return EntryDecision(False, "EMA200 is not sloping up")
    if extra.require_ema50:
        if ema50 is None or not np_finite(ema50):
            return EntryDecision(False, "EMA50 not ready")
        if price <= ema50:
            return EntryDecision(False, "price is not above EMA50")
    if extra.chop_filter:
        if atr_pct is None or atr_pct_q25 is None or not np_finite(atr_pct) or not np_finite(atr_pct_q25):
            return EntryDecision(False, "ATR% chop filter not ready")
        if atr_pct < atr_pct_q25:
            return EntryDecision(False, "ATR% below rolling 25th percentile (chop)")
    return None


def donchian_breakout_cross(
    close: float,
    prev_close: float,
    prior_n_high: float,
) -> bool:
    """Close crosses above the prior N-bar high (channel excludes the current bar)."""
    return prev_close <= prior_n_high < close


def ema_reclaim_after_pullback(close: float, prev_close: float, ema_fast: float) -> bool:
    """Previous close was below the fast EMA; this close is back at/above it."""
    return prev_close < ema_fast <= close


def evaluate_entry(
    *,
    price: float,
    ema200_4h: float | None,
    rsi_value: float | None,
    prev_rsi: float | None,
    volume: float,
    volume_ma: float | None,
    has_open_position: bool,
    paused: bool = False,
    pause_reason: str | None = None,
    session_ok: bool = True,
    extra: ExtraFilters | None = None,
    ema200_prev: float | None = None,
    ema50: float | None = None,
    atr_pct: float | None = None,
    atr_pct_q25: float | None = None,
) -> EntryDecision:
    """Product RSI bounce: trend + RSI(14) cross up through 40 + volume."""
    extra = extra or ExtraFilters()
    blocked = common_long_gates(
        price=price,
        ema200_4h=ema200_4h,
        has_open_position=has_open_position,
        paused=paused,
        pause_reason=pause_reason,
        session_ok=session_ok,
        extra=extra,
        ema200_prev=ema200_prev,
        ema50=ema50,
        atr_pct=atr_pct,
        atr_pct_q25=atr_pct_q25,
    )
    if blocked is not None:
        return blocked
    if rsi_value is None or prev_rsi is None or not np_finite(rsi_value) or not np_finite(prev_rsi):
        return EntryDecision(False, "RSI(14) 1h not ready")
    if extra.rsi_from is not None and not (prev_rsi < extra.rsi_from):
        return EntryDecision(
            False,
            f"RSI(14) did not come from below {extra.rsi_from:g} ({prev_rsi:.2f})",
        )
    if not rsi_crosses_up_through(prev_rsi, rsi_value, RSI_CROSS_LEVEL):
        return EntryDecision(
            False,
            f"RSI(14) did not cross up through {RSI_CROSS_LEVEL:g} ({prev_rsi:.2f} → {rsi_value:.2f})",
        )
    if volume_ma is None or not np_finite(volume_ma):
        return EntryDecision(False, "volume MA20 not ready")
    if not volume_above_average(volume, volume_ma):
        return EntryDecision(False, "1h volume is not above its 20-period average")
    return EntryDecision(True, "LONG: trend + RSI cross + volume confirmation")


def evaluate_breakout(
    *,
    price: float,
    ema200_4h: float | None,
    prev_close: float | None,
    donchian_high: float | None,
    has_open_position: bool,
    paused: bool = False,
    pause_reason: str | None = None,
    session_ok: bool = True,
    extra: ExtraFilters | None = None,
    ema200_prev: float | None = None,
    ema50: float | None = None,
    atr_pct: float | None = None,
    atr_pct_q25: float | None = None,
    donchian_n: int = DONCHIAN_N,
) -> EntryDecision:
    """Donchian / N-bar high breakout. No RSI. Volume is not required."""
    extra = extra or ExtraFilters()
    blocked = common_long_gates(
        price=price,
        ema200_4h=ema200_4h,
        has_open_position=has_open_position,
        paused=paused,
        pause_reason=pause_reason,
        session_ok=session_ok,
        extra=extra,
        ema200_prev=ema200_prev,
        ema50=ema50,
        atr_pct=atr_pct,
        atr_pct_q25=atr_pct_q25,
    )
    if blocked is not None:
        return blocked
    if donchian_high is None or prev_close is None or not np_finite(donchian_high) or not np_finite(prev_close):
        return EntryDecision(False, f"Donchian({donchian_n}) channel not ready")
    if not donchian_breakout_cross(price, prev_close, donchian_high):
        return EntryDecision(
            False,
            f"close did not break prior {donchian_n}-bar high ({donchian_high:.2f})",
        )
    return EntryDecision(True, f"LONG: trend + Donchian({donchian_n}) high breakout")


def evaluate_pullback(
    *,
    price: float,
    ema200_4h: float | None,
    prev_close: float | None,
    ema20: float | None,
    has_open_position: bool,
    paused: bool = False,
    pause_reason: str | None = None,
    session_ok: bool = True,
    extra: ExtraFilters | None = None,
    ema200_prev: float | None = None,
    ema50: float | None = None,
    atr_pct: float | None = None,
    atr_pct_q25: float | None = None,
) -> EntryDecision:
    """Optional A/B: reclaim EMA20 after a pullback while still above EMA200. No RSI."""
    extra = extra or ExtraFilters()
    blocked = common_long_gates(
        price=price,
        ema200_4h=ema200_4h,
        has_open_position=has_open_position,
        paused=paused,
        pause_reason=pause_reason,
        session_ok=session_ok,
        extra=extra,
        ema200_prev=ema200_prev,
        ema50=ema50,
        atr_pct=atr_pct,
        atr_pct_q25=atr_pct_q25,
    )
    if blocked is not None:
        return blocked
    if ema20 is None or prev_close is None or not np_finite(ema20) or not np_finite(prev_close):
        return EntryDecision(False, "EMA20 pullback series not ready")
    if not ema_reclaim_after_pullback(price, prev_close, ema20):
        return EntryDecision(False, "close did not reclaim EMA20 after a pullback")
    return EntryDecision(True, "LONG: trend + EMA20 reclaim after pullback")


def decide_entry(
    signal: str,
    *,
    price: float,
    ema200_4h: float | None,
    has_open_position: bool,
    paused: bool = False,
    pause_reason: str | None = None,
    session_ok: bool = True,
    extra: ExtraFilters | None = None,
    ema200_prev: float | None = None,
    ema50: float | None = None,
    atr_pct: float | None = None,
    atr_pct_q25: float | None = None,
    rsi_value: float | None = None,
    prev_rsi: float | None = None,
    volume: float = 0.0,
    volume_ma: float | None = None,
    prev_close: float | None = None,
    donchian_high: float | None = None,
    donchian_n: int = DONCHIAN_N,
    ema20: float | None = None,
) -> EntryDecision:
    """Dispatch to RSI (product default), Donchian breakout, or EMA pullback."""
    kind = (signal or "rsi").strip().lower()
    shared = dict(
        price=price,
        ema200_4h=ema200_4h,
        has_open_position=has_open_position,
        paused=paused,
        pause_reason=pause_reason,
        session_ok=session_ok,
        extra=extra,
        ema200_prev=ema200_prev,
        ema50=ema50,
        atr_pct=atr_pct,
        atr_pct_q25=atr_pct_q25,
    )
    if kind == "breakout":
        return evaluate_breakout(
            **shared,
            prev_close=prev_close,
            donchian_high=donchian_high,
            donchian_n=donchian_n,
        )
    if kind == "pullback":
        return evaluate_pullback(
            **shared,
            prev_close=prev_close,
            ema20=ema20,
        )
    if kind == "rsi":
        return evaluate_entry(
            **shared,
            rsi_value=rsi_value,
            prev_rsi=prev_rsi,
            volume=volume,
            volume_ma=volume_ma,
        )
    raise ValueError(f"Unknown signal family: {signal!r} (expected {SIGNALS})")


def stop_from_mode(
    entry: float,
    atr_value: float,
    *,
    atr_mult: float = STOP_ATR_MULT,
    signal_low: float | None = None,
    mode: str = "atr",
) -> float:
    """ATR stop, or the breakout-bar low when that is below the fill."""
    atr_stop = stop_price(entry, atr_value, atr_mult=atr_mult)
    kind = (mode or "atr").strip().lower()
    if kind == "atr":
        return atr_stop
    if kind != "bar-low":
        raise ValueError(f"Unknown stop mode: {mode!r} (expected {STOP_MODES})")
    if signal_low is None or not np_finite(signal_low) or signal_low >= entry:
        return atr_stop
    return float(signal_low)


def np_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))
