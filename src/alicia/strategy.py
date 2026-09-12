"""Explicit LONG-only entry and exit rules (see docs/SPEC.md)."""

from __future__ import annotations

from dataclasses import dataclass

RSI_CROSS_LEVEL = 40.0
STOP_ATR_MULT = 1.5
TP_ATR_MULT = 2.0  # product default (~1:1.33 RR). Experiments may use 3.0 for 1:2.


@dataclass(frozen=True)
class ExtraFilters:
    """Optional entry gates. All off = product default."""

    require_ema_slope: bool = False
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
    atr_pct: float | None = None,
    atr_pct_q25: float | None = None,
) -> EntryDecision:
    """Return whether a new LONG may be opened on this closed bar."""
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
    if extra.chop_filter:
        if atr_pct is None or atr_pct_q25 is None or not np_finite(atr_pct) or not np_finite(atr_pct_q25):
            return EntryDecision(False, "ATR% chop filter not ready")
        if atr_pct < atr_pct_q25:
            return EntryDecision(False, "ATR% below rolling 25th percentile (chop)")
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


def np_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))
