from dataclasses import replace

from alicia.orderbook import load_book_json
from alicia.paper import evaluate_latest
from alicia.sample_data import generate_sample_ohlcv


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
