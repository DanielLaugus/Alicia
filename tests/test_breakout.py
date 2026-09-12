import pandas as pd

from alicia.backtest import run_backtest
from alicia.cli import main
from alicia.indicators import attach_indicators, donchian_prior_high
from alicia.sample_data import generate_sample_ohlcv
from alicia.session import PROFILES, US_PEAK
from alicia.strategy import (
    decide_entry,
    donchian_breakout_cross,
    ema_reclaim_after_pullback,
    evaluate_breakout,
    evaluate_entry,
    stop_from_mode,
    stop_price,
)


def _breakout_ok(**overrides):
    base = dict(
        price=70_100.0,
        ema200_4h=65_000.0,
        prev_close=69_000.0,
        donchian_high=70_000.0,
        has_open_position=False,
    )
    base.update(overrides)
    return evaluate_breakout(**base)


def test_donchian_prior_high_excludes_current_bar():
    high = pd.Series([1.0, 2.0, 3.0, 4.0, 10.0])
    prior = donchian_prior_high(high, 3)
    assert pd.isna(prior.iloc[2])
    assert prior.iloc[3] == 3.0  # max(1,2,3), not 4
    assert prior.iloc[4] == 4.0  # max(2,3,4), not the current 10


def test_donchian_no_lookahead_when_last_high_changes():
    idx = pd.date_range("2024-01-01", periods=40, freq="1h", tz="UTC")
    high = pd.Series([float(i + 1) for i in range(40)], index=idx)
    a = donchian_prior_high(high, 20)
    high_b = high.copy()
    high_b.iloc[-1] = 1_000_000.0
    b = donchian_prior_high(high_b, 20)
    pd.testing.assert_series_equal(a, b)


def test_attach_donchian_ignores_current_bar_high():
    df = generate_sample_ohlcv(n_1h=900, seed=2)
    a = attach_indicators(df)
    b_src = df.copy()
    b_src.iloc[-1, b_src.columns.get_loc("high")] = float(b_src.iloc[-1]["high"]) * 5
    b = attach_indicators(b_src)
    pd.testing.assert_series_equal(a["donchian_high"], b["donchian_high"], check_names=False)
    assert "ema20" in a.columns
    assert "close_prev" in a.columns


def test_donchian_cross_definition():
    assert donchian_breakout_cross(101.0, 99.0, 100.0)
    assert not donchian_breakout_cross(100.0, 99.0, 100.0)  # must be strictly above
    assert not donchian_breakout_cross(102.0, 101.0, 100.0)  # already above — not a cross
    assert not donchian_breakout_cross(99.0, 98.0, 100.0)


def test_breakout_enters_on_channel_cross_above_ema200():
    decision = _breakout_ok()
    assert decision.enter
    assert "Donchian" in decision.reason


def test_breakout_blocks_without_cross():
    decision = _breakout_ok(price=69_500.0, prev_close=69_000.0, donchian_high=70_000.0)
    assert not decision.enter
    assert "did not break" in decision.reason


def test_breakout_blocks_when_already_above_channel():
    decision = _breakout_ok(price=71_000.0, prev_close=70_500.0, donchian_high=70_000.0)
    assert not decision.enter


def test_breakout_blocks_below_ema200_even_on_cross():
    decision = _breakout_ok(price=64_000.0, ema200_4h=65_000.0, donchian_high=63_000.0)
    assert not decision.enter
    assert "EMA200" in decision.reason


def test_breakout_does_not_require_rsi_or_volume():
    # A bar that fails the product RSI rule can still be a Donchian LONG.
    rsi = evaluate_entry(
        price=70_100.0,
        ema200_4h=65_000.0,
        rsi_value=55.0,
        prev_rsi=54.0,
        volume=10.0,
        volume_ma=100.0,
        has_open_position=False,
    )
    assert not rsi.enter
    brk = _breakout_ok()
    assert brk.enter


def test_breakout_reuses_session_and_one_position_gates():
    assert not _breakout_ok(session_ok=False).enter
    assert not _breakout_ok(has_open_position=True).enter
    paused = _breakout_ok(paused=True, pause_reason="monthly drawdown")
    assert not paused.enter
    assert "monthly drawdown" in paused.reason


