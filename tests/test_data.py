from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from alicia.data import (
    bars_to_frame,
    cache_csv_path,
    download_ohlcv,
    drop_incomplete_last_bar,
    history_covers_request,
    load_ohlcv,
    merge_ohlcv,
    paginate_ohlcv,
    read_cache,
    resolve_cached_1h,
    resolve_or_resample,
    write_resampled_cache,
)
from alicia.sample_data import generate_sample_ohlcv, ohlcv_to_csv


def _catalog(n: int = 2500, start: str = "2024-01-01"):
    idx = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return [
        [int(ts.timestamp() * 1000), 100.0, 101.0, 99.0, 100.5, 10.0]
        for ts in idx
    ]


class FakePublicExchange:
    def __init__(self, rows: list[list], page: int = 400):
        self.rows = rows
        self.page = page
        self.calls: list[tuple] = []

    def __call__(self, symbol: str, timeframe: str, since_ms: int | None, limit: int):
        self.calls.append((symbol, timeframe, since_ms, limit))
        subset = [r for r in self.rows if since_ms is None or r[0] >= since_ms]
        return subset[: min(limit, self.page)]


def test_bars_to_frame_and_merge_dedupes():
    a = bars_to_frame([[1_700_000_000_000, 1, 2, 0.5, 1.5, 10]])
    b = bars_to_frame(
        [
            [1_700_000_000_000, 1, 2, 0.5, 1.6, 11],
            [1_700_000_360_000, 1.6, 2, 1, 1.7, 8],
        ]
    )
    merged = merge_ohlcv(a, b)
    assert len(merged) == 2
    assert merged.iloc[0]["close"] == 1.6


def test_drop_incomplete_last_bar():
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
        index=idx,
    )
    now = datetime(2024, 1, 1, 2, 30, tzinfo=timezone.utc)
    trimmed = drop_incomplete_last_bar(frame, "1h", now=now)
    assert len(trimmed) == 2
    assert trimmed.index[-1] == idx[1]


def test_paginate_walks_since_cursor():
    rows = _catalog(1250)
    fake = FakePublicExchange(rows, page=400)
    frame = paginate_ohlcv(
        symbol="BTC/USDT",
        timeframe="1h",
        since_ms=rows[0][0],
        until_ms=rows[-1][0] + 3_600_000,
        limit=400,
        fetch=fake,
    )
    assert len(frame) == 1250
    assert len(fake.calls) >= 4


def test_paginate_continues_when_exchange_page_is_smaller_than_limit():
    rows = _catalog(900)
    fake = FakePublicExchange(rows, page=300)
    frame = paginate_ohlcv(
        symbol="BTC/USDT",
        timeframe="1h",
        since_ms=rows[0][0],
        until_ms=rows[-1][0] + 3_600_000,
        limit=1000,
        fetch=fake,
    )
    assert len(frame) == 900
    assert len(fake.calls) >= 3


def test_cache_roundtrip(tmp_path):
    src = generate_sample_ohlcv(n_1h=48, seed=1)
    path = tmp_path / "sample.csv"
    ohlcv_to_csv(src, path)
    loaded = load_ohlcv(path)
    pd.testing.assert_frame_equal(src, loaded, check_freq=False)


def test_download_writes_cache_and_derived_4h(tmp_path):
    rows = _catalog(40, start="2024-01-01")
    fake = FakePublicExchange(rows, page=20)
    now_ms = rows[-1][0] + 3_600_000
    frame = download_ohlcv(
        exchange_id="binance",
        symbol="BTC/USDT",
        since="2024-01-01",
        until=str(pd.Timestamp(now_ms, unit="ms", tz="UTC")),
        directory=tmp_path,
        force=True,
        fetch=fake,
        derive_4h=True,
    )
    path = cache_csv_path("binance", "BTC/USDT", "1h", tmp_path)
    assert path.exists()
    assert cache_csv_path("binance", "BTC/USDT", "4h", tmp_path).exists()
    cached = read_cache(path)
    assert len(cached) == len(frame)
    assert cached.index.tz is not None


