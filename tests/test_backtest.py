from __future__ import annotations

import pandas as pd

from alicia.backtest import apply_buy_slippage, apply_sell_slippage, run_backtest
from alicia.calendar import EventCalendar, MacroEvent
from alicia.cli import main
from alicia.indicators import attach_indicators
from alicia.risk import size_from_settings
from alicia.sample_data import generate_sample_ohlcv
from alicia.strategy import evaluate_entry


def test_sample_series_produces_trades_after_ema_warmup(settings):
    result = run_backtest(generate_sample_ohlcv(), settings)
    assert result.closed_trades, "synthetic series should demonstrate at least one full trade"
    first = result.trades[0]
    # 200 × 4h warmup from 2024-01-01 → first valid trend date is early February
    assert first.signal_time >= pd.Timestamp("2024-02-03", tz="UTC")


def test_slippage_is_adverse():
    assert apply_buy_slippage(100.0, 0.001) == 100.1
    assert apply_sell_slippage(100.0, 0.001) == 99.9


def test_backtest_never_has_overlapping_positions(settings):
    result = run_backtest(generate_sample_ohlcv(), settings)
    open_intervals: list[tuple] = []
    for trade in result.trades:
        end = trade.exit_time or result.equity_curve.index[-1]
        for start, stop in open_intervals:
            overlap = trade.entry_time < stop and start < end
            assert not overlap, "max one open position / no averaging down"
        open_intervals.append((trade.entry_time, end))


def test_backtest_fees_are_deducted_on_closed_trades(settings):
    result = run_backtest(generate_sample_ohlcv(), settings)
    for trade in result.closed_trades:
        assert trade.fees_quote > 0
        raw = (trade.exit_price - trade.entry_price) * trade.qty
        assert abs((raw - trade.fees_quote) - (trade.pnl_quote or 0.0)) < 1e-6


def test_entry_fill_uses_next_bar_open_plus_slippage(settings):
    """If a signal exists, the fill price must be next open * (1+slip), not the signal close."""
    ohlcv = generate_sample_ohlcv()
    result = run_backtest(ohlcv, settings)
    if not result.trades:
        return
    frame = ohlcv.copy()
    for trade in result.trades:
        nxt = frame.index[frame.index.get_loc(trade.signal_time) + 1]
        assert trade.entry_time == nxt
        expected = apply_buy_slippage(float(frame.loc[nxt, "open"]), settings.slippage_rate)
        assert abs(trade.entry_price - expected) < 1e-6


def test_sizing_matches_risk_module(settings):
    qty = size_from_settings(settings, entry_price=60_000.0, stop=59_100.0, capital_eur=2_000.0)
    assert qty > 0
    risk = qty * (60_000.0 - 59_100.0)
    assert abs(risk - 2_000.0 * settings.risk_pct_clamped) < 1e-6


def test_event_day_blocks_new_entries(settings):
    ohlcv = generate_sample_ohlcv()
    frame = attach_indicators(ohlcv)
    # Find a bar that would otherwise be a valid signal, if any.
    hits = []
    for ts, row in frame.iterrows():
        d = evaluate_entry(
            price=float(row["close"]),
            ema200_4h=None if pd.isna(row["ema200_4h"]) else float(row["ema200_4h"]),
            rsi_value=None if pd.isna(row["rsi_14"]) else float(row["rsi_14"]),
            prev_rsi=None if pd.isna(row["rsi_14_prev"]) else float(row["rsi_14_prev"]),
            volume=float(row["volume"]),
            volume_ma=None if pd.isna(row["volume_ma20"]) else float(row["volume_ma20"]),
            has_open_position=False,
        )
        if d.enter:
            hits.append(ts.date())
            break
    if not hits:
        return
    cal = EventCalendar(
        events=(MacroEvent(hits[0], "cpi", "US CPI"),),
        pause_cpi=True,
        pause_fed=False,
        pause_nfp=False,
    )
    blocked = run_backtest(ohlcv, settings, calendar=cal)
    entered_that_day = [
        t for t in blocked.trades if t.signal_time.tz_convert("UTC").date() == hits[0]
    ]
    assert entered_that_day == []


def test_cli_dry_run_without_keys(capsys):
    code = main(["dry-run"])
    captured = capsys.readouterr()
    assert code == 0
    assert "keys were not used" in captured.out.lower() or "Dry-run complete" in captured.out
    assert "EXCHANGE_API" not in captured.out
