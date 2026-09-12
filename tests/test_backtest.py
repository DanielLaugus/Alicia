from __future__ import annotations

import pandas as pd

from alicia.backtest import (
    apply_buy_slippage,
    apply_sell_slippage,
    max_drawdown_pct,
    run_backtest,
)
from alicia.calendar import EventCalendar, MacroEvent
from alicia.cli import main
from alicia.cli import _atr_multiples, _trend_tf
from alicia.indicators import attach_indicators, resample_ohlcv
from alicia.risk import size_from_settings
from alicia.sample_data import generate_sample_ohlcv
from alicia.strategy import evaluate_entry


def test_sample_series_produces_trades_after_ema_warmup(settings):
    result = run_backtest(generate_sample_ohlcv(), settings)
    assert result.closed_trades, "synthetic series should demonstrate at least one full trade"
    first = result.trades[0]
    # 200 × 4h warmup from 2024-01-01 → first valid trend date is early February
    assert first.signal_time >= pd.Timestamp("2024-02-03", tz="UTC")


def test_max_drawdown_from_peak():
    equity = pd.Series([100.0, 120.0, 108.0, 90.0, 95.0])
    assert abs(max_drawdown_pct(equity) - ((90.0 - 120.0) / 120.0)) < 1e-9


def test_closed_trades_record_positive_slippage_cost(settings):
    result = run_backtest(generate_sample_ohlcv(), settings)
    closed = result.closed_trades
    assert closed
    assert all(t.slippage_quote > 0 for t in closed)
    s = result.summary()
    assert s["win_rate_pct"] >= 0
    assert s["max_drawdown_pct"] <= 0


def test_zero_cost_compare_shows_cost_impact(settings):
    result = run_backtest(generate_sample_ohlcv(), settings, compare_zero_cost=True)
    assert result.zero_cost_end_equity is not None
    assert result.zero_cost_end_equity >= result.end_equity - 1e-6


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
    assert "order-book filters were not applied" in captured.out.lower()
    assert "order book:    skipped" in captured.out


def test_cli_dry_run_book_fixture(capsys):
    code = main(["dry-run", "--book", "tests/fixtures/orderbook_pass.json"])
    captured = capsys.readouterr()
    assert code == 0
    assert "PASS" in captured.out
    assert "not historical" in captured.out


def test_cli_book_fixture_offline(capsys):
    code = main(["book", "--json", "tests/fixtures/orderbook_pass.json"])
    captured = capsys.readouterr()
    assert code == 0
    assert "gate:" in captured.out
    assert "PASS" in captured.out


def test_cli_backtest_without_cache_exits_cleanly(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = main(["backtest", "--cache-dir", str(tmp_path / "empty-cache")])
    captured = capsys.readouterr()
    assert code == 2
    assert "No cached OHLCV" in captured.err
    assert "download" in captured.err


def test_cli_backtest_synthetic(capsys):
    code = main(["backtest", "--synthetic", "--no-cost-compare"])
    captured = capsys.readouterr()
    assert code == 0
    assert "source:        synthetic" in captured.out
    assert "entry 1h / trend EMA200 4h" in captured.out
    assert "win rate" in captured.out
    assert "EXPERIMENT" not in captured.out
    assert "1.5×ATR / 2×ATR" in captured.out


def test_trend_tf_defaults_keep_product_and_experiments():
    assert _trend_tf("1h", None) == "4h"
    assert _trend_tf("1m", None) == "1h"
    assert _trend_tf("2h", None) == "8h"
    assert _trend_tf("4h", None) == "12h"
    assert _trend_tf("2h", "1d") == "1d"


def test_atr_multiples_default_and_reward_risk():
    from argparse import Namespace

    product = Namespace(stop_atr=None, tp_atr=None, reward_risk=None)
    assert _atr_multiples(product) == (1.5, 2.0)
    rr2 = Namespace(stop_atr=None, tp_atr=None, reward_risk=2.0)
    assert _atr_multiples(rr2) == (1.5, 3.0)
    explicit = Namespace(stop_atr=1.5, tp_atr=3.0, reward_risk=None)
    assert _atr_multiples(explicit) == (1.5, 3.0)


def test_2h_rr_experiment_stop_and_tp_are_1_to_2(settings):
    hourly = generate_sample_ohlcv(n_1h=4200, seed=11)
    bars_2h = resample_ohlcv(hourly, "2h")
    result = run_backtest(
        bars_2h,
        settings,
        entry_timeframe="2h",
        trend_timeframe="8h",
        stop_atr_mult=1.5,
        tp_atr_mult=3.0,
    )
    assert result.entry_timeframe == "2h"
    assert result.trend_timeframe == "8h"
    assert result.summary()["reward_risk"] == 2.0
    for trade in result.trades:
        risk = trade.entry_price - trade.stop
        reward = trade.take_profit - trade.entry_price
        assert risk > 0
        assert abs(reward / risk - 2.0) < 1e-9


def test_4h_rr_experiment_stop_and_tp_are_1_to_2(settings):
    hourly = generate_sample_ohlcv(n_1h=5200, seed=13)
    bars_4h = resample_ohlcv(hourly, "4h")
    result = run_backtest(
        bars_4h,
        settings,
        entry_timeframe="4h",
        trend_timeframe="12h",
        stop_atr_mult=1.5,
        tp_atr_mult=3.0,
    )
    assert result.entry_timeframe == "4h"
    assert result.trend_timeframe == "12h"
    assert result.summary()["reward_risk"] == 2.0
    for trade in result.trades:
        risk = trade.entry_price - trade.stop
        reward = trade.take_profit - trade.entry_price
        assert risk > 0
        assert abs(reward / risk - 2.0) < 1e-9


def test_cli_4h_reward_risk_experiment_banner(capsys):
    code = main(
        [
            "backtest",
            "--synthetic",
            "--timeframe",
            "4h",
            "--reward-risk",
            "2",
            "--no-cost-compare",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "EXPERIMENT" in captured.out
    assert "4h entry" in captured.out
    assert "12h EMA200" in captured.out
    assert "3×ATR" in captured.out or "3.0×ATR" in captured.out


def test_cli_2h_reward_risk_experiment_banner(capsys):
    code = main(
        [
            "backtest",
            "--synthetic",
            "--timeframe",
            "2h",
            "--reward-risk",
            "2",
            "--no-cost-compare",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "EXPERIMENT" in captured.out
    assert "2h entry" in captured.out
    assert "8h EMA200" in captured.out
    assert "3×ATR" in captured.out or "3.0×ATR" in captured.out