def test_pullback_reclaim_definition():
    assert ema_reclaim_after_pullback(100.0, 98.0, 99.0)
    assert not ema_reclaim_after_pullback(100.0, 99.5, 99.0)  # never went below
    assert not ema_reclaim_after_pullback(98.0, 97.0, 99.0)


def test_decide_entry_dispatches_families():
    rsi = decide_entry(
        "rsi",
        price=70_000.0,
        ema200_4h=65_000.0,
        rsi_value=41.0,
        prev_rsi=39.0,
        volume=200.0,
        volume_ma=100.0,
        has_open_position=False,
    )
    assert rsi.enter
    brk = decide_entry(
        "breakout",
        price=70_100.0,
        ema200_4h=65_000.0,
        has_open_position=False,
        prev_close=69_000.0,
        donchian_high=70_000.0,
    )
    assert brk.enter
    pb = decide_entry(
        "pullback",
        price=70_000.0,
        ema200_4h=65_000.0,
        has_open_position=False,
        prev_close=68_000.0,
        ema20=69_000.0,
    )
    assert pb.enter


def test_stop_from_mode_bar_low_and_atr_fallback():
    atr_stop = stop_price(50_000.0, 1_000.0)
    assert stop_from_mode(50_000.0, 1_000.0, mode="atr") == atr_stop
    assert stop_from_mode(50_000.0, 1_000.0, signal_low=49_200.0, mode="bar-low") == 49_200.0
    # Gap-up: bar low at/above fill → ATR fallback
    assert stop_from_mode(50_000.0, 1_000.0, signal_low=50_100.0, mode="bar-low") == atr_stop


def test_breakout_profiles_do_not_replace_default():
    assert PROFILES["default"].signal == "rsi"
    assert PROFILES["default"].entry_timeframe == "1h"
    assert PROFILES["breakout"].signal == "breakout"
    assert PROFILES["breakout"].entry_timeframe == "4h"
    assert PROFILES["breakout"].session is None
    assert PROFILES["breakout-us"].session == US_PEAK
    assert PROFILES["breakout-trail"].trail_atr == 1.5


def test_default_backtest_matches_explicit_rsi_signal(settings):
    ohlcv = generate_sample_ohlcv()
    product = run_backtest(ohlcv, settings)
    explicit = run_backtest(ohlcv, settings, signal="rsi")
    assert product.signal == "rsi"
    assert len(product.closed_trades) == len(explicit.closed_trades)
    assert [t.entry_time for t in product.trades] == [t.entry_time for t in explicit.trades]


def test_breakout_backtest_runs_and_stays_one_position(settings):
    result = run_backtest(
        generate_sample_ohlcv(n_1h=4200, seed=11),
        settings,
        signal="breakout",
        entry_timeframe="1h",
        trend_timeframe="4h",
        stop_atr_mult=1.5,
        tp_atr_mult=3.0,
    )
    assert result.signal == "breakout"
    open_intervals: list[tuple] = []
    for trade in result.trades:
        end = trade.exit_time or result.equity_curve.index[-1]
        for start, stop in open_intervals:
            assert not (trade.entry_time < stop and start < end)
        open_intervals.append((trade.entry_time, end))
        assert "Donchian" in trade.reason_entry


def test_cli_default_is_still_rsi_not_breakout(capsys):
    code = main(["backtest", "--synthetic", "--no-cost-compare"])
    captured = capsys.readouterr()
    assert code == 0
    assert "EXPERIMENT" not in captured.out
    assert "Donchian" not in captured.out
    assert "signal:        rsi" in captured.out


def test_cli_breakout_profile_banner(capsys):
    code = main(["backtest", "--synthetic", "--profile", "breakout", "--no-cost-compare"])
    captured = capsys.readouterr()
    assert code == 0
    assert "EXPERIMENT" in captured.out
    assert "profile=breakout" in captured.out
    assert "4h entry" in captured.out
    assert "signal breakout" in captured.out
    assert "Donchian 20" in captured.out


def test_cli_breakout_us_uses_ny_peak(capsys):
    code = main(["backtest", "--synthetic", "--profile", "breakout-us", "--no-cost-compare"])
    captured = capsys.readouterr()
    assert code == 0
    assert "America/New_York" in captured.out
    assert "09:00" in captured.out
