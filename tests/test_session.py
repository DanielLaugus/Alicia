import pandas as pd

from alicia.cli import main
from alicia.indicators import resample_ohlcv
from alicia.sample_data import generate_sample_ohlcv
from alicia.session import (
    US_PRIMARY,
    bar_close_time,
    parse_hhmm,
    session_allows_signal,
)
from alicia.strategy import evaluate_entry


def test_parse_hhmm():
    assert parse_hhmm("13:30") == 13 * 60 + 30
    assert parse_hhmm("20:00") == 20 * 60


def test_primary_window_uses_bar_close_not_open():
    # 2h bar 12:00–14:00 closes at 14:00 → inside 13:30–20:00.
    open_ts = pd.Timestamp("2026-03-16 12:00", tz="UTC")  # Monday
    assert bar_close_time(open_ts, "2h") == pd.Timestamp("2026-03-16 14:00", tz="UTC")
    assert session_allows_signal(open_ts, "2h", US_PRIMARY)
    # 2h bar 10:00–12:00 closes 12:00 → before NY cash open.
    early = pd.Timestamp("2026-03-16 10:00", tz="UTC")
    assert not session_allows_signal(early, "2h", US_PRIMARY)
    # Close exactly 20:00 is included.
    last = pd.Timestamp("2026-03-16 18:00", tz="UTC")
    assert session_allows_signal(last, "2h", US_PRIMARY)
    after = pd.Timestamp("2026-03-16 20:00", tz="UTC")
    assert not session_allows_signal(after, "2h", US_PRIMARY)


def test_weekdays_only_blocks_saturday():
    sat = pd.Timestamp("2026-03-14 14:00", tz="UTC")  # Saturday 12:00–14:00 2h
    assert sat.weekday() == 5
    assert not session_allows_signal(sat, "2h", US_PRIMARY)


def test_evaluate_entry_blocks_outside_session():
    decision = evaluate_entry(
        price=70_000.0,
        ema200_4h=65_000.0,
        rsi_value=41.0,
        prev_rsi=39.0,
        volume=200.0,
        volume_ma=100.0,
        has_open_position=False,
        session_ok=False,
    )
    assert not decision.enter
    assert "session" in decision.reason.lower()


def test_us_session_backtest_has_no_off_hours_signals(settings):
    from alicia.backtest import run_backtest

    hourly = generate_sample_ohlcv(n_1h=4200, seed=11)
    bars = resample_ohlcv(hourly, "2h")
    result = run_backtest(
        bars,
        settings,
        entry_timeframe="2h",
        trend_timeframe="8h",
        stop_atr_mult=1.5,
        tp_atr_mult=3.0,
        session=US_PRIMARY,
        profile="us-session",
    )
    for trade in result.trades:
        assert session_allows_signal(trade.signal_time, "2h", US_PRIMARY)


def test_cli_default_backtest_is_not_us_session(capsys):
    code = main(["backtest", "--synthetic", "--no-cost-compare"])
    captured = capsys.readouterr()
    assert code == 0
    assert "EXPERIMENT" not in captured.out
    assert "entry 1h / trend EMA200 4h" in captured.out
    assert "session 24/7" in captured.out


def test_cli_us_session_profile_banner(capsys):
    code = main(["backtest", "--synthetic", "--profile", "us-session", "--no-cost-compare"])
    captured = capsys.readouterr()
    assert code == 0
    assert "EXPERIMENT" in captured.out
    assert "profile=us-session" in captured.out
    assert "2h entry" in captured.out
    assert "8h EMA200" in captured.out
    assert "13:30" in captured.out
    assert "20:00" in captured.out
    assert "3×ATR" in captured.out or "3.0×ATR" in captured.out
