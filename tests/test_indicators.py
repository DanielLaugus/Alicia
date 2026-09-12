import pandas as pd

from alicia.indicators import attach_indicators, ema, rsi
from alicia.sample_data import generate_sample_ohlcv


def test_ema_of_constant_is_constant():
    values = pd.Series([10.0] * 50)
    out = ema(values, 10)
    assert abs(out.iloc[-1] - 10.0) < 1e-9


def test_rsi_is_high_on_a_steady_rise():
    closes = pd.Series([100.0 + i for i in range(40)])
    value = float(rsi(closes, 14).iloc[-1])
    assert value > 70


def test_rsi_is_low_on_a_steady_drop():
    closes = pd.Series([100.0 - i for i in range(40)])
    value = float(rsi(closes, 14).iloc[-1])
    assert value < 30


def test_completed_4h_ema_has_no_lookahead_from_last_1h_bar():
    df = generate_sample_ohlcv(n_1h=900, seed=1)
    a = attach_indicators(df)
    b_src = df.copy()
    b_src.iloc[-1, b_src.columns.get_loc("close")] = float(b_src.iloc[-1]["close"]) * 1.5
    b_src.iloc[-1, b_src.columns.get_loc("high")] = max(
        float(b_src.iloc[-1]["high"]), float(b_src.iloc[-1]["close"])
    )
    b = attach_indicators(b_src)
    pd.testing.assert_series_equal(a["ema200_4h"], b["ema200_4h"], check_names=False)


def test_ema200_4h_unavailable_until_200_completed_4h_bars():
    # 199 4h bars = 796 hours; EMA200 must stay NaN so we do not enter on a baby EMA.
    df = generate_sample_ohlcv(n_1h=796, seed=4)
    frame = attach_indicators(df)
    assert frame["ema200_4h"].isna().all()
    df_ready = generate_sample_ohlcv(n_1h=200 * 4 + 8, seed=4)
    ready = attach_indicators(df_ready)
    assert ready["ema200_4h"].notna().any()


def test_1m_experiment_uses_completed_1h_ema200():
    idx = pd.date_range("2024-01-01", periods=200 * 60 + 90, freq="1min", tz="UTC")
    close = pd.Series(range(len(idx)), index=idx, dtype="float64") + 40_000.0
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1.0,
        },
        index=idx,
    )
    a = attach_indicators(df, trend_timeframe="1h")
    assert a["ema200_4h"].notna().any()
    b_src = df.copy()
    b_src.iloc[-1, b_src.columns.get_loc("close")] = float(b_src.iloc[-1]["close"]) * 2
    b = attach_indicators(b_src, trend_timeframe="1h")
    pd.testing.assert_series_equal(a["ema200_4h"], b["ema200_4h"], check_names=False)


def test_attach_indicators_adds_expected_columns():
    frame = attach_indicators(generate_sample_ohlcv(n_1h=900, seed=2))
    for col in ("rsi_14", "rsi_14_prev", "atr_14", "volume_ma20", "ema200_4h"):
        assert col in frame.columns
    assert frame["atr_14"].dropna().gt(0).all()
