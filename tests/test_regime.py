import pandas as pd

from alicia.cli import main
from alicia.indicators import adx, attach_indicators, donchian_prior_low
from alicia.sample_data import generate_sample_ohlcv
from alicia.session import PROFILES
from alicia.strategy import (
    ExtraFilters,
    decide_entry,
    donchian_breakdown_cross,
    evaluate_breakout,
    rsi_crosses_down_through,
)


def test_adx_is_nan_until_warmup():
    idx = pd.date_range("2024-01-01", periods=20, freq="1h", tz="UTC")
    close = pd.Series(range(20), index=idx, dtype="float64") + 100.0
    high, low = close + 1, close - 1
    value, plus_di, minus_di = adx(high, low, close, 14)
    assert value.isna().iloc[:13].all()
    assert plus_di.notna().iloc[-1]


def test_donchian_low_excludes_current_bar():
    low = pd.Series([10.0, 9.0, 8.0, 7.0, 1.0])
    prior = donchian_prior_low(low, 3)
    assert pd.isna(prior.iloc[2])
    assert prior.iloc[3] == 8.0
    assert prior.iloc[4] == 7.0  # current 1 is excluded


def test_breakdown_cross_definition():
    assert donchian_breakdown_cross(99.0, 101.0, 100.0)
    assert not donchian_breakdown_cross(100.0, 101.0, 100.0)
    assert not donchian_breakdown_cross(98.0, 99.0, 100.0)


def test_rsi_cross_down():
    assert rsi_crosses_down_through(61.0, 59.0)
    assert not rsi_crosses_down_through(60.0, 59.0)


def test_adx_min_blocks_breakout_in_range():
    extra = ExtraFilters(adx_min=25.0)
    blocked = evaluate_breakout(
        price=70_100.0,
        ema200_4h=65_000.0,
        prev_close=69_000.0,
        donchian_high=70_000.0,
        has_open_position=False,
        extra=extra,
        adx=18.0,
    )
    assert not blocked.enter
    allowed = evaluate_breakout(
        price=70_100.0,
        ema200_4h=65_000.0,
        prev_close=69_000.0,
        donchian_high=70_000.0,
        has_open_position=False,
        extra=extra,
        adx=30.0,
    )
    assert allowed.enter


def test_regime_switches_to_breakout_when_adx_high():
    extra = ExtraFilters(adx_split=25.0)
    # RSI would fail (no cross); breakout would pass.
    decision = decide_entry(
        "regime",
        price=70_100.0,
        ema200_4h=65_000.0,
        has_open_position=False,
        extra=extra,
        rsi_value=55.0,
        prev_rsi=54.0,
        volume=10.0,
        volume_ma=100.0,
        prev_close=69_000.0,
        donchian_high=70_000.0,
        adx=30.0,
    )
    assert decision.enter
    assert "Donchian" in decision.reason


def test_regime_uses_rsi_when_adx_low():
    extra = ExtraFilters(adx_split=25.0)
    decision = decide_entry(
        "regime",
        price=70_000.0,
        ema200_4h=65_000.0,
        has_open_position=False,
        extra=extra,
        rsi_value=41.0,
        prev_rsi=39.0,
        volume=200.0,
        volume_ma=100.0,
        prev_close=69_000.0,
        donchian_high=80_000.0,
        adx=15.0,
    )
    assert decision.enter
    assert "RSI" in decision.reason


def test_short_breakout_requires_price_below_ema():
    extra = ExtraFilters()
    blocked = evaluate_breakout(
        price=70_000.0,
        ema200_4h=65_000.0,
        prev_close=71_000.0,
        donchian_high=80_000.0,
        donchian_low=70_500.0,
        has_open_position=False,
        extra=extra,
        side="short",
    )
    assert not blocked.enter
    allowed = evaluate_breakout(
        price=64_000.0,
        ema200_4h=65_000.0,
        prev_close=66_000.0,
        donchian_high=80_000.0,
        donchian_low=65_000.0,
        has_open_position=False,
        extra=extra,
        side="short",
    )
    assert allowed.enter
    assert "SHORT" in allowed.reason


def test_product_default_profile_stays_rsi_long():
    assert PROFILES["default"].signal == "rsi"
    assert PROFILES["default"].side == "long"
    assert PROFILES["regime"].signal == "regime"


def test_attach_adds_adx_columns():
    frame = attach_indicators(generate_sample_ohlcv(n_1h=900, seed=3))
    assert "adx_14" in frame.columns
    assert "donchian_low" in frame.columns
    assert frame["adx_14"].dropna().ge(0).all()


def test_cli_regime_banner(capsys):
    code = main(["backtest", "--synthetic", "--profile", "regime", "--no-cost-compare"])
    captured = capsys.readouterr()
    assert code == 0
    assert "EXPERIMENT" in captured.out
    assert "signal regime" in captured.out
    assert "EXPERIMENT" in captured.out


def test_cli_default_still_unmarked(capsys):
    code = main(["backtest", "--synthetic", "--no-cost-compare"])
    captured = capsys.readouterr()
    assert code == 0
    assert "EXPERIMENT" not in captured.out
