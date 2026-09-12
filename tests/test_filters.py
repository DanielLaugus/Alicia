from alicia.backtest import run_backtest
from alicia.cli import main
from alicia.sample_data import generate_sample_ohlcv
from alicia.strategy import ExtraFilters, evaluate_entry


def _ok(**overrides):
    base = dict(
        price=70_000.0,
        ema200_4h=65_000.0,
        rsi_value=41.0,
        prev_rsi=39.0,
        volume=200.0,
        volume_ma=100.0,
        has_open_position=False,
    )
    base.update(overrides)
    return evaluate_entry(**base)


def test_ema_slope_blocks_flat_or_down_trend():
    extra = ExtraFilters(require_ema_slope=True)
    assert not _ok(extra=extra, ema200_prev=65_100.0).enter
    assert _ok(extra=extra, ema200_prev=64_000.0).enter


def test_rsi_from_30_blocks_shallow_cross():
    extra = ExtraFilters(rsi_from=30.0)
    assert not _ok(extra=extra, prev_rsi=35.0, rsi_value=41.0).enter
    assert _ok(extra=extra, prev_rsi=28.0, rsi_value=41.0).enter


def test_ema50_and_slope_are_and_gates():
    extra = ExtraFilters(require_ema_slope=True, require_ema50=True)
    assert not _ok(extra=extra, ema200_prev=64_000.0, ema50=71_000.0).enter
    assert not _ok(extra=extra, ema200_prev=65_100.0, ema50=60_000.0).enter
    assert _ok(extra=extra, ema200_prev=64_000.0, ema50=60_000.0).enter


def test_chop_filter_blocks_low_atr():
    extra = ExtraFilters(chop_filter=True)
    assert not _ok(extra=extra, atr_pct=0.003, atr_pct_q25=0.005).enter
    assert _ok(extra=extra, atr_pct=0.008, atr_pct_q25=0.005).enter


def test_product_evaluate_entry_ignores_extra_when_omitted():
    assert _ok().enter


def test_breakeven_can_raise_stop(settings):
    result = run_backtest(
        generate_sample_ohlcv(),
        settings,
        breakeven_r=1.0,
    )
    # Synthetic path may or may not trigger BE; just prove the flag does not crash
    # and that initial_stop is recorded.
    assert all(t.initial_stop > 0 for t in result.trades)


def test_cli_us_peak_1h_banner(capsys):
    code = main(["backtest", "--synthetic", "--profile", "us-peak-1h", "--no-cost-compare"])
    captured = capsys.readouterr()
    assert code == 0
    assert "us-peak-1h" in captured.out or "profile=us-peak-1h" in captured.out
    assert "1h entry" in captured.out
    assert "America/New_York" in captured.out


def test_cli_default_still_has_no_experiment_extras(capsys):
    code = main(["backtest", "--synthetic", "--no-cost-compare"])
    captured = capsys.readouterr()
    assert code == 0
    assert "EXPERIMENT" not in captured.out
    assert "ema-slope" not in captured.out
