from datetime import datetime, timezone

from alicia.risk import MonthlyDrawdownGuard, clamp_risk_pct, position_qty


def test_risk_pct_clamped_to_1_3_percent():
    assert clamp_risk_pct(0.0) == 0.01
    assert clamp_risk_pct(0.05) == 0.03
    assert clamp_risk_pct(0.02) == 0.02


def test_qty_derived_from_stop_distance():
    entry, stop = 50_000.0, 49_000.0
    capital, risk = 10_000.0, 0.02
    qty = position_qty(
        capital_eur=capital,
        entry_price=entry,
        stop=stop,
        risk_pct=risk,
        max_small_notional_eur=200.0,
    )
    # 2% of 10k = 200 USDT risk; stop distance 1000 → 0.2 BTC → notional 10_000
    assert abs(qty - 0.2) < 1e-9
    assert qty * entry > 200.0  # above €200 uses risk-to-stop, not a hard €200 cap


def test_small_notional_path_does_not_exceed_200():
    # Wide stop + 1% of €1000 → notional under €200
    qty = position_qty(
        capital_eur=1_000.0,
        entry_price=50_000.0,
        stop=47_000.0,
        risk_pct=0.01,
        max_small_notional_eur=200.0,
    )
    assert qty * 50_000.0 <= 200.0 + 1e-9
    assert abs(qty * (50_000.0 - 47_000.0) - 10.0) < 1e-9


def test_available_quote_caps_size():
    qty = position_qty(
        capital_eur=10_000.0,
        entry_price=50_000.0,
        stop=49_000.0,
        risk_pct=0.02,
        max_small_notional_eur=200.0,
        available_quote=100.0,
    )
    assert abs(qty - 100.0 / 50_000.0) < 1e-9


def test_invalid_stop_yields_zero():
    assert (
        position_qty(
            capital_eur=1000,
            entry_price=50_000,
            stop=51_000,
            risk_pct=0.02,
            max_small_notional_eur=200,
        )
        == 0.0
    )


def test_monthly_drawdown_halts_at_minus_10_percent():
    guard = MonthlyDrawdownGuard(threshold=0.10)
    t0 = datetime(2024, 3, 1, tzinfo=timezone.utc)
    assert not guard.update(t0, 1000.0)
    t1 = datetime(2024, 3, 10, tzinfo=timezone.utc)
    assert guard.update(t1, 899.0)
    assert guard.halted
    assert "monthly drawdown" in (guard.reason or "")


def test_monthly_drawdown_resets_next_month():
    guard = MonthlyDrawdownGuard(threshold=0.10)
    guard.update(datetime(2024, 3, 1, tzinfo=timezone.utc), 1000.0)
    guard.update(datetime(2024, 3, 5, tzinfo=timezone.utc), 800.0)
    assert guard.halted
    assert not guard.update(datetime(2024, 4, 1, tzinfo=timezone.utc), 800.0)
    assert not guard.halted
