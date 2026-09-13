"""Skeptical re-test of ETH/USDT regime-20. Read-only research; no orders."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from alicia.backtest import apply_buy_slippage, apply_sell_slippage, run_backtest
from alicia.config import load_settings
from alicia.data import drop_incomplete_last_bar, read_cache
from alicia.indicators import TREND_COMPLETE, attach_indicators, donchian_prior_high, ema, resample_ohlcv
from alicia.risk import size_from_settings
from alicia.session import PROFILES
from alicia.strategy import ExtraFilters, take_profit_price

CACHE = Path("data/cache")
OUT = Path("/tmp/retest_eth_regime20.json")
SPLIT_MID = pd.Timestamp("2025-09-12", tz="UTC")
SPLITS = {
    "mid-2025-09-12": SPLIT_MID,
    "2025-06-01": pd.Timestamp("2025-06-01", tz="UTC"),
    "2025-12-01": pd.Timestamp("2025-12-01", tz="UTC"),
}
LAST_6M = pd.Timestamp("2026-03-13", tz="UTC")


def _compact(result) -> dict:
    s = result.summary()
    keep = (
        "trades",
        "open_at_end",
        "wins",
        "losses",
        "win_rate_pct",
        "return_pct",
        "max_drawdown_pct",
        "end_equity",
        "pnl_usdt",
        "fees_usdt",
        "slippage_usdt",
        "zero_cost_end_equity",
        "halt_events",
        "bars",
        "first_bar",
        "last_bar",
        "signal",
        "profile",
    )
    out = {k: s[k] for k in keep}
    if s.get("zero_cost_end_equity") and result.start_capital:
        out["zero_cost_return_pct"] = round(
            (s["zero_cost_end_equity"] / result.start_capital - 1.0) * 100.0, 4
        )
    return out


def _run(ohlcv, settings, *, profile, signal=None, extra=None, fee=None, slip=None, **kwargs):
    spec = PROFILES[profile] if isinstance(profile, str) else profile
    cfg = settings
    if fee is not None or slip is not None:
        cfg = replace(
            settings,
            fee_bps=settings.fee_bps if fee is None else fee,
            slippage_bps=settings.slippage_bps if slip is None else slip,
        )
    stop = spec.stop_atr or 1.5
    rr = spec.reward_risk if spec.reward_risk is not None else (2.0 / 1.5)
    tp = stop * float(rr) if spec.reward_risk is not None else 2.0
    return run_backtest(
        ohlcv,
        cfg,
        source="retest",
        entry_timeframe=spec.entry_timeframe,
        trend_timeframe=spec.trend_timeframe,
        stop_atr_mult=stop,
        tp_atr_mult=tp,
        session=spec.session,
        profile=spec.name,
        extra=extra if extra is not None else spec.extra,
        signal=signal or spec.signal,
        donchian_n=spec.donchian_n,
        trail_atr=spec.trail_atr,
        stop_mode=spec.stop_mode or "atr",
        side=spec.side or "long",
        **kwargs,
    )


def _buy_hold(ohlcv: pd.DataFrame) -> dict:
    first = float(ohlcv["close"].iloc[0])
    last = float(ohlcv["close"].iloc[-1])
    return {
        "first_close": first,
        "last_close": last,
        "return_pct": round((last / first - 1.0) * 100.0, 4),
        "max_close": float(ohlcv["close"].max()),
        "min_close": float(ohlcv["close"].min()),
    }


def _lookahead_audit(ohlcv: pd.DataFrame) -> dict:
    now = datetime.now(timezone.utc)
    last = ohlcv.index[-1].to_pydatetime()
    unfinished = last + pd.Timedelta(hours=4) > now
    frame = attach_indicators(ohlcv, trend_timeframe="12h", donchian_n=20)
    # Donchian must exclude the current bar.
    independent = donchian_prior_high(ohlcv["high"], 20)
    donch_ok = bool(
        np.allclose(
            frame["donchian_high"].dropna(),
            independent.reindex(frame.index).dropna(),
            equal_nan=True,
        )
    )
    # Completed 12h EMA: a 4h bar at T must not see a 12h candle that closes after T.
    trend = resample_ohlcv(ohlcv, "12h")
    trend["ema200"] = ema(trend["close"], 200)
    complete = trend.copy()
    complete.index = complete.index + TREND_COMPLETE["12h"]
    leak_count = 0
    checked = 0
    for ts in frame.index[:: max(len(frame) // 80, 1)]:
        ema_v = frame.loc[ts, "ema200_4h"]
        if pd.isna(ema_v):
            continue
        visible = complete.loc[complete.index <= ts, "ema200"]
        if visible.empty:
            continue
        checked += 1
        if abs(float(visible.iloc[-1]) - float(ema_v)) > 1e-8:
            leak_count += 1
        # Any 12h bar whose close is after T must be invisible.
        future = complete.loc[complete.index > ts, "ema200"]
        if not future.empty and abs(float(future.iloc[0]) - float(ema_v)) < 1e-12:
            # Equal by chance is ok; leak if it matches a not-yet-complete value
            # that differs from the last visible. Already covered by visible check.
            pass
    # Prefix vs full-series causality on a sample of bars (ADX / RSI / Donchian).
    rng = np.random.default_rng(7)
    idxs = rng.choice(np.arange(400, len(ohlcv) - 10), size=12, replace=False)
    prefix_mismatch = []
    for i in sorted(idxs.tolist()):
        prefix = attach_indicators(ohlcv.iloc[: i + 1], trend_timeframe="12h", donchian_n=20)
        ts = ohlcv.index[i]
        for col in ("adx_14", "rsi_14", "donchian_high", "ema200_4h", "atr_14"):
            a = prefix.iloc[-1][col]
            b = frame.loc[ts, col]
            if pd.isna(a) and pd.isna(b):
                continue
            if pd.isna(a) or pd.isna(b) or abs(float(a) - float(b)) > 1e-6:
                prefix_mismatch.append(
                    {"bar": str(ts), "col": col, "prefix": None if pd.isna(a) else float(a), "full": None if pd.isna(b) else float(b)}
                )
    return {
        "last_bar": str(ohlcv.index[-1]),
        "now_utc": now.isoformat(),
        "unfinished_last_bar": unfinished,
        "donchian_excludes_current_bar": donch_ok,
        "ema200_matches_completed_12h": leak_count == 0,
        "ema200_checked_bars": checked,
        "prefix_vs_full_mismatches": prefix_mismatch[:8],
        "prefix_mismatch_count": len(prefix_mismatch),
        "gaps_gt_4h": int((ohlcv.index.to_series().diff() > pd.Timedelta(hours=4)).sum()),
    }


def _overlap_check(result) -> dict:
    overlaps = 0
    prev = None
    fills_next_open = 0
    fills_checked = 0
    for t in result.trades:
        if prev is not None and prev.exit_time is not None and t.entry_time < prev.exit_time:
            overlaps += 1
        prev = t
        if t.signal_time is not None and t.entry_time is not None:
            fills_checked += 1
            if t.entry_time > t.signal_time:
                fills_next_open += 1
    return {
        "overlapping_positions": overlaps,
        "fills_after_signal": fills_next_open,
        "fills_checked": fills_checked,
        "same_bar_fills": fills_checked - fills_next_open,
    }


def _random_baseline(
    ohlcv, settings, n_signals: int, seeds: int = 40, strategy_return: float | None = None
) -> dict:
    """Same engine costs/stops, random entries on indicator-ready bars, one position."""
    spec = PROFILES["regime-20"]
    frame = attach_indicators(ohlcv, trend_timeframe="12h", donchian_n=20)
    ready = [
        i
        for i in range(len(frame) - 1)
        if not pd.isna(frame.iloc[i]["ema200_4h"])
        and not pd.isna(frame.iloc[i]["atr_14"])
        and float(frame.iloc[i]["atr_14"]) > 0
    ]
    if n_signals <= 0 or len(ready) < n_signals:
        return {"error": "not enough ready bars", "ready": len(ready)}
    fee = settings.fee_rate
    slip = settings.slippage_rate
    returns = []
    rng_master = np.random.default_rng(20260913)
    for _ in range(seeds):
        chosen = set(int(x) for x in rng_master.choice(ready, size=n_signals, replace=False))
        cash = float(settings.capital_eur)
        qty = 0.0
        pos = None
        pending = None
        peak = cash
        max_dd = 0.0
        for i in range(len(frame)):
            row = frame.iloc[i]
            mark = float(row["close"])
            equity = cash + qty * mark
            peak = max(peak, equity)
            max_dd = min(max_dd, (equity - peak) / peak if peak else 0.0)
            if pending is not None and pos is None:
                raw = float(row["open"])
                fill = apply_buy_slippage(raw, slip)
                stop = fill - 1.5 * pending["atr"]
                take = take_profit_price(fill, pending["atr"], atr_mult=3.0)
                trade_qty = size_from_settings(
                    settings, entry_price=fill, stop=stop, capital_eur=equity, available_quote=cash
                )
                if trade_qty > 0:
                    entry_fee = fill * trade_qty * fee
                    cash -= fill * trade_qty + entry_fee
                    qty = trade_qty
                    pos = {
                        "fill": fill,
                        "stop": stop,
                        "take": take,
                        "qty": trade_qty,
                        "fees": entry_fee,
                    }
                pending = None
            if pos is not None:
                low, high = float(row["low"]), float(row["high"])
                exit_px = None
                if low <= pos["stop"]:
                    exit_px = apply_sell_slippage(pos["stop"], slip)
                elif high >= pos["take"]:
                    exit_px = apply_sell_slippage(pos["take"], slip)
                if exit_px is not None:
                    exit_fee = exit_px * pos["qty"] * fee
                    cash += exit_px * pos["qty"] - exit_fee
                    qty = 0.0
                    pos = None
            if i in chosen and pos is None and pending is None:
                pending = {"atr": float(row["atr_14"])}
        last = float(frame["close"].iloc[-1])
        end = cash + qty * last
        returns.append((end / settings.capital_eur - 1.0) * 100.0)
    arr = np.array(returns)
    return {
        "seeds": seeds,
        "signals_per_seed": n_signals,
        "ready_bars": len(ready),
        "mean_return_pct": round(float(arr.mean()), 4),
        "median_return_pct": round(float(np.median(arr)), 4),
        "p10_return_pct": round(float(np.percentile(arr, 10)), 4),
        "p90_return_pct": round(float(np.percentile(arr, 90)), 4),
        "min_return_pct": round(float(arr.min()), 4),
        "max_return_pct": round(float(arr.max()), 4),
        "share_gt_strategy": (
            None
            if strategy_return is None
            else round(float((arr > strategy_return).mean()), 4)
        ),
    }


def main() -> None:
    settings = load_settings(env_file=None)
    settings = replace(settings, symbol="ETH/USDT", exchange_id="okx", fee_bps=10.0, slippage_bps=5.0)
    eth4 = drop_incomplete_last_bar(read_cache(CACHE / "okx_ETHUSDT_4h.csv"), "4h")
    eth1 = drop_incomplete_last_bar(read_cache(CACHE / "okx_ETHUSDT_1h.csv"), "1h")
    btc4 = drop_incomplete_last_bar(read_cache(CACHE / "okx_BTCUSDT_4h.csv"), "4h")
    meta = json.loads((CACHE / "okx_ETHUSDT_4h.meta.json").read_text())

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "venue": "okx",
            "symbol": "ETH/USDT",
            "timeframe": "4h",
            "bars": int(len(eth4)),
            "first": str(eth4.index[0]),
            "last": str(eth4.index[-1]),
            "meta": meta,
            "eth_1h_bars": int(len(eth1)),
            "eth_1h_range": [str(eth1.index[0]), str(eth1.index[-1])],
            "btc_4h_bars": int(len(btc4)),
            "btc_4h_range": [str(btc4.index[0]), str(btc4.index[-1])],
            "buy_hold_eth_4h": _buy_hold(eth4),
        },
    }

    base = _run(eth4, settings, profile="regime-20", compare_zero_cost=True)
    report["base_10_5"] = _compact(base)
    report["overlap"] = _overlap_check(base)

    splits = {}
    for name, cut in SPLITS.items():
        train = _run(eth4, settings, profile="regime-20", entry_until=cut)
        oos = _run(eth4, settings, profile="regime-20", entry_from=cut)
        splits[name] = {"train": _compact(train), "oos": _compact(oos)}
    splits["last_6m_from_2026-03-13"] = {
        "oos": _compact(_run(eth4, settings, profile="regime-20", entry_from=LAST_6M))
    }
    report["splits"] = splits

    rsi_4h = ExtraFilters()  # product RSI gates only
    report["ablations_same_4h"] = {
        "regime-20": report["base_10_5"],
        "breakout_only": _compact(_run(eth4, settings, profile="breakout")),
        "rsi_only_rr2": _compact(
            _run(eth4, settings, profile="regime-20", signal="rsi", extra=rsi_4h)
        ),
    }
    report["eth_product_rsi_1h"] = _compact(
        run_backtest(
            eth1,
            settings,
            source="retest-1h",
            entry_timeframe="1h",
            trend_timeframe="4h",
            stop_atr_mult=1.5,
            tp_atr_mult=2.0,
            profile="default",
            extra=ExtraFilters(),
            signal="rsi",
        )
    )
    report["btc_regime-20"] = _compact(_run(btc4, replace(settings, symbol="BTC/USDT"), profile="regime-20"))

    report["fee_stress"] = {
        "10_5": report["base_10_5"],
        "15_10": _compact(_run(eth4, settings, profile="regime-20", fee=15.0, slip=10.0)),
        "2_2": _compact(_run(eth4, settings, profile="regime-20", fee=2.0, slip=2.0)),
    }

    report["lookahead"] = _lookahead_audit(eth4)
    n_sig = max(len(base.trades), report["base_10_5"]["trades"])
    rnd = _random_baseline(
        eth4,
        settings,
        n_signals=n_sig,
        seeds=40,
        strategy_return=report["base_10_5"]["return_pct"],
    )
    if "mean_return_pct" in rnd:
        rnd["strategy_return_pct"] = report["base_10_5"]["return_pct"]
        rnd["beats_random_mean"] = report["base_10_5"]["return_pct"] > rnd["mean_return_pct"]
    report["random_entry_baseline"] = rnd

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
