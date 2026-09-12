"""CLI: download public OHLCV, backtest, dry-run, paper signal. No withdrawal commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from alicia.backtest import format_report, run_backtest
from alicia.config import load_settings
from alicia.data import (
    cache_csv_path,
    cache_dir,
    download_ohlcv,
    download_ohlcv_with_fallback,
    load_ohlcv,
    read_cache,
    resolve_cached_1h,
    resolve_or_resample,
)
from alicia.strategy import STOP_ATR_MULT, TP_ATR_MULT
from alicia.orderbook import (
    fetch_public_order_book_with_fallback,
    load_book_json,
)
from alicia.paper import evaluate_latest, load_paper_ohlcv
from alicia.safety import FORBIDDEN_ACTIONS


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alicia",
        description="BTC/USDT spot bot — backtest-first. Read+trade only; no withdrawals.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to env file (default: .env). Secrets are never required for public data.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser(
        "download",
        help="Fetch public BTC/USDT 1h history via ccxt (no API key) and cache it locally",
    )
    dl.add_argument("--years", type=float, default=2.0, help="How many years back (default: 2; ignored for 1m unless --since)")
    dl.add_argument("--days", type=float, default=None, help="Lookback in days (1m experiment default: 60)")
    dl.add_argument(
        "--timeframe",
        default="1h",
        help="Candle timeframe (default: 1h). 1m / 2h are curiosity experiments only.",
    )
    dl.add_argument("--since", default=None, help="UTC start date YYYY-MM-DD (overrides --years/--days)")
    dl.add_argument("--until", default=None, help="UTC end date YYYY-MM-DD (default: now)")
    dl.add_argument("--exchange", default=None, help="ccxt id (default: EXCHANGE or binance)")
    dl.add_argument("--symbol", default=None, help="Spot symbol (default: SYMBOL or BTC/USDT)")
    dl.add_argument("--cache-dir", default=None, help="Cache directory (default: data/cache)")
    dl.add_argument(
        "--force",
        action="store_true",
        help="Re-download the full window instead of appending to the cache",
    )
    dl.add_argument(
        "--no-fallback",
        action="store_true",
        help="Do not try other public venues if the preferred exchange is blocked",
    )

    bt = sub.add_parser(
        "backtest",
        help="Run the strategy on cached public OHLCV (or --csv / --synthetic)",
    )
    bt.add_argument("--csv", default=None, help="1h OHLCV CSV (timestamp,open,high,low,close,volume)")
    bt.add_argument("--cache-dir", default=None, help="Cache directory (default: data/cache)")
    bt.add_argument(
        "--synthetic",
        action="store_true",
        help="Use the built-in synthetic series instead of cached market data",
    )
    bt.add_argument(
        "--no-cost-compare",
        action="store_true",
        help="Skip the extra zero-fee/zero-slippage run used for cost impact",
    )
    bt.add_argument(
        "--timeframe",
        default="1h",
        help="Entry timeframe (default: 1h product). 1m / 2h are curiosity experiments only.",
    )
    bt.add_argument(
        "--trend-timeframe",
        default=None,
        help="Trend EMA200 TF (default: 4h for 1h, 1h for 1m, 8h for 2h)",
    )
    bt.add_argument(
        "--stop-atr",
        type=float,
        default=None,
        help=f"Stop distance in ATR multiples (default: {STOP_ATR_MULT:g}, product)",
    )
    bt.add_argument(
        "--tp-atr",
        type=float,
        default=None,
        help=f"Take-profit distance in ATR multiples (default: {TP_ATR_MULT:g}, product ~1:1.33)",
    )
    bt.add_argument(
        "--reward-risk",
        type=float,
        default=None,
        dest="reward_risk",
        help="If set, TP ATR = this × stop ATR (e.g. 2 → TP 3.0×ATR when stop is 1.5×ATR)",
    )

    dry = sub.add_parser(
        "dry-run",
        help="Prove signal/risk logic on synthetic data (no exchange keys)",
    )
    dry.add_argument("--csv", default=None)
    dry.add_argument(
        "--book",
        default=None,
        help="Optional L2 JSON fixture to demonstrate order-book filters (not used as history)",
    )

    paper = sub.add_parser(
        "paper",
        help="Evaluate the latest signal + public L2 book. Does not place orders.",
    )
    paper.add_argument("--csv", default=None)
    paper.add_argument(
        "--public",
        action="store_true",
        help="Fetch the latest public 1h candles via ccxt (no API key). Requires ccxt",
    )
    paper.add_argument("--cache-dir", default=None)
    paper.add_argument("--book", default=None, help="L2 JSON snapshot instead of a live fetch")
    paper.add_argument(
        "--no-book",
        action="store_true",
        help="Skip the L2 fetch (fails closed if ORDERBOOK_REQUIRE=true)",
    )

    book = sub.add_parser(
        "book",
        help="Fetch or load a public L2 snapshot and print spread/imbalance/depth (no orders)",
    )
    book.add_argument("--json", dest="book_json", default=None, help="Load a recorded L2 fixture")
    book.add_argument("--exchange", default=None)
    book.add_argument("--symbol", default=None)

    sub.add_parser("rules", help="Print the candle rules and order-book filters")
    return parser


RULES_TEXT = """
Alicia rules (see docs/SPEC.md)
  Market: BTC/USDT spot | Entry TF: 1h | Trend TF: 4h | LONG only

  1. Trend filter: new entries only when price is above EMA200(4h).
  2. Entry: RSI(14) 1h crosses up through 40 AND 1h volume > SMA20(volume).
  3. Stop = entry − 1.5×ATR(14,1h). Take-profit = entry + 2×ATR(14,1h). No averaging down.
  4. Size from 1–3% of capital to the stop. Notionals up to €200 allowed; above that, risk-to-stop only. Max one position.
  5. Kill-switch: halt on −10% monthly drawdown; pause on CPI/Fed/NFP days; pause on API/latency errors.
  6. Order book (paper/live, not historical backtest): spread ≤ max bps; top-N imbalance ≥ min;
     bid depth within N bps of mid ≥ min size. Fail closed if the book is missing when required.

  API safety: read + trade only. This CLI has no withdrawal/transfer commands.
  Forbidden actions: {forbidden}
