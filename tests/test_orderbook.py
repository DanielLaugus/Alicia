from dataclasses import replace

from alicia.orderbook import (
    BACKTEST_SKIP_REASON,
    apply_orderbook_gate,
    bid_depth_within,
    evaluate_book_filters,
    evaluate_book_from_settings,
    load_book_json,
    signed_imbalance,
    snapshot_from_levels,
    spread_bps,
)
from alicia.strategy import EntryDecision


PASS_FIXTURE = "tests/fixtures/orderbook_pass.json"
WIDE_FIXTURE = "tests/fixtures/orderbook_reject_spread.json"
WEAK_IMB_FIXTURE = "tests/fixtures/orderbook_reject_imbalance.json"

TIGHT = dict(
    max_spread_bps=2.0,
    levels=10,
    imbalance_min=0.20,
    min_bid_depth=2.0,
    depth_bps=5.0,
    require=True,
)


def test_spread_imbalance_depth_math_on_pass_fixture():
    book = load_book_json(PASS_FIXTURE)
    assert book.best_bid == 66998.5
    assert book.best_ask == 67001.5
    spr = spread_bps(book)
    assert spr is not None and spr <= 2.0
    imb = signed_imbalance(book, 10)
    assert imb is not None and imb >= 0.20
    depth = bid_depth_within(book, mid=book.mid, depth_bps=5.0)
    assert depth >= 2.0


def test_wide_spread_blocks():
    decision = evaluate_book_filters(load_book_json(WIDE_FIXTURE), **TIGHT)
    assert not decision.ok
    assert "spread" in decision.reason


def test_weak_bid_imbalance_blocks_under_plus_0_20():
    book = load_book_json(WEAK_IMB_FIXTURE)
    imb = signed_imbalance(book, 10)
    assert imb is not None and 0.0 <= imb < 0.20
    decision = evaluate_book_filters(book, **TIGHT)
    assert not decision.ok
    assert "imbalance" in decision.reason


def test_ask_heavy_imbalance_blocks():
    book = snapshot_from_levels(
        bids=[[100.0, 1.0], [99.9, 1.0]],
        asks=[[100.02, 8.0], [100.03, 8.0]],
    )
    decision = evaluate_book_filters(
        book,
        max_spread_bps=2.0,
        levels=10,
        imbalance_min=0.20,
        min_bid_depth=0.1,
        depth_bps=20.0,
        require=True,
    )
    assert not decision.ok
    assert "imbalance" in decision.reason


def test_thin_bid_depth_blocks():
    book = snapshot_from_levels(
        bids=[[100.0, 0.05], [99.0, 5.0]],
        asks=[[100.02, 0.05]],
    )
    # 5 bps of ~100.01 mid ≈ 0.05; only the 0.05 bid sits inside the band.
    decision = evaluate_book_filters(
        book,
        max_spread_bps=2.0,
        levels=10,
        imbalance_min=-1.0,
        min_bid_depth=2.0,
        depth_bps=5.0,
        require=True,
    )
    assert not decision.ok
    assert "depth" in decision.reason


def test_missing_book_fails_closed_when_required():
    decision = evaluate_book_filters(None, **TIGHT)
    assert not decision.ok
    assert "unavailable" in decision.reason


def test_missing_book_skipped_when_not_required():
    decision = evaluate_book_filters(None, **{**TIGHT, "require": False})
    assert decision.ok
    assert decision.reason == BACKTEST_SKIP_REASON


def test_empty_and_crossed_books_fail_closed():
    empty = snapshot_from_levels(bids=[], asks=[[100.0, 1.0]])
    crossed = snapshot_from_levels(bids=[[101.0, 1.0]], asks=[[100.0, 1.0]])
    assert not evaluate_book_filters(empty, **TIGHT).ok
    assert not evaluate_book_filters(crossed, **TIGHT).ok


def test_gate_does_not_override_a_candle_block(settings):
    candle = EntryDecision(False, "price is not above EMA200(4h)")
    book = load_book_json(PASS_FIXTURE)
    live = replace(settings, orderbook_enabled=True, orderbook_require=True)
    gated = apply_orderbook_gate(candle, book, live, apply=True)
    assert not gated.enter
    assert gated.reason == candle.reason


def test_gate_blocks_passing_candle_when_book_fails(settings):
    candle = EntryDecision(True, "LONG: trend + RSI cross + volume confirmation")
    live = replace(settings, orderbook_enabled=True, orderbook_require=True)
    gated = apply_orderbook_gate(candle, load_book_json(WIDE_FIXTURE), live, apply=True)
    assert not gated.enter
    assert "spread" in gated.reason


def test_settings_pass_fixture(settings):
    live = replace(settings, orderbook_enabled=True, orderbook_require=True)
    decision = evaluate_book_from_settings(load_book_json(PASS_FIXTURE), live)
    assert decision.ok
    assert decision.metrics is not None
    assert decision.metrics.half_spread_bps == decision.metrics.spread_bps / 2.0
    assert decision.metrics.imbalance >= 0.20
    assert decision.metrics.bid_depth >= 2.0
    assert decision.metrics.spread_bps <= 2.0
