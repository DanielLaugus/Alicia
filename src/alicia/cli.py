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
from alicia.session import (
    PROFILES,
    SESSION_PRESETS,
    SessionWindow,
    parse_hhmm,
)
from alicia.strategy import (
    ADX_SPLIT_DEFAULT,
    DONCHIAN_N,
    ExtraFilters,
    SIDES,
    SIGNALS,
    STOP_ATR_MULT,
    STOP_MODES,
    TP_ATR_MULT,
)
from dataclasses import replace
from alicia.orderbook import (
    evaluate_book_from_settings,
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
        help="Candle timeframe (default: 1h). 1m / 2h / 4h are curiosity experiments only.",
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
    bt.add_argument("--csv", default=None, help="OHLCV CSV (timestamp,open,high,low,close,volume)")
    bt.add_argument("--cache-dir", default=None, help="Cache directory (default: data/cache)")
    bt.add_argument(
        "--symbol",
        default=None,
        help="Spot symbol for cache lookup (default: SYMBOL or BTC/USDT). Use ETH/USDT for the regime-20 ETH run.",
    )
    bt.add_argument(
        "--exchange",
        default=None,
        help="Cache venue id (default: EXCHANGE / active pointer)",
    )
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
        "--profile",
        default=None,
        choices=sorted(name for name in PROFILES if name != "default"),
        help="Named experiment bundle (not the 1h/4h RSI product default). "
        "breakout / breakout-us = Donchian + EMA200; us-session = RSI in NY peak.",
    )
    bt.add_argument(
        "--timeframe",
        default="1h",
        help="Entry timeframe (default: 1h product). 1m / 2h / 4h are curiosity experiments only.",
    )
    bt.add_argument(
        "--trend-timeframe",
        default=None,
        help="Trend EMA200 TF (default: 4h for 1h, 1h for 1m, 8h for 2h, 12h for 4h)",
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
    bt.add_argument(
        "--session",
        default=None,
        choices=sorted(SESSION_PRESETS),
        help="Named UTC session window (us / us-primary / us-overlap / us-wide). Off by default.",
    )
    bt.add_argument("--session-start", default=None, help="UTC HH:MM session start (bar-close clock)")
    bt.add_argument("--session-end", default=None, help="UTC HH:MM session end inclusive")
    bt.add_argument(
        "--all-days",
        action="store_true",
        help="Allow weekend session entries (US profile defaults to Mon–Fri UTC)",
    )
    bt.add_argument(
        "--ema-slope",
        action="store_true",
        help="Experiment: require the trend EMA200 to be rising vs the prior bar",
    )
    bt.add_argument(
        "--ema50",
        action="store_true",
        help="Experiment: require price above EMA50 on the entry TF (AND with other gates)",
    )
    bt.add_argument(
        "--chop-filter",
        action="store_true",
        help="Experiment: skip entries when ATR% is below its 200-bar 25th percentile",
    )
    bt.add_argument(
        "--rsi-from",
        type=float,
        default=None,
        help="Experiment: require previous RSI below this (still cross up through 40)",
    )
    bt.add_argument(
        "--breakeven-r",
        type=float,
        default=None,
        help="Experiment: after +N×R favorable, move stop to cost-aware breakeven",
    )
    bt.add_argument(
        "--signal",
        default=None,
        choices=list(SIGNALS),
        help="Entry family: rsi (product default), breakout (Donchian + EMA200), "
        "or pullback (EMA20 reclaim). Profiles may set this.",
    )
    bt.add_argument(
        "--donchian-n",
        type=int,
        default=None,
        help=f"Prior N-bar high for --signal breakout (default: {DONCHIAN_N})",
    )
    bt.add_argument(
        "--trail-atr",
        type=float,
        default=None,
        help="If set, trail the stop by this ×ATR after each completed bar (no fixed TP)",
    )
    bt.add_argument(
        "--stop-mode",
        default=None,
        choices=list(STOP_MODES),
        help="Initial stop: atr (product 1.5×ATR) or bar-low (breakout-bar low if below fill)",
    )
    bt.add_argument(
        "--adx-min",
        type=float,
        default=None,
        help="Experiment: require ADX >= this (trend regime)",
    )
    bt.add_argument(
        "--adx-max",
        type=float,
        default=None,
        help="Experiment: require ADX <= this (range regime)",
    )
    bt.add_argument(
        "--adx-split",
        type=float,
        default=None,
        help=f"ADX split for --signal regime (default {ADX_SPLIT_DEFAULT:g})",
    )
    bt.add_argument(
        "--di-align",
        action="store_true",
        help="Experiment: require +DI > −DI for longs (−DI > +DI for shorts)",
    )
    bt.add_argument(
        "--vol-halt",
        action="store_true",
        help="Experiment: skip entries when ATR%% is at/above its 200-bar 90th percentile",
    )
    bt.add_argument(
        "--vol-target",
        type=float,
        default=None,
        help="Experiment: scale qty by min(1, target / ATR%%) (e.g. 0.02)",
    )
    bt.add_argument(
        "--side",
        default=None,
        choices=list(SIDES),
        help="long (product/spot), short, or both. short/both are futures-like research only.",
    )
    bt.add_argument(
        "--fee-bps",
        type=float,
        default=None,
        help="Override FEE_BPS for this run (e.g. 3 for a maker sensitivity check)",
    )
    bt.add_argument(
        "--slip-bps",
        type=float,
        default=None,
        help="Override SLIPPAGE_BPS for this run",
    )
    bt.add_argument(
        "--funding-csv",
        default=None,
        help="Optional funding-rate CSV (timestamp,rate) used as a no-lookahead filter",
    )
    bt.add_argument(
        "--funding-max",
        type=float,
        default=None,
        help="Skip new longs when last completed funding exceeds this (e.g. 0.0001)",
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
        help="Evaluate the official ETH/USDT regime-20 paper signal + L2 book. "
        "Does not place orders. Does not enable live trading.",
    )
    paper.add_argument("--csv", default=None)
    paper.add_argument(
        "--public",
        action="store_true",
        help="Fetch the latest public candles via ccxt (no API key). Uses the profile entry TF.",
    )
    paper.add_argument("--cache-dir", default=None)
    paper.add_argument("--book", default=None, help="L2 JSON snapshot instead of a live fetch")
    paper.add_argument(
        "--no-book",
        action="store_true",
        help="Skip the L2 fetch (fails closed if ORDERBOOK_REQUIRE=true)",
    )
    paper.add_argument(
        "--profile",
        default=None,
        choices=sorted(PROFILES),
        help="Paper profile (default: PAPER_PROFILE / paper-eth). "
        "paper-eth and regime-20 are the locked ETH paper bundle.",
    )
    paper.add_argument(
        "--symbol",
        default=None,
        help="Spot symbol (default: profile pin or PAPER_SYMBOL / ETH/USDT for paper-eth)",
    )
    paper.add_argument(
        "--exchange",
        default=None,
        help="Cache / public-candle venue (default: EXCHANGE or ORDERBOOK_EXCHANGE)",
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

  Official paper profile (not the BTC backtest default): ETH/USDT regime-20.
    python -m alicia paper --profile paper-eth
  Paper evaluates the latest closed bar + L2 gate only. No orders. No live mode.

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


def _session_from_args(args) -> SessionWindow | None:
    preset_name = getattr(args, "session", None)
    profile_name = getattr(args, "profile", None)
    start_raw = getattr(args, "session_start", None)
    end_raw = getattr(args, "session_end", None)
    if preset_name:
        base = SESSION_PRESETS[preset_name]
    elif profile_name and profile_name in PROFILES and PROFILES[profile_name].session is not None:
        base = PROFILES[profile_name].session
    elif start_raw or end_raw:
        base = SESSION_PRESETS["us-primary"]
    else:
        return None
    assert base is not None
    start = parse_hhmm(start_raw) if start_raw else base.start_minute
    end = parse_hhmm(end_raw) if end_raw else base.end_minute
    weekdays = False if getattr(args, "all_days", False) else base.weekdays_only
    return SessionWindow(
        start,
        end,
        weekdays_only=weekdays,
        name=base.name,
        timezone=base.timezone,
        end_exclusive=base.end_exclusive if not (start_raw or end_raw) else False,
    )


def _apply_profile(args) -> str:
    """Mutate timeframe / RR from a named profile. Product default stays 1h/4h."""
    name = getattr(args, "profile", None) or "default"
    if name == "default":
        return name
    spec = PROFILES[name]
    if args.timeframe == "1h":
        args.timeframe = spec.entry_timeframe
    if spec.trend_timeframe and args.trend_timeframe is None:
        args.trend_timeframe = spec.trend_timeframe
    if spec.reward_risk is not None and args.reward_risk is None and args.tp_atr is None:
        args.reward_risk = spec.reward_risk
    if spec.stop_atr is not None and args.stop_atr is None:
        args.stop_atr = spec.stop_atr
    return name


def _resolve_paper_bundle(args, settings):
    """Official paper default is paper-eth (ETH/USDT regime-20). Not live."""
    name = getattr(args, "profile", None) or settings.paper_profile or "paper-eth"
    if name not in PROFILES:
        raise ValueError(f"Unknown paper profile: {name}")
    spec = PROFILES[name]
    if getattr(args, "symbol", None):
        symbol = args.symbol
    elif spec.symbol:
        symbol = spec.symbol
    elif name in {"paper-eth", "regime-20"}:
        symbol = settings.paper_symbol or "ETH/USDT"
    else:
        symbol = settings.symbol
    return spec, symbol


def _trend_tf(entry_tf: str, override: str | None) -> str:
    if override:
        return override
    return {"1m": "1h", "1h": "4h", "2h": "8h", "4h": "12h"}.get(entry_tf, "4h")


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
        if timeframe in {"1m", "2h", "4h"}:
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
        elif timeframe == "4h":
            print(
                "Experiment backtest: python -m alicia backtest "
                "--timeframe 4h --reward-risk 2"
            )
        return 0

    if args.command == "backtest":
        if getattr(args, "symbol", None):
            settings = replace(settings, symbol=args.symbol)
        if getattr(args, "exchange", None):
            settings = replace(settings, exchange_id=args.exchange)
        profile_name = _apply_profile(args)
        spec_bt = PROFILES.get(profile_name)
        if spec_bt is not None and spec_bt.symbol and not getattr(args, "symbol", None):
            settings = replace(settings, symbol=spec_bt.symbol)
        ohlcv, source = _resolve_ohlcv(args, settings)
        if ohlcv is None:
            return 2
        entry_tf = args.timeframe
        trend_tf = _trend_tf(entry_tf, args.trend_timeframe)
        try:
            stop_atr, tp_atr = _atr_multiples(args)
            session = _session_from_args(args)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        spec = PROFILES.get(profile_name, PROFILES["default"])
        extra = ExtraFilters(
            require_ema_slope=bool(getattr(args, "ema_slope", False)) or spec.extra.require_ema_slope,
            require_ema50=bool(getattr(args, "ema50", False)) or spec.extra.require_ema50,
            chop_filter=bool(getattr(args, "chop_filter", False)) or spec.extra.chop_filter,
            rsi_from=getattr(args, "rsi_from", None)
            if getattr(args, "rsi_from", None) is not None
            else spec.extra.rsi_from,
            adx_min=getattr(args, "adx_min", None)
            if getattr(args, "adx_min", None) is not None
            else spec.extra.adx_min,
            adx_max=getattr(args, "adx_max", None)
            if getattr(args, "adx_max", None) is not None
            else spec.extra.adx_max,
            adx_split=getattr(args, "adx_split", None)
            if getattr(args, "adx_split", None) is not None
            else spec.extra.adx_split,
            require_di_align=bool(getattr(args, "di_align", False)) or spec.extra.require_di_align,
            vol_halt=bool(getattr(args, "vol_halt", False)) or spec.extra.vol_halt,
            funding_max=getattr(args, "funding_max", None)
            if getattr(args, "funding_max", None) is not None
            else spec.extra.funding_max,
            funding_min=spec.extra.funding_min,
        )
        breakeven_r = getattr(args, "breakeven_r", None)
        if breakeven_r is None:
            breakeven_r = spec.breakeven_r
        signal = getattr(args, "signal", None) or spec.signal or "rsi"
        donchian_n = (
            int(args.donchian_n)
            if getattr(args, "donchian_n", None) is not None
            else spec.donchian_n
        )
        trail_atr = (
            float(args.trail_atr)
            if getattr(args, "trail_atr", None) is not None
            else spec.trail_atr
        )
        stop_mode = getattr(args, "stop_mode", None) or spec.stop_mode or "atr"
        trade_side = getattr(args, "side", None) or spec.side or "long"
        vol_target = (
            float(args.vol_target)
            if getattr(args, "vol_target", None) is not None
            else spec.vol_target
        )
        if getattr(args, "fee_bps", None) is not None:
            settings = replace(settings, fee_bps=float(args.fee_bps))
        if getattr(args, "slip_bps", None) is not None:
            settings = replace(settings, slippage_bps=float(args.slip_bps))
        funding_series = None
        if getattr(args, "funding_csv", None):
            fund_df = pd.read_csv(args.funding_csv)
            ts_col = "timestamp" if "timestamp" in fund_df.columns else fund_df.columns[0]
            rate_col = "rate" if "rate" in fund_df.columns else fund_df.columns[1]
            funding_series = pd.Series(
                fund_df[rate_col].astype("float64").values,
                index=pd.to_datetime(fund_df[ts_col], utc=True),
            )
        extras_on = (
            extra.require_ema_slope
            or extra.require_ema50
            or extra.chop_filter
            or extra.rsi_from is not None
            or breakeven_r
            or signal != "rsi"
            or trail_atr is not None
            or stop_mode != "atr"
            or extra.adx_min is not None
            or extra.adx_max is not None
            or extra.require_di_align
            or extra.vol_halt
            or vol_target is not None
            or trade_side != "long"
            or getattr(args, "fee_bps", None) is not None
        )
        if entry_tf == "1m":
            print(
                "EXPERIMENT: 1m entry / "
                f"{trend_tf} EMA200 trend. Product default remains 1h/4h. "
                "Order-book filters skipped (no historical L2)."
            )
        elif profile_name != "default" or session is not None or entry_tf in {
            "2h",
            "4h",
        } or args.reward_risk is not None or (
            args.tp_atr is not None and args.tp_atr != TP_ATR_MULT
        ) or extras_on:
            bits = []
            if extra.require_ema_slope:
                bits.append("ema-slope")
            if extra.require_ema50:
                bits.append("ema50")
            if extra.chop_filter:
                bits.append("chop-filter")
            if extra.rsi_from is not None:
                bits.append(f"rsi-from {extra.rsi_from:g}")
            if breakeven_r is not None:
                bits.append(f"BE@{breakeven_r:g}R")
            if signal != "rsi":
                bits.append(f"signal {signal}")
            if signal in {"breakout", "regime"}:
                bits.append(f"Donchian {donchian_n}")
            if signal == "regime":
                bits.append(f"ADX split {extra.adx_split:g}")
            if trail_atr is not None:
                bits.append(f"trail {trail_atr:g}×ATR")
            if stop_mode != "atr":
                bits.append(f"stop-mode {stop_mode}")
            if extra.adx_min is not None:
                bits.append(f"ADX>={extra.adx_min:g}")
            if extra.adx_max is not None:
                bits.append(f"ADX<={extra.adx_max:g}")
            if extra.require_di_align:
                bits.append("DI-align")
            if extra.vol_halt:
                bits.append("vol-halt")
            if vol_target is not None:
                bits.append(f"vol-target {vol_target:g}")
            if trade_side != "long":
                bits.append(f"side {trade_side}")
            if getattr(args, "fee_bps", None) is not None:
                bits.append(f"fee {settings.fee_bps:g}bps")
            exits = (
                f"stop {stop_atr:g}×ATR / trail {trail_atr:g}×ATR (no fixed TP)"
                if trail_atr is not None
                else (
                    f"stop {stop_atr:g}×ATR / TP {tp_atr:g}×ATR "
                    f"(RR 1:{tp_atr / stop_atr:g})"
                )
            )
            print(
                f"EXPERIMENT: profile={profile_name} / {entry_tf} entry / "
                f"{trend_tf} EMA200 / {exits}"
                + (f" / {session.label}" if session else "")
                + (f" / extras: {', '.join(bits)}" if bits else "")
                + ". Product default remains 1h/4h 24/7 RSI with TP=2×ATR. "
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
            session=session,
            profile=profile_name,
            extra=extra,
            breakeven_r=breakeven_r,
            signal=signal,
            donchian_n=donchian_n,
            trail_atr=trail_atr,
            stop_mode=stop_mode,
            side=trade_side,
            vol_target=vol_target,
            funding=funding_series,
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
        try:
            spec, symbol = _resolve_paper_bundle(args, settings)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if getattr(args, "exchange", None):
            settings = replace(settings, exchange_id=args.exchange)
        settings = replace(settings, symbol=symbol)
        entry_tf = spec.entry_timeframe
        if args.csv:
            ohlcv = load_paper_ohlcv(settings, csv_path=args.csv, symbol=symbol)
        elif args.public:
            try:
                ohlcv = load_paper_ohlcv(
                    settings,
                    use_public=True,
                    timeframe=entry_tf,
                    symbol=symbol,
                )
            except Exception as exc:
                print(f"Public candle fetch failed: {exc}", file=sys.stderr)
                return 1
        else:
            path = resolve_or_resample(
                settings.exchange_id,
                symbol,
                entry_tf,
                cache_dir(args.cache_dir),
            )
            if path is None:
                preferred = cache_csv_path(
                    settings.exchange_id, symbol, entry_tf, cache_dir(args.cache_dir)
                )
                print(
                    f"No cached {symbol} {entry_tf} at {preferred}\n"
                    "Download public history (no API key), then re-run paper:\n"
                    f"  python -m alicia download --exchange okx --symbol {symbol} "
                    f"--timeframe {entry_tf} --years 2\n"
                    "  python -m alicia paper --profile paper-eth\n"
                    "Or: python -m alicia paper --profile paper-eth --public",
                    file=sys.stderr,
                )
                return 2
            ohlcv = read_cache(path)
        book = None
        book_venue = None
        if args.book:
            book = load_book_json(args.book)
            book_venue = f"fixture:{args.book}"
        elif not args.no_book and settings.orderbook_enabled:
            try:
                book, used = fetch_public_order_book_with_fallback(
                    settings.orderbook_venue,
                    symbol,
                    limit=settings.orderbook_limit,
                )
                book_venue = used
            except Exception as exc:
                print(f"Public L2 fetch failed: {exc}", file=sys.stderr)
                book = None
                book_venue = None
        snap = evaluate_latest(
            ohlcv,
            settings,
            book=book,
            book_venue=book_venue,
            profile=spec,
            symbol=symbol,
        )
        official = spec.name in {"paper-eth", "regime-20"}
        print("Alicia paper snapshot — PAPER ONLY (no order sent, live trading disabled)")
        print(
            f"  profile:    {spec.name}"
            + ("  [official ETH regime-20 paper]" if official else "")
        )
        print(f"  symbol:     {symbol}")
        print(f"  timeframes: entry {spec.entry_timeframe} / trend EMA200 {spec.trend_timeframe}")
        print(f"  signal:     {spec.signal}  ADX split {spec.extra.adx_split:g}")
        print(f"  time:       {snap.timestamp}")
        print(f"  price:      {snap.price:.2f}")
        print(f"  EMA200:     {snap.ema200_4h}")
        print(f"  ADX 14:     {snap.adx}")
        print(f"  RSI 14:     {snap.prev_rsi} → {snap.rsi}")
        print(f"  volume:     {snap.volume:.2f} vs MA20 {snap.volume_ma}")
        print(f"  ATR 14:     {snap.atr}")
        print(f"  stop/tp:    {snap.stop} / {snap.take_profit}")
        _print_book_section(snap)
        print(f"  decision:   {'ENTER LONG' if snap.decision.enter else 'NO ENTRY'}")
        print(f"  reason:     {snap.decision.reason}")
        if official:
            print(
                "  note:       Locked paper profile. Same rules lose on BTC. "
                "OOS is thin. See docs/BACKTEST.md § Potential search."
            )
        book_missing = settings.orderbook_enabled and settings.orderbook_require and (
            snap.book is None
            or (not snap.book.ok and "unavailable" in (snap.book.reason or ""))
        )
        if book_missing:
            print("Fail closed: no new LONG while L2 is missing or required.", file=sys.stderr)
            return 2
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
