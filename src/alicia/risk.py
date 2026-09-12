"""Position sizing and monthly drawdown kill-switch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from alicia.config import MAX_RISK_PCT, MIN_RISK_PCT, Settings


def clamp_risk_pct(risk_pct: float) -> float:
    return min(max(risk_pct, MIN_RISK_PCT), MAX_RISK_PCT)


def position_qty(
    *,
    capital_eur: float,
    entry_price: float,
    stop: float,
    risk_pct: float,
    max_small_notional_eur: float,
    usdt_eur_rate: float = 1.0,
    available_quote: float | None = None,
) -> float:
    """BTC quantity for a long.

    Risk-to-stop uses 1–3% of capital. Notionals up to €200 are allowed on the
    small-book path; larger notionals exist only when derived from stop distance.
    """
    if entry_price <= 0:
        return 0.0
    stop_distance = entry_price - stop
    if stop_distance <= 0:
        return 0.0

    risk_pct = clamp_risk_pct(risk_pct)
    qty = (capital_eur * risk_pct) / stop_distance
    notional_usdt = qty * entry_price
    notional_eur = notional_usdt * usdt_eur_rate

    # Small-book: never exceed the €200 allowance unless risk-derived size is larger.
    if notional_eur <= max_small_notional_eur:
        qty = min(qty, max_small_notional_eur / (entry_price * usdt_eur_rate))
    # Above €200: keep the risk-derived quantity (already computed).

    if available_quote is not None:
        max_qty = available_quote / entry_price
        qty = min(qty, max(max_qty, 0.0))
    return float(max(qty, 0.0))


def size_from_settings(
    settings: Settings,
    *,
    entry_price: float,
    stop: float,
    capital_eur: float | None = None,
    available_quote: float | None = None,
) -> float:
    return position_qty(
        capital_eur=settings.capital_eur if capital_eur is None else capital_eur,
        entry_price=entry_price,
        stop=stop,
        risk_pct=settings.risk_pct,
        max_small_notional_eur=settings.max_small_notional_eur,
        usdt_eur_rate=settings.usdt_eur_rate,
        available_quote=available_quote,
    )


@dataclass
class MonthlyDrawdownGuard:
    """Pause new entries after −threshold drawdown from the month's equity peak."""

    threshold: float = 0.10
    month: date | None = None
    peak_equity: float | None = None
    halted: bool = False
    reason: str | None = None

    def update(self, ts: datetime, equity: float) -> bool:
        month_key = date(ts.year, ts.month, 1)
        if self.month != month_key:
            self.month = month_key
            self.peak_equity = equity
            self.halted = False
            self.reason = None

        assert self.peak_equity is not None
        if equity > self.peak_equity:
            self.peak_equity = equity

        if self.peak_equity > 0:
            drawdown = (equity - self.peak_equity) / self.peak_equity
            if drawdown <= -self.threshold:
                self.halted = True
                self.reason = (
                    f"monthly drawdown {drawdown:.2%} ≤ -{self.threshold:.0%} kill-switch"
                )
        return self.halted
