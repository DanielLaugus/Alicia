from argparse import Namespace
from dataclasses import replace

from alicia.cli import _resolve_paper_bundle, main
from alicia.indicators import resample_ohlcv
from alicia.orderbook import load_book_json
from alicia.paper import evaluate_latest
from alicia.sample_data import generate_sample_ohlcv, ohlcv_to_csv
from alicia.session import PROFILE_PAPER_ETH, PROFILES


def test_paper_snapshot_does_not_require_keys(settings):
    snap = evaluate_latest(generate_sample_ohlcv(n_1h=1000, seed=3), settings)
    assert snap.price > 0
    assert snap.decision.reason
    assert snap.stop is None or snap.stop < snap.price < (snap.take_profit or snap.price + 1)
    assert snap.book is None


def test_paper_applies_book_fixture(settings):
    ohlcv = generate_sample_ohlcv(n_1h=1000, seed=3)
    live = replace(settings, orderbook_enabled=True, orderbook_require=True)
    passing = evaluate_latest(
        ohlcv,
        live,
        book=load_book_json("tests/fixtures/orderbook_pass.json"),
        book_venue="fixture",
    )
    blocked = evaluate_latest(
        ohlcv,
        live,
        book=load_book_json("tests/fixtures/orderbook_reject_spread.json"),
        book_venue="fixture",
    )
    assert passing.book is not None and passing.book.ok
    assert passing.estimated_cross_slippage_bps is not None
    assert blocked.book is not None and not blocked.book.ok
    assert "spread" in blocked.book.reason
    if passing.decision.enter:
        assert not blocked.decision.enter
        assert "spread" in blocked.decision.reason


def test_paper_require_book_fails_closed(settings):
    live = replace(settings, orderbook_enabled=True, orderbook_require=True)
    snap = evaluate_latest(generate_sample_ohlcv(n_1h=1000, seed=3), live, book=None)
    assert snap.book is not None
    assert not snap.book.ok
    assert "unavailable" in snap.book.reason


def test_paper_eth_profile_pins_eth_regime20():
    assert "paper-eth" in PROFILES
    spec = PROFILES["paper-eth"]
    assert spec.symbol == "ETH/USDT"
    assert spec.signal == "regime"
    assert spec.extra.adx_split == 20.0
    assert spec.entry_timeframe == "4h"
    assert spec.trend_timeframe == "12h"
    assert spec.reward_risk == 2.0
    assert PROFILES["regime-20"].signal == spec.signal
    assert PROFILES["default"].signal == "rsi"
    assert PROFILES["default"].symbol is None


def test_paper_eth_evaluate_uses_regime_and_rr2(settings):
    hourly = generate_sample_ohlcv(n_1h=5200, seed=13)
    bars = resample_ohlcv(hourly, "4h")
    snap = evaluate_latest(bars, settings, profile=PROFILE_PAPER_ETH, symbol="ETH/USDT")
    assert snap.profile == "paper-eth"
    assert snap.symbol == "ETH/USDT"
    assert snap.signal == "regime"
    assert snap.decision.reason
    if snap.stop is not None and snap.take_profit is not None and snap.atr:
        assert abs((snap.price - snap.stop) / snap.atr - 1.5) < 1e-6
        assert abs((snap.take_profit - snap.price) / snap.atr - 3.0) < 1e-6


def test_paper_eth_book_gate_still_fails_closed(settings):
    hourly = generate_sample_ohlcv(n_1h=5200, seed=13)
    bars = resample_ohlcv(hourly, "4h")
    live = replace(settings, orderbook_enabled=True, orderbook_require=True)
    snap = evaluate_latest(bars, live, profile=PROFILE_PAPER_ETH, book=None)
    assert snap.book is not None
    assert not snap.book.ok
    assert not snap.decision.enter
    assert "unavailable" in snap.book.reason


def test_resolve_paper_bundle_defaults_to_paper_eth(settings):
    spec, symbol = _resolve_paper_bundle(Namespace(profile=None, symbol=None), settings)
    assert spec.name == "paper-eth"
    assert symbol == "ETH/USDT"
    spec2, symbol2 = _resolve_paper_bundle(
        Namespace(profile="regime-20", symbol=None),
        replace(settings, paper_symbol="ETH/USDT"),
    )
    assert spec2.name == "regime-20"
    assert symbol2 == "ETH/USDT"


def test_cli_paper_eth_is_paper_only(capsys, tmp_path):
    hourly = generate_sample_ohlcv(n_1h=5200, seed=13)
    bars = resample_ohlcv(hourly, "4h")
    csv_path = tmp_path / "eth4h.csv"
    ohlcv_to_csv(bars, csv_path)
    code = main(
        [
            "paper",
            "--profile",
            "paper-eth",
            "--csv",
            str(csv_path),
            "--book",
            "tests/fixtures/orderbook_pass.json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "PAPER ONLY" in captured.out
    assert "paper-eth" in captured.out
    assert "ETH/USDT" in captured.out
    assert "no order" in captured.out.lower()
    assert "live trading disabled" in captured.out.lower()


def test_cli_paper_regime20_symbol_eth(capsys, tmp_path):
    hourly = generate_sample_ohlcv(n_1h=5200, seed=13)
    bars = resample_ohlcv(hourly, "4h")
    csv_path = tmp_path / "eth4h.csv"
    ohlcv_to_csv(bars, csv_path)
    code = main(
        [
            "paper",
            "--profile",
            "regime-20",
            "--symbol",
            "ETH/USDT",
            "--csv",
            str(csv_path),
            "--book",
            "tests/fixtures/orderbook_pass.json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "regime-20" in captured.out
    assert "ETH/USDT" in captured.out
    assert "official ETH regime-20 paper" in captured.out
    assert "PAPER ONLY" in captured.out


def test_cli_paper_refuses_live_mode(monkeypatch, tmp_path, capsys):
    hourly = generate_sample_ohlcv(n_1h=5200, seed=13)
    bars = resample_ohlcv(hourly, "4h")
    csv_path = tmp_path / "eth4h.csv"
    ohlcv_to_csv(bars, csv_path)
    monkeypatch.setenv("ALICIA_MODE", "live")
    code = main(
        [
            "paper",
            "--profile",
            "paper-eth",
            "--csv",
            str(csv_path),
            "--no-book",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "Refusing live mode" in captured.err


def test_cli_paper_no_book_fails_closed(capsys, tmp_path):
    hourly = generate_sample_ohlcv(n_1h=5200, seed=13)
    bars = resample_ohlcv(hourly, "4h")
    csv_path = tmp_path / "eth4h.csv"
    ohlcv_to_csv(bars, csv_path)
    code = main(
        [
            "paper",
            "--profile",
            "paper-eth",
            "--csv",
            str(csv_path),
            "--no-book",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "Fail closed" in captured.err
    assert "PAPER ONLY" in captured.out
