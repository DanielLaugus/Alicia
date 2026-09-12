"""CLI: backtest, dry-run, paper signal. No withdrawal commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alicia.backtest import format_report, run_backtest
from alicia.config import load_settings
from alicia.data import load_ohlcv
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
        help="Path to env file (default: .env). Secrets are never required for backtest/dry-run.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="Run the strategy on sample or CSV 1h OHLCV")
    bt.add_argument("--csv", default=None, help="Optional 1h OHLCV CSV (timestamp,open,high,low,close,volume)")

    dry = sub.add_parser(
        "dry-run",
        help="Prove signal/risk logic on synthetic data (no exchange keys)",
    )
    dry.add_argument("--csv", default=None)

    paper = sub.add_parser(
        "paper",
        help="Evaluate the latest signal (sample data or public OHLCV). Does not place orders.",
    )
    paper.add_argument("--csv", default=None)
    paper.add_argument(
        "--public",
        action="store_true",
        help="Fetch public 1h candles via ccxt (no API key). Requires: pip install ccxt",
    )

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


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(args.env_file)

    if args.command == "rules":
        print(RULES_TEXT)
        return 0

    if args.command in {"backtest", "dry-run"}:
        ohlcv = load_ohlcv(args.csv)
        result = run_backtest(ohlcv, settings)
        print(format_report(result))
        if args.command == "dry-run":
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
        ohlcv = load_paper_ohlcv(settings, csv_path=args.csv, use_public=args.public)
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