def test_download_appends_incrementally(tmp_path):
    rows = _catalog(30, start="2024-01-01")
    first = FakePublicExchange(rows[:20], page=50)
    until = str(pd.Timestamp(rows[19][0] + 3_600_000, unit="ms", tz="UTC"))
    download_ohlcv(
        exchange_id="binance",
        symbol="BTC/USDT",
        since="2024-01-01",
        until=until,
        directory=tmp_path,
        force=True,
        fetch=first,
        derive_4h=False,
    )
    second = FakePublicExchange(rows, page=50)
    until2 = str(pd.Timestamp(rows[-1][0] + 3_600_000, unit="ms", tz="UTC"))
    frame = download_ohlcv(
        exchange_id="binance",
        symbol="BTC/USDT",
        until=until2,
        directory=tmp_path,
        force=False,
        fetch=second,
        derive_4h=False,
    )
    assert len(frame) == 30
    # Incremental call should start after the last cached bar, not from year window.
    assert second.calls[0][2] > rows[0][0]


def test_history_covers_request_rejects_recent_window_only():
    idx = pd.date_range("2026-08-13", periods=720, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
        index=idx,
    )
    assert not history_covers_request(frame, years=2.0, since=None)
    long_idx = pd.date_range("2024-09-01", periods=4000, freq="1h", tz="UTC")
    long = frame.reindex(long_idx).ffill()
    until = str(long.index[-1] + pd.Timedelta(hours=1))
    assert history_covers_request(long, years=0.4, since="2024-09-01", until=until)


def test_short_recent_cache_does_not_cover_two_years(tmp_path):
    rows = _catalog(20, start="2026-09-01")
    fake = FakePublicExchange(rows, page=50)
    until = str(pd.Timestamp(rows[-1][0] + 3_600_000, unit="ms", tz="UTC"))
    short = download_ohlcv(
        exchange_id="kraken-like",
        symbol="BTC/USDT",
        since="2024-01-01",
        until=until,
        directory=tmp_path,
        force=True,
        fetch=fake,
        derive_4h=False,
    )
    assert not history_covers_request(short, years=2.0, since="2024-01-01")


def test_1m_download_does_not_overwrite_1h_active_pointer(tmp_path):
    rows_1h = _catalog(24, start="2024-01-01")
    fake_1h = FakePublicExchange(rows_1h, page=50)
    until_1h = str(pd.Timestamp(rows_1h[-1][0] + 3_600_000, unit="ms", tz="UTC"))
    download_ohlcv(
        exchange_id="okx",
        symbol="BTC/USDT",
        timeframe="1h",
        since="2024-01-01",
        until=until_1h,
        directory=tmp_path,
        force=True,
        fetch=fake_1h,
        derive_4h=False,
    )
    pointer = (tmp_path / "active.json").read_text(encoding="utf-8")
    rows_1m = [
        [1_704_067_200_000 + i * 60_000, 1, 2, 0.5, 1.5, 1]
        for i in range(30)
    ]
    fake_1m = FakePublicExchange(rows_1m, page=50)
    until_1m = str(pd.Timestamp(rows_1m[-1][0] + 60_000, unit="ms", tz="UTC"))
    download_ohlcv(
        exchange_id="okx",
        symbol="BTC/USDT",
        timeframe="1m",
        since="2024-01-01",
        until=until_1m,
        directory=tmp_path,
        force=True,
        fetch=fake_1m,
        derive_4h=False,
    )
    assert (tmp_path / "active.json").read_text(encoding="utf-8") == pointer
    assert cache_csv_path("okx", "BTC/USDT", "1m", tmp_path).exists()


