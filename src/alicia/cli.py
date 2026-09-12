"""CLI: download public OHLCV, backtest, dry-run, paper signal. No withdrawal commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alicia.backtest import format_report, run_backtest
from alicia.config import load_settings
from alicia.data import (
    cache_csv_path,
    cache_dir,
    download_ohlcv,
    load_ohlcv,
    read_cache,
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
    dl.add_argument("--years", type=float, default=2.0, help="How many years back (default: 2)")
    dl.add_argument("--since", default=None, help="UTC start date YYYY-MM-DD (overrides --years)")
    dl.add_argument("--until", default=None, help="UTC end date YYYY-MM-DD (default: now)")
    dl.add_argument("--exchange", default=None, help="ccxt id (default: EXCHANGE or binance)")
    dl.add_argument("--symbol", default=None, help="Spot symbol (default: SYMBOL or BTC/USDT)")
    dl.add_argument("--cache-dir", default=None, help="Cache directory (default: data/cache)")
    dl.add_argument(
        "--force",
        action="store_true",
        help="Re-download the full window instead of appending to the cache",
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

    dry = sub.add_parser(
        "dry-run",
        help="Prove signal/risk logic on synthetic data (no exchange keys)",
    )
    dry.add_argument("--csv", default=None)

    paper = sub.add_parser(
        "paper",
        help="Evaluate the latest signal (cache, CSV, or public OHLCV). Does not place orders.",
    )
    paper.add_argument("--csv", default=None)
    paper.add_argument(
        "--public",
        action="store_true",
        help="Fetch the latest public 1h candles via ccxt (no API key). Requires ccxt",
    )
    paper.add_argument("--cache-dir", default=None)

    sub.add_parser("rules", help="Print the five strategy rules")
    return parser


RULES_TEXT = """
Alicia rules (see docs/SPEC.md)
  Market: BTC/USDT spot | Entry TF: 1h | Trend TF: 4h | LONG only

  1. Trend filter: new entries only when price is above EMA200(4h).
  2. Entry: RSI(14) 1h crosses up through 40 AND 1h volume > SMA20(volume).
  3. Stop = entry − 1.5×ATR(14,1h). Take-profit = entry + 2×ATR(14,1h). No averaging down.
  4. Size from 1–3% of capital to the stop. Notionals up to €200 allowed; above that, risk-to-stop only. Max one position.
  5. Kill-switch: halt on −10% monthly drawdown; pause on CPI/Fed/NFP days; pause on API/latency errors.

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


def _resolve_ohlcv(args, settings):
    if getattr(args, "csv", None):
        frame = load_ohlcv(args.csv)
        return frame, f"csv:{args.csv}"
    if getattr(args, "synthetic", False):
        return load_ohlcv(synthetic=True), "synthetic"
    directory = cache_dir(getattr(args, "cache_dir", None))
    path = cache_csv_path(settings.exchange_id, settings.symbol, "1h", directory)
    if not path.exists():
        print(_missing_cache_message(path), file=sys.stderr)
        return None, None
    return read_cache(path), f"cache:{path}"


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
        print(
            f"Downloading public {symbol} 1h from {exchange} "
            f"(no API key) → {directory}/ ..."
        )
        try:
            frame = download_ohlcv(
                exchange_id=exchange,
                symbol=symbol,
                years=args.years,
                since=args.since,
                until=args.until,
                directory=directory,
                force=args.force,
            )
        except Exception as exc:
            print(f"Download failed: {exc}", file=sys.stderr)
            return 1
        path = cache_csv_path(exchange, symbol, "1h", directory)
        h4_path = cache_csv_path(exchange, symbol, "4h", directory)
        print(f"Cached {len(frame)} 1h bars: {frame.index[0]} → {frame.index[-1]}")
        print(f"  1h CSV: {path}")
        if h4_path.exists():
            print(f"  4h CSV (resampled from 1h, for inspection): {h4_path}")
        print("Backtest with: python -m alicia backtest")
        return 0

    if args.command == "backtest":
        ohlcv, source = _resolve_ohlcv(args, settings)
        if ohlcv is None:
            return 2
        result = run_backtest(
            ohlcv,
            settings,
            source=source,
            compare_zero_cost=not args.no_cost_compare,
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
        return 0

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
            path = cache_csv_path(
                settings.exchange_id,
                settings.symbol,
                "1h",
                cache_dir(args.cache_dir),
            )
            if path.exists():
                ohlcv = read_cache(path)
            else:
                ohlcv = load_paper_ohlcv(settings)
        snap = evaluate_latest(ohlcv, settings)
        print("Alicia paper snapshot (no order sent)")
        print(f"  time:       {snap.timestamp}")
        print(f"  price:      {snap.price:.2f}")
        print(f"  EMA200 4h:  {snap.ema200_4h}")
        print(f"  RSI 14:     {snap.prev_rsi} → {snap.rsi}")
        print(f"  volume:     {snap.volume:.2f} vs MA20 {snap.volume_ma}")
        print(f"  ATR 14:     {snap.atr}")
        print(f"  stop/tp:    {snap.stop} / {snap.take_profit}")
        print(f"  decision:   {'ENTER LONG' if snap.decision.enter else 'NO ENTRY'}")
        print(f"  reason:     {snap.decision.reason}")
        return 0

    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
