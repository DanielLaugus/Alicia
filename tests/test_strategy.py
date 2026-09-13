from alicia.strategy import (
    RSI_CROSS_LEVEL,
    evaluate_entry,
    rsi_crosses_up_through,
    stop_price,
    take_profit_price,
    volume_above_average,
)


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


def test_rsi_cross_definition():
    assert rsi_crosses_up_through(39.9, 40.1)
    assert not rsi_crosses_up_through(40.0, 41.0)
    assert not rsi_crosses_up_through(39.0, 40.0)
    assert not rsi_crosses_up_through(41.0, 42.0)
    assert RSI_CROSS_LEVEL == 40.0


def test_volume_must_exceed_average():
    assert volume_above_average(101, 100)
    assert not volume_above_average(100, 100)
    assert not volume_above_average(50, 100)


def test_entry_when_all_rules_pass():
    decision = _ok()
    assert decision.enter
    assert "LONG" in decision.reason


def test_blocks_when_price_below_ema200_4h():
    decision = _ok(price=64_000.0, ema200_4h=65_000.0)
    assert not decision.enter
    assert "EMA200" in decision.reason


def test_blocks_when_rsi_does_not_cross():
    decision = _ok(prev_rsi=41.0, rsi_value=42.0)
    assert not decision.enter
    assert "RSI" in decision.reason


def test_blocks_when_volume_is_not_above_average():
    decision = _ok(volume=90.0, volume_ma=100.0)
    assert not decision.enter
    assert "volume" in decision.reason.lower()


def test_blocks_second_position_no_averaging_down():
    decision = _ok(has_open_position=True)
    assert not decision.enter
    assert "averaging" in decision.reason.lower()


def test_blocks_when_paused():
    decision = _ok(paused=True, pause_reason="monthly drawdown")
    assert not decision.enter
    assert "monthly drawdown" in decision.reason


def test_stop_and_target_use_atr_multiples():
    entry, atr = 50_000.0, 1_000.0
    assert stop_price(entry, atr) == 50_000.0 - 1.5 * 1_000.0
    assert take_profit_price(entry, atr) == 50_000.0 + 2.0 * 1_000.0


def test_experiment_rr_1_to_2_uses_3x_atr_tp():
    entry, atr = 50_000.0, 1_000.0
    stop = stop_price(entry, atr, atr_mult=1.5)
    take = take_profit_price(entry, atr, atr_mult=3.0)
    assert stop == 50_000.0 - 1.5 * 1_000.0
    assert take == 50_000.0 + 3.0 * 1_000.0
    assert abs((take - entry) / (entry - stop) - 2.0) < 1e-12