def test_2h_download_does_not_overwrite_1h_active_pointer(tmp_path):
    rows_1h = _catalog(24, start="2024-01-01")
    fake_1h = FakePublicExchange(rows_1h, page=50)
    until_1h = str(pd.Timestamp(rows_1h[-1][0] + 3_600_000, unit="ms", tz="UTC"))
    download_ohlcv(
        exchange_id="okx",
        symbol="BTC/USDT",
        timeframe="1h",
        since="2024-01-01",
        until=until_1h,
        directory=tmp_path,
        force=True,
        fetch=fake_1h,
        derive_4h=False,
    )
    pointer = (tmp_path / "active.json").read_text(encoding="utf-8")
    rows_2h = [
        [1_704_067_200_000 + i * 7_200_000, 1, 2, 0.5, 1.5, 1]
        for i in range(20)
    ]
    fake_2h = FakePublicExchange(rows_2h, page=50)
    until_2h = str(pd.Timestamp(rows_2h[-1][0] + 7_200_000, unit="ms", tz="UTC"))
    download_ohlcv(
        exchange_id="okx",
        symbol="BTC/USDT",
        timeframe="2h",
        since="2024-01-01",
        until=until_2h,
        directory=tmp_path,
        force=True,
        fetch=fake_2h,
        derive_4h=False,
    )
    assert (tmp_path / "active.json").read_text(encoding="utf-8") == pointer
    assert cache_csv_path("okx", "BTC/USDT", "2h", tmp_path).exists()


def test_resolve_cached_prefers_active_venue_when_multiple_4h(tmp_path):
    from alicia.data import resolve_cached, write_active_pointer

    rows = _catalog(24, start="2024-01-01")
    fake = FakePublicExchange(rows, page=80)
    until = str(pd.Timestamp(rows[-1][0] + 3_600_000, unit="ms", tz="UTC"))
    download_ohlcv(
        exchange_id="okx",
        symbol="BTC/USDT",
        timeframe="1h",
        since="2024-01-01",
        until=until,
        directory=tmp_path,
        force=True,
        fetch=fake,
        derive_4h=True,
    )
    download_ohlcv(
        exchange_id="kraken",
        symbol="BTC/USDT",
        timeframe="4h",
        since="2024-01-01",
        until=until,
        directory=tmp_path,
        force=True,
        fetch=FakePublicExchange(
            [[1_704_067_200_000 + i * 14_400_000, 1, 2, 0.5, 1.5, 1] for i in range(8)],
            page=50,
        ),
        derive_4h=False,
        update_active=False,
    )
    write_active_pointer(
        exchange_id="okx",
        symbol="BTC/USDT",
        timeframe="1h",
        csv_path=cache_csv_path("okx", "BTC/USDT", "1h", tmp_path),
        directory=tmp_path,
    )
    path = resolve_cached("binance", "BTC/USDT", "4h", tmp_path)
    assert path is not None
    assert path.name.startswith("okx_")


def test_resolve_or_resample_builds_2h_from_1h(tmp_path):
    rows = _catalog(48, start="2024-01-01")
    fake = FakePublicExchange(rows, page=80)
    until = str(pd.Timestamp(rows[-1][0] + 3_600_000, unit="ms", tz="UTC"))
    download_ohlcv(
        exchange_id="okx",
        symbol="BTC/USDT",
        timeframe="1h",
        since="2024-01-01",
        until=until,
        directory=tmp_path,
        force=True,
        fetch=fake,
        derive_4h=False,
    )
    path = resolve_or_resample("okx", "BTC/USDT", "2h", tmp_path)
    assert path is not None
    frame = read_cache(path)
    assert len(frame) == 24
    assert (frame.index[1] - frame.index[0]) == pd.Timedelta(hours=2)
    src = cache_csv_path("okx", "BTC/USDT", "1h", tmp_path)
    dest = write_resampled_cache(
        src, "2h", exchange_id="okx", symbol="BTC/USDT", directory=tmp_path
    )
    assert dest.exists()


def test_resolve_cached_1h_uses_active_pointer(tmp_path):
    rows = _catalog(24, start="2024-01-01")
    fake = FakePublicExchange(rows, page=50)
    until = str(pd.Timestamp(rows[-1][0] + 3_600_000, unit="ms", tz="UTC"))
    download_ohlcv(
        exchange_id="okx",
        symbol="BTC/USDT",
        since="2024-01-01",
        until=until,
        directory=tmp_path,
        force=True,
        fetch=fake,
        derive_4h=False,
    )
    path = resolve_cached_1h("binance", "BTC/USDT", tmp_path)
    assert path is not None
    assert path.name.startswith("okx_")


def test_fixture_csv_loads():
    frame = load_ohlcv("tests/fixtures/tiny_btcusdt_1h.csv")
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 5
    assert str(frame.index.tz) == "UTC"
