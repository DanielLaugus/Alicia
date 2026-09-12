"""L2 order-book filters for new LONG entries. No historical books are invented."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from alicia.config import Settings
from alicia.strategy import EntryDecision

BACKTEST_SKIP_REASON = (
    "order-book filters skipped in backtest (no historical L2; "
    "paper/live apply spread, imbalance, and depth)"
)


@dataclass(frozen=True)
class BookSnapshot:
    """Normalized L2 snapshot. Bids/asks are (price, size) best-first."""

    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    timestamp_ms: int | None = None

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0


@dataclass(frozen=True)
class BookMetrics:
    mid: float
    best_bid: float
    best_ask: float
    spread_bps: float
    imbalance: float
    bid_depth: float
    ask_depth_top: float
    bid_volume_top: float
    half_spread_bps: float


@dataclass(frozen=True)
class BookDecision:
    ok: bool
    reason: str
    metrics: BookMetrics | None = None


def snapshot_from_levels(
    bids: Sequence[Sequence[float]],
    asks: Sequence[Sequence[float]],
    timestamp_ms: int | None = None,
) -> BookSnapshot:
    def _norm(levels: Sequence[Sequence[float]], *, reverse: bool) -> tuple[tuple[float, float], ...]:
        cleaned: list[tuple[float, float]] = []
        for level in levels:
            if len(level) < 2:
                continue
            price, size = float(level[0]), float(level[1])
            if price <= 0 or size <= 0:
                continue
            cleaned.append((price, size))
        cleaned.sort(key=lambda item: item[0], reverse=reverse)
        return tuple(cleaned)

    return BookSnapshot(
        bids=_norm(bids, reverse=True),
        asks=_norm(asks, reverse=False),
        timestamp_ms=timestamp_ms,
    )


def snapshot_from_ccxt(raw: dict) -> BookSnapshot:
    ts = raw.get("timestamp")
    return snapshot_from_levels(
        raw.get("bids") or [],
        raw.get("asks") or [],
        timestamp_ms=int(ts) if ts is not None else None,
    )


def load_book_json(path: str | Path) -> BookSnapshot:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return snapshot_from_ccxt(payload)


def spread_bps(snapshot: BookSnapshot) -> float | None:
    mid = snapshot.mid
    if mid is None or mid <= 0 or snapshot.best_bid is None or snapshot.best_ask is None:
        return None
    if snapshot.best_ask < snapshot.best_bid:
        return None
    return (snapshot.best_ask - snapshot.best_bid) / mid * 10_000.0


def top_volume(levels: Sequence[tuple[float, float]], n: int) -> float:
    return float(sum(size for _, size in levels[: max(n, 0)]))


def signed_imbalance(snapshot: BookSnapshot, levels: int) -> float | None:
    bid_vol = top_volume(snapshot.bids, levels)
    ask_vol = top_volume(snapshot.asks, levels)
    denom = bid_vol + ask_vol
    if denom <= 0:
        return None
    return (bid_vol - ask_vol) / denom


def bid_depth_within(snapshot: BookSnapshot, *, mid: float, depth_bps: float) -> float:
    """Bid-side base volume with price ≥ mid × (1 − depth_bps/10_000)."""
    if mid <= 0 or depth_bps < 0:
        return 0.0
    floor = mid * (1.0 - depth_bps / 10_000.0)
    return float(sum(size for price, size in snapshot.bids if price >= floor))


def measure_book(snapshot: BookSnapshot, *, levels: int, depth_bps: float) -> BookMetrics | None:
    spr = spread_bps(snapshot)
    imb = signed_imbalance(snapshot, levels)
    mid = snapshot.mid
    if (
        spr is None
        or imb is None
        or mid is None
        or snapshot.best_bid is None
        or snapshot.best_ask is None
    ):
        return None
    return BookMetrics(
        mid=mid,
        best_bid=snapshot.best_bid,
        best_ask=snapshot.best_ask,
        spread_bps=spr,
        imbalance=imb,
        bid_depth=bid_depth_within(snapshot, mid=mid, depth_bps=depth_bps),
        ask_depth_top=top_volume(snapshot.asks, levels),
        bid_volume_top=top_volume(snapshot.bids, levels),
        half_spread_bps=spr / 2.0,
    )


def evaluate_book_filters(
    snapshot: BookSnapshot | None,
    *,
    max_spread_bps: float,
    levels: int,
    imbalance_min: float,
    min_bid_depth: float,
    depth_bps: float,
    require: bool,
) -> BookDecision:
    """Fail closed on a missing or unusable book when ``require`` is true."""
    if snapshot is None:
        if require:
            return BookDecision(False, "order book required but unavailable")
        return BookDecision(True, BACKTEST_SKIP_REASON)

    if not snapshot.bids or not snapshot.asks:
        return BookDecision(False, "order book empty (fail closed)")
    if snapshot.best_ask is not None and snapshot.best_bid is not None:
        if snapshot.best_ask < snapshot.best_bid:
            return BookDecision(False, "order book crossed (fail closed)")

    metrics = measure_book(snapshot, levels=levels, depth_bps=depth_bps)
    if metrics is None:
        return BookDecision(False, "order book unusable (fail closed)")

    if metrics.spread_bps > max_spread_bps:
        return BookDecision(
            False,
            f"spread {metrics.spread_bps:.2f} bps > max {max_spread_bps:g} bps",
            metrics,
        )
    if metrics.imbalance < imbalance_min:
        return BookDecision(
            False,
            f"imbalance {metrics.imbalance:.3f} < min {imbalance_min:g} "
            f"(top {levels} levels; need bid-heavy / not ask-heavy)",
            metrics,
        )
    if metrics.bid_depth < min_bid_depth:
        return BookDecision(
            False,
            f"bid depth {metrics.bid_depth:.4f} < min {min_bid_depth:g} "
            f"within {depth_bps:g} bps of mid",
            metrics,
        )
    return BookDecision(
        True,
        (
            f"book OK: spread {metrics.spread_bps:.2f} bps, "
            f"imbalance {metrics.imbalance:.3f}, "
            f"bid depth {metrics.bid_depth:.4f}"
        ),
        metrics,
    )


def evaluate_book_from_settings(
    snapshot: BookSnapshot | None,
    settings: Settings,
    *,
    require: bool | None = None,
) -> BookDecision:
    return evaluate_book_filters(
        snapshot,
        max_spread_bps=settings.orderbook_max_spread_bps,
        levels=settings.orderbook_levels,
        imbalance_min=settings.orderbook_imbalance_min,
        min_bid_depth=settings.orderbook_min_bid_depth,
        depth_bps=settings.orderbook_depth_bps,
        require=settings.orderbook_require if require is None else require,
    )


def apply_orderbook_gate(
    candle: EntryDecision,
    snapshot: BookSnapshot | None,
    settings: Settings,
    *,
    apply: bool,
) -> EntryDecision:
    """Additional LONG gate. Candle rules stay unchanged; this only blocks."""
    if not candle.enter:
        return candle
    if not apply:
        return candle
    book = evaluate_book_from_settings(snapshot, settings)
    if not book.ok:
        return EntryDecision(False, book.reason)
    return EntryDecision(True, f"{candle.reason}; {book.reason}")


def fetch_public_order_book(
    exchange_id: str,
    symbol: str,
    *,
    limit: int = 20,
) -> BookSnapshot:
    """Public L2 via ccxt. Never attaches API keys."""
    from alicia.data import _public_exchange

    exchange = _public_exchange(exchange_id)
    raw = exchange.fetch_order_book(symbol, limit)
    return snapshot_from_ccxt(raw)


def fetch_public_order_book_with_fallback(
    exchange_id: str,
    symbol: str,
    *,
    limit: int = 20,
    fallbacks: Iterable[str] = ("okx", "kucoin", "gate"),
) -> tuple[BookSnapshot, str]:
    chain: list[str] = []
    for name in (exchange_id, *fallbacks):
        if name and name not in chain:
            chain.append(name)
    errors: list[str] = []
    for name in chain:
        try:
            return fetch_public_order_book(name, symbol, limit=limit), name
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("No public L2 book available.\n" + "\n".join(errors))