""".strip().format(forbidden=", ".join(sorted(FORBIDDEN_ACTIONS)))


def _missing_cache_message(path: Path) -> str:
    return (
        f"No cached OHLCV at {path}\n"
        "Download public history (no API key):\n"
        "  pip install -e \".[exchange]\"\n"
        "  python -m alicia download --years 2\n"
        "Or pass --csv PATH or --synthetic."
    )


def _trend_tf(entry_tf: str, override: str | None) -> str:
    if override:
        return override
    return {"1m": "1h", "1h": "4h", "2h": "8h"}.get(entry_tf, "4h")


def _atr_multiples(args) -> tuple[float, float]:
    stop_atr = STOP_ATR_MULT if args.stop_atr is None else float(args.stop_atr)
    if args.reward_risk is not None:
        if args.reward_risk <= 0:
            raise ValueError("--reward-risk must be positive")
        tp_atr = float(args.reward_risk) * stop_atr
    elif args.tp_atr is not None:
        tp_atr = float(args.tp_atr)
    else:
        tp_atr = TP_ATR_MULT
    if stop_atr <= 0 or tp_atr <= 0:
        raise ValueError("ATR multiples must be positive")
    return stop_atr, tp_atr


def _resolve_ohlcv(args, settings):
    if getattr(args, "csv", None):
        frame = load_ohlcv(args.csv)
        return frame, f"csv:{args.csv}"
    if getattr(args, "synthetic", False):
        return load_ohlcv(synthetic=True), "synthetic"
    directory = cache_dir(getattr(args, "cache_dir", None))
    timeframe = getattr(args, "timeframe", "1h")
    path = resolve_or_resample(settings.exchange_id, settings.symbol, timeframe, directory)
    if path is None:
        preferred = cache_csv_path(settings.exchange_id, settings.symbol, timeframe, directory)
        print(_missing_cache_message(preferred), file=sys.stderr)
        return None, None
    source = f"cache:{path}"
    meta = path.with_suffix(".meta.json")
    if meta.exists() and "resampled-from-1h" in meta.read_text(encoding="utf-8"):
        source = f"resampled-{timeframe}-from-1h:{path}"
    return read_cache(path), source


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(args.env_file)

    if args.command == "rules":
        print(RULES_TEXT)
        return 0

    if args.command == "download":
        exchange = args.exchange or settings.exchange_id
        symbol = args.symbol or settings.symbol
        directory = cache_dir(args.cache_dir)
        timeframe = args.timeframe
        days = args.days
        if timeframe == "1m" and args.since is None and days is None:
            days = 60.0
        print(
            f"Downloading public {symbol} {timeframe} from {exchange} "
            f"(no API key; fallbacks if geo-blocked) → {directory}/ ..."
        )
        if timeframe in {"1m", "2h"}:
            print(
                f"NOTE: {timeframe} download is a curiosity experiment. "
                "It does not change the default 1h cache pointer."
            )
        def _progress(rows: int, last_ms: int) -> None:
            last = pd.Timestamp(last_ms, unit="ms", tz="UTC")
            print(f"  … {rows} bars through {last}")

        try:
            if args.no_fallback:
                frame = download_ohlcv(
                    exchange_id=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    years=args.years,
                    days=days,
                    since=args.since,
                    until=args.until,
                    directory=directory,
                    force=args.force,
                    on_page=_progress,
                )
                used = exchange
            else:
                frame, used = download_ohlcv_with_fallback(
                    exchange_id=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    years=args.years,
                    days=days,
                    since=args.since,
                    until=args.until,
                    directory=directory,
                    force=args.force,
                    on_page=_progress,
                    on_try=lambda name: print(f"Trying {name} …"),
                    on_skip=lambda name, msg: print(f"  skip {name}: {msg}", file=sys.stderr),
                )
        except Exception as exc:
            print(f"Download failed: {exc}", file=sys.stderr)
            return 1
        exchange = used
        path = cache_csv_path(exchange, symbol, timeframe, directory)
        print(f"Cached {len(frame)} {timeframe} bars: {frame.index[0]} → {frame.index[-1]}")
        print(f"  CSV: {path}")
        if timeframe == "1h":
            h4_path = cache_csv_path(exchange, symbol, "4h", directory)
            if h4_path.exists():
                print(f"  4h CSV (resampled from 1h, for inspection): {h4_path}")
            print("Backtest with: python -m alicia backtest")
        elif timeframe == "1m":
            print(
                "Experiment backtest: python -m alicia backtest --timeframe 1m"
            )
        elif timeframe == "2h":
            print(
                "Experiment backtest: python -m alicia backtest "
                "--timeframe 2h --reward-risk 2"
            )
        return 0

    if args.command == "backtest":
        ohlcv, source = _resolve_ohlcv(args, settings)
        if ohlcv is None:
            return 2
        entry_tf = args.timeframe
        trend_tf = _trend_tf(entry_tf, args.trend_timeframe)
        try:
            stop_atr, tp_atr = _atr_multiples(args)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if entry_tf == "1m":
            print(
                "EXPERIMENT: 1m entry / "
                f"{trend_tf} EMA200 trend. Product default remains 1h/4h. "
                "Order-book filters skipped (no historical L2)."
            )
        elif entry_tf == "2h" or args.reward_risk is not None or (
            args.tp_atr is not None and args.tp_atr != TP_ATR_MULT
        ):
            print(
                f"EXPERIMENT: {entry_tf} entry / {trend_tf} EMA200 / "
                f"stop {stop_atr:g}×ATR / TP {tp_atr:g}×ATR "
                f"(RR 1:{tp_atr / stop_atr:g}). "
                "Product default remains 1h/4h with TP=2×ATR. "
                "Order-book filters skipped (no historical L2)."
            )
        result = run_backtest(
            ohlcv,
            settings,
            source=source,
            compare_zero_cost=not args.no_cost_compare,
            entry_timeframe=entry_tf,
            trend_timeframe=trend_tf,
            stop_atr_mult=stop_atr,
            tp_atr_mult=tp_atr,
        )
        print(format_report(result))
        return 0

    if args.command == "dry-run":
        ohlcv = load_ohlcv(args.csv) if args.csv else load_ohlcv(synthetic=True)
        result = run_backtest(ohlcv, settings, source="synthetic" if not args.csv else f"csv:{args.csv}")
        print(format_report(result))
        print("\nSampled entry decisions (no keys used):")
        shown = 0
        for ts, decision in result.decisions_sampled:
            if decision.enter or shown < 6:
                flag = "ENTER" if decision.enter else "skip "
                print(f"  {ts}  {flag}  {decision.reason}")
                shown += 1
        if not result.trades:
            print(
                "\nNo fills on this series (warmup / filters). "
                "Unit tests still cover each rule in isolation."
            )
        print("\nDry-run complete. Exchange API keys were not used.")
        if args.book:
            from alicia.orderbook import evaluate_book_from_settings, load_book_json

            snap = load_book_json(args.book)
            book = evaluate_book_from_settings(snap, settings)
            print("\nOrder-book fixture (not historical — one recorded snapshot):")
            print(f"  {'PASS' if book.ok else 'BLOCK'}  {book.reason}")
        else:
            print(
                "Order-book filters were not applied to the candle backtest "
                "(no historical L2). Use --book FILE to demo the live gate."
            )
        return 0

    if args.command == "book":
        return _run_book_command(args, settings)

    if args.command == "paper":
        if settings.mode == "live":
            print(
                "Refusing live mode from the paper command. "
                "Paper evaluates signals only and never sends orders.",
                file=sys.stderr,
            )
            return 2
        if args.csv:
            ohlcv = load_paper_ohlcv(settings, csv_path=args.csv, use_public=False)
        elif args.public:
            ohlcv = load_paper_ohlcv(settings, use_public=True)
        else:
            path = resolve_cached_1h(
                settings.exchange_id,
                settings.symbol,
                cache_dir(args.cache_dir),
            )
            if path is not None:
                ohlcv = read_cache(path)
            else:
                ohlcv = load_paper_ohlcv(settings)
        book = None
        book_venue = None
        if args.book:
            book = load_book_json(args.book)
            book_venue = f"fixture:{args.book}"
        elif not args.no_book and settings.orderbook_enabled:
            try:
                book, used = fetch_public_order_book_with_fallback(
                    settings.orderbook_venue,
                    settings.symbol,
                    limit=settings.orderbook_limit,
                )
                book_venue = used
            except Exception as exc:
                print(f"Public L2 fetch failed: {exc}", file=sys.stderr)
                book = None
                book_venue = None
        snap = evaluate_latest(ohlcv, settings, book=book, book_venue=book_venue)
        print("Alicia paper snapshot (no order sent)")
        print(f"  time:       {snap.timestamp}")
        print(f"  price:      {snap.price:.2f}")
        print(f"  EMA200 4h:  {snap.ema200_4h}")
        print(f"  RSI 14:     {snap.prev_rsi} → {snap.rsi}")
        print(f"  volume:     {snap.volume:.2f} vs MA20 {snap.volume_ma}")
        print(f"  ATR 14:     {snap.atr}")
        print(f"  stop/tp:    {snap.stop} / {snap.take_profit}")
        _print_book_section(snap)
        print(f"  decision:   {'ENTER LONG' if snap.decision.enter else 'NO ENTRY'}")
        print(f"  reason:     {snap.decision.reason}")
        return 0

    parser.error(f"unknown command {args.command}")
    return 2


def _print_book_section(snap) -> None:
    print(f"  book venue:  {snap.book_venue}")
    if snap.book is None:
        print("  book:        (disabled)")
        return
    metrics = snap.book.metrics
    if metrics is None:
        print(f"  book:        {snap.book.reason}")
        return
    print(
        f"  book:        bid {metrics.best_bid:.2f} / ask {metrics.best_ask:.2f} "
        f"mid {metrics.mid:.2f}"
    )
    print(
        f"  spread:      {metrics.spread_bps:.2f} bps  "
        f"(half-spread slip est. {metrics.half_spread_bps:.2f} bps; "
        f"backtest still uses SLIPPAGE_BPS)"
    )
    print(
        f"  imbalance:   {metrics.imbalance:.3f}  "
        f"(bid top {metrics.bid_volume_top:.4f} / ask top {metrics.ask_depth_top:.4f})"
    )
    print(f"  bid depth:   {metrics.bid_depth:.4f}")
    print(f"  book gate:   {'PASS' if snap.book.ok else 'BLOCK'}  {snap.book.reason}")


def _run_book_command(args, settings) -> int:
    from alicia.orderbook import evaluate_book_from_settings

    try:
        if args.book_json:
            snap = load_book_json(args.book_json)
            venue = f"fixture:{args.book_json}"
        else:
            exchange = args.exchange or settings.orderbook_venue
            symbol = args.symbol or settings.symbol
            snap, venue = fetch_public_order_book_with_fallback(
                exchange,
                symbol,
                limit=settings.orderbook_limit,
            )
    except Exception as exc:
        print(f"Order book unavailable: {exc}", file=sys.stderr)
        if settings.orderbook_require:
            print("Fail closed: no new LONG while L2 is missing.", file=sys.stderr)
        return 1
    decision = evaluate_book_from_settings(snap, settings)
    print(f"Alicia L2 snapshot — {venue} {settings.symbol} (no order sent)")
    if decision.metrics:
        m = decision.metrics
        print(f"  bid/ask/mid: {m.best_bid:.2f} / {m.best_ask:.2f} / {m.mid:.2f}")
        print(f"  spread:      {m.spread_bps:.2f} bps")
        print(f"  imbalance:   {m.imbalance:.3f} (top {settings.orderbook_levels})")
        print(
            f"  bid depth:   {m.bid_depth:.4f} within {settings.orderbook_depth_bps:g} bps of mid"
        )
        print(f"  half-spread: {m.half_spread_bps:.2f} bps estimated extra slip vs mid")
    print(f"  gate:        {'PASS' if decision.ok else 'BLOCK'}  {decision.reason}")
    return 0 if decision.ok or not settings.orderbook_require else 2


if __name__ == "__main__":
    raise SystemExit(main())
