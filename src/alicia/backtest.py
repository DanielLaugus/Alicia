"""1h backtest engine: fees, slippage, one-position, kill-switch."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

import numpy as np
import pandas as pd

from alicia.calendar import EventCalendar, calendar_from_settings
from alicia.config import Settings, load_settings
from alicia.indicators import attach_indicators
from alicia.risk import MonthlyDrawdownGuard, size_from_settings
from alicia.session import SessionWindow, session_allows_signal
from alicia.strategy import ExtraFilters, EntryDecision, evaluate_entry, stop_price, take_profit_price


@dataclass
class Trade:
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp | None
    entry_price: float
    exit_price: float | None
    qty: float
    stop: float
    initial_stop: float
    take_profit: float
    reason_entry: str
    reason_exit: str | None = None
    pnl_quote: float | None = None
    fees_quote: float = 0.0
    slippage_quote: float = 0.0


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series | None = None
    start_capital: float = 0.0
    end_equity: float = 0.0
    decisions_sampled: list[tuple[pd.Timestamp, EntryDecision]] = field(default_factory=list)
    halt_events: list[str] = field(default_factory=list)
    source: str = "unknown"
    zero_cost_end_equity: float | None = None
    entry_timeframe: str = "1h"
    trend_timeframe: str = "4h"
    stop_atr_mult: float = 1.5
    tp_atr_mult: float = 2.0
    session_label: str | None = None
    profile: str = "default"
    extra_filters: ExtraFilters = field(default_factory=ExtraFilters)
    breakeven_r: float | None = None

    @property
    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.exit_time is not None]

    def summary(self) -> dict:
        closed = self.closed_trades
        wins = [t for t in closed if (t.pnl_quote or 0) > 0]
        losses = [t for t in closed if (t.pnl_quote or 0) <= 0]
        pnl = sum(t.pnl_quote or 0.0 for t in closed)
        fees = sum(t.fees_quote for t in self.trades)
        slip = sum(t.slippage_quote for t in self.trades)
        win_rate = (len(wins) / len(closed) * 100.0) if closed else 0.0
        first = last = None
        if self.equity_curve is not None and not self.equity_curve.empty:
            first = str(self.equity_curve.index[0])
            last = str(self.equity_curve.index[-1])
        impact = None
        if self.zero_cost_end_equity is not None:
            impact = self.zero_cost_end_equity - self.end_equity
        return {
            "source": self.source,
            "entry_timeframe": self.entry_timeframe,
            "trend_timeframe": self.trend_timeframe,
            "stop_atr_mult": self.stop_atr_mult,
            "tp_atr_mult": self.tp_atr_mult,
            "reward_risk": round(self.tp_atr_mult / self.stop_atr_mult, 4)
            if self.stop_atr_mult
            else None,
            "bars": int(len(self.equity_curve)) if self.equity_curve is not None else 0,
            "first_bar": first,
            "last_bar": last,
            "trades": len(closed),
            "open_at_end": sum(1 for t in self.trades if t.exit_time is None),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "pnl_usdt": round(pnl, 4),
            "fees_usdt": round(fees, 4),
            "slippage_usdt": round(slip, 4),
            "max_drawdown_pct": round(max_drawdown_pct(self.equity_curve) * 100.0, 4),
            "start_capital": round(self.start_capital, 4),
            "end_equity": round(self.end_equity, 4),
            "return_pct": round((self.end_equity / self.start_capital - 1.0) * 100.0, 4)
            if self.start_capital
            else 0.0,
            "zero_cost_end_equity": None
            if self.zero_cost_end_equity is None
            else round(self.zero_cost_end_equity, 4),
            "fees_slippage_impact_usdt": None if impact is None else round(impact, 4),
            "halt_events": list(self.halt_events),
            "session": self.session_label,
            "profile": self.profile,
        }


def max_drawdown_pct(equity: pd.Series | None) -> float:
    """Peak-to-trough drawdown as a negative fraction (e.g. -0.12 = −12%)."""
    if equity is None or equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0.0, np.nan)
    value = float(dd.min())
    return value if value == value else 0.0


def apply_buy_slippage(price: float, slippage_rate: float) -> float:
    return price * (1.0 + slippage_rate)


def apply_sell_slippage(price: float, slippage_rate: float) -> float:
    return price * (1.0 - slippage_rate)


def _as_utc_ts(ts: pd.Timestamp | datetime) -> datetime:
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.to_pydatetime()


def run_backtest(
    ohlcv_1h: pd.DataFrame,
    settings: Settings | None = None,
    calendar: EventCalendar | None = None,
    *,
    source: str = "unknown",
    compare_zero_cost: bool = False,
    entry_timeframe: str = "1h",
    trend_timeframe: str = "4h",
    stop_atr_mult: float = 1.5,
    tp_atr_mult: float = 2.0,
    session: SessionWindow | None = None,
    profile: str = "default",
    entry_from: pd.Timestamp | None = None,
    entry_until: pd.Timestamp | None = None,
    extra: ExtraFilters | None = None,
    breakeven_r: float | None = None,
) -> BacktestResult:
    settings = settings or load_settings()
    calendar = calendar if calendar is not None else calendar_from_settings(settings)
    frame = attach_indicators(ohlcv_1h, trend_timeframe=trend_timeframe)
    if entry_from is not None:
        entry_from = pd.Timestamp(entry_from)
        entry_from = entry_from.tz_localize("UTC") if entry_from.tzinfo is None else entry_from.tz_convert("UTC")
    if entry_until is not None:
        entry_until = pd.Timestamp(entry_until)
        entry_until = entry_until.tz_localize("UTC") if entry_until.tzinfo is None else entry_until.tz_convert("UTC")

    cash = float(settings.capital_eur)  # USDT treated 1:1 with EUR by default
    qty = 0.0
    position: Trade | None = None
    pending_entry: dict | None = None
    dd = MonthlyDrawdownGuard(threshold=settings.monthly_dd_halt)
    result = BacktestResult(
        start_capital=cash,
        source=source,
        entry_timeframe=entry_timeframe,
        trend_timeframe=trend_timeframe,
        stop_atr_mult=stop_atr_mult,
        tp_atr_mult=tp_atr_mult,
        session_label=session.label if session is not None else None,
        profile=profile,
        extra_filters=extra or ExtraFilters(),
        breakeven_r=breakeven_r,
    )
    equity_points: list[tuple[pd.Timestamp, float]] = []

    fee = settings.fee_rate
    slip = settings.slippage_rate

    for i in range(len(frame)):
        row = frame.iloc[i]
        ts = frame.index[i]
        mark = float(row["close"])
        equity = cash + qty * mark
        equity_points.append((ts, equity))
        halted = dd.update(_as_utc_ts(ts), equity)
        if halted and dd.reason and dd.reason not in result.halt_events:
            result.halt_events.append(dd.reason)

        # Fill a signal from the previous closed bar at this bar's open.
        if pending_entry is not None and position is None:
            raw_entry = float(row["open"])
            fill = apply_buy_slippage(raw_entry, slip)
            stop = float(pending_entry["stop_fn"](fill))
            take = float(pending_entry["tp_fn"](fill))
            trade_qty = size_from_settings(
                settings,
                entry_price=fill,
                stop=stop,
                capital_eur=equity,
                available_quote=cash,
            )
            if trade_qty > 0:
                entry_fee = fill * trade_qty * fee
                entry_slip = (fill - raw_entry) * trade_qty
                cash -= fill * trade_qty + entry_fee
                qty = trade_qty
                position = Trade(
                    signal_time=pending_entry["signal_time"],
                    entry_time=ts,
                    exit_time=None,
                    entry_price=fill,
                    exit_price=None,
                    qty=trade_qty,
                    stop=stop,
                    initial_stop=stop,
                    take_profit=take,
                    reason_entry=pending_entry["reason"],
                    fees_quote=entry_fee,
                    slippage_quote=entry_slip,
                )
                result.trades.append(position)
            pending_entry = None

        # Manage open position on this bar (conservative: stop before TP).
        if position is not None and position.exit_time is None:
            low = float(row["low"])
            high = float(row["high"])
            if breakeven_r is not None and breakeven_r > 0:
                risk = position.entry_price - position.initial_stop
                if risk > 0 and high >= position.entry_price + breakeven_r * risk:
                    # Cost-aware BE: cover round-trip fee + slippage so a BE stop is ~flat.
                    be = position.entry_price * (1.0 + 2.0 * fee + 2.0 * slip)
                    if be > position.stop:
                        position.stop = be
            exit_px: float | None = None
            reason_exit: str | None = None
            if low <= position.stop:
                raw_exit = position.stop
                exit_px = apply_sell_slippage(raw_exit, slip)
                reason_exit = "stop"
            elif high >= position.take_profit:
                raw_exit = position.take_profit
                exit_px = apply_sell_slippage(raw_exit, slip)
                reason_exit = "take-profit"
            else:
                raw_exit = None
            if exit_px is not None and raw_exit is not None:
                exit_fee = exit_px * position.qty * fee
                exit_slip = (raw_exit - exit_px) * position.qty
                cash += exit_px * position.qty - exit_fee
                position.exit_time = ts
                position.exit_price = exit_px
                position.reason_exit = reason_exit
                position.fees_quote += exit_fee
                position.slippage_quote += exit_slip
                position.pnl_quote = (
                    (exit_px - position.entry_price) * position.qty - position.fees_quote
                )
                qty = 0.0
                position = None

        has_open = position is not None and position.exit_time is None
        event_reason = calendar.pause_reason(_as_utc_ts(ts).date())
        paused = bool(dd.halted or event_reason)
        pause_reason = dd.reason if dd.halted else event_reason

        ema = row["ema200_4h"]
        rsi_v = row["rsi_14"]
        rsi_p = row["rsi_14_prev"]
        vol_ma = row["volume_ma20"]
        atr_v = row["atr_14"]

        in_entry_span = True
        if entry_from is not None and ts < pd.Timestamp(entry_from):
            in_entry_span = False
        if entry_until is not None and ts >= pd.Timestamp(entry_until):
            in_entry_span = False
        session_ok = in_entry_span and session_allows_signal(ts, entry_timeframe, session)

        ema_prev = row["ema200_prev"] if "ema200_prev" in frame.columns else None
        atr_pct = row["atr_pct"] if "atr_pct" in frame.columns else None
        atr_q = row["atr_pct_q25"] if "atr_pct_q25" in frame.columns else None
        decision = evaluate_entry(
            price=mark,
            ema200_4h=None if pd.isna(ema) else float(ema),
            rsi_value=None if pd.isna(rsi_v) else float(rsi_v),
            prev_rsi=None if pd.isna(rsi_p) else float(rsi_p),
            volume=float(row["volume"]),
            volume_ma=None if pd.isna(vol_ma) else float(vol_ma),
            has_open_position=has_open or pending_entry is not None,
            paused=paused,
            pause_reason=pause_reason,
            session_ok=session_ok,
            extra=extra,
            ema200_prev=None if ema_prev is None or pd.isna(ema_prev) else float(ema_prev),
            atr_pct=None if atr_pct is None or pd.isna(atr_pct) else float(atr_pct),
            atr_pct_q25=None if atr_q is None or pd.isna(atr_q) else float(atr_q),
        )
        if i % max(len(frame) // 8, 1) == 0 or decision.enter:
            result.decisions_sampled.append((ts, decision))

        if (
            decision.enter
            and pending_entry is None
            and not has_open
            and i + 1 < len(frame)
            and not pd.isna(atr_v)
            and float(atr_v) > 0
        ):
            atr_signal = float(atr_v)
            pending_entry = {
                "signal_time": ts,
                "reason": decision.reason,
                "stop_fn": lambda fill, a=atr_signal: stop_price(
                    fill, a, atr_mult=stop_atr_mult
                ),
                "tp_fn": lambda fill, a=atr_signal: take_profit_price(
                    fill, a, atr_mult=tp_atr_mult
                ),
            }

    # Mark-to-market open position at the last close (not a forced exit).
    last_close = float(frame["close"].iloc[-1])
    result.end_equity = cash + qty * last_close
    result.equity_curve = pd.Series(
        {t: e for t, e in equity_points},
        name="equity",
    )
    if compare_zero_cost and (settings.fee_bps or settings.slippage_bps):
        baseline = run_backtest(
            ohlcv_1h,
            replace(settings, fee_bps=0.0, slippage_bps=0.0),
            calendar,
            source=source,
            compare_zero_cost=False,
            entry_timeframe=entry_timeframe,
            trend_timeframe=trend_timeframe,
            stop_atr_mult=stop_atr_mult,
            tp_atr_mult=tp_atr_mult,
            session=session,
            profile=profile,
            entry_from=entry_from,
            entry_until=entry_until,
            extra=extra,
            breakeven_r=breakeven_r,
        )
        result.zero_cost_end_equity = baseline.end_equity
    return result


def format_report(result: BacktestResult) -> str:
    s = result.summary()
    lines = [
        "Alicia backtest — BTC/USDT spot, LONG only",
        f"  source:        {s['source']}",
        f"  timeframes:    entry {s['entry_timeframe']} / trend EMA200 {s['trend_timeframe']}",
        f"  stop / TP:     {s['stop_atr_mult']:g}×ATR / {s['tp_atr_mult']:g}×ATR "
        f"(RR 1:{s['reward_risk']:g})",
        f"  profile:       {s['profile']}"
        + (f"  session {s['session']}" if s["session"] else "  session 24/7 (product)"),
        f"  bars:          {s['bars']}  ({s['first_bar']} → {s['last_bar']})",
        f"  trades:        {s['trades']}  (open at end: {s['open_at_end']})",
        f"  wins/losses:   {s['wins']}/{s['losses']}  (win rate {s['win_rate_pct']:.2f}%)",
        f"  start capital: {s['start_capital']:.2f}",
        f"  end equity:    {s['end_equity']:.2f}",
        f"  return:        {s['return_pct']:.2f}%",
        f"  max drawdown:  {s['max_drawdown_pct']:.2f}%",
        f"  closed PnL:    {s['pnl_usdt']:.2f} USDT (fees+slippage included)",
        f"  fees:          {s['fees_usdt']:.2f} USDT",
        f"  slippage:      {s['slippage_usdt']:.2f} USDT",
        "  order book:    skipped — no historical L2 (paper/live apply spread/imbalance/depth)",
    ]
    if s["fees_slippage_impact_usdt"] is not None:
        lines.append(
            f"  cost impact:   {s['fees_slippage_impact_usdt']:.2f} USDT "
            f"(zero-cost equity {s['zero_cost_end_equity']:.2f} vs {s['end_equity']:.2f})"
        )
    if s["halt_events"]:
        lines.append("  halt events:")
        for ev in s["halt_events"]:
            lines.append(f"    - {ev}")
    if result.trades:
        lines.append("  last trades:")
        for trade in result.trades[-5:]:
            exit_bit = (
                f"exit {trade.exit_price:.2f} ({trade.reason_exit})"
                if trade.exit_price is not None
                else "OPEN"
            )
            pnl_bit = f" pnl={trade.pnl_quote:.2f}" if trade.pnl_quote is not None else ""
            lines.append(
                f"    {trade.entry_time} qty={trade.qty:.6f} "
                f"in={trade.entry_price:.2f} {exit_bit}{pnl_bit}"
            )
    return "\n".join(lines)
