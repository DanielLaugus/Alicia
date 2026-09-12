"""Public OHLCV download and local cache. Never needs private keys."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from alicia.indicators import resample_ohlcv_4h
from alicia.sample_data import generate_sample_ohlcv, ohlcv_from_csv, ohlcv_to_csv

OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
DEFAULT_CACHE_DIR = Path("data/cache")
DEFAULT_TIMEFRAME = "1h"
PAGE_LIMIT = 1000
TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}

FetchFn = Callable[[str, str, int | None, int], list]

# Tried in order when the preferred venue geo-blocks public history (no keys).
PUBLIC_FALLBACKS = (
    "binance",
    "okx",
    "kucoin",
    "gate",
    "bitstamp",
    "mexc",
    "bitfinex",
    "htx",
)


def cache_dir(path: str | Path | None = None) -> Path:
    raw = path or os.getenv("DATA_CACHE_DIR") or DEFAULT_CACHE_DIR
    return Path(raw)


def cache_csv_path(
    exchange_id: str,
    symbol: str,
    timeframe: str = DEFAULT_TIMEFRAME,
    directory: str | Path | None = None,
) -> Path:
    safe_symbol = symbol.replace("/", "").replace(":", "")
    return cache_dir(directory) / f"{exchange_id}_{safe_symbol}_{timeframe}.csv"


def cache_meta_path(csv_path: Path) -> Path:
    return csv_path.with_suffix(".meta.json")


def active_pointer_path(directory: str | Path | None = None) -> Path:
    return cache_dir(directory) / "active.json"


def write_active_pointer(
    *,
    exchange_id: str,
    symbol: str,
    timeframe: str,
    csv_path: Path,
    directory: str | Path | None = None,
) -> None:
    pointer = active_pointer_path(directory)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps(
            {
                "exchange": exchange_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "csv": str(csv_path),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def resolve_cached_1h(
    exchange_id: str,
    symbol: str,
    directory: str | Path | None = None,
) -> Path | None:
    """Preferred cache, then the last successful download pointer, then a unique match."""
    directory = cache_dir(directory)
    preferred = cache_csv_path(exchange_id, symbol, "1h", directory)
    if preferred.exists():
        return preferred
    pointer = active_pointer_path(directory)
    if pointer.exists():
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        candidate = Path(payload.get("csv", ""))
        if candidate.exists():
            return candidate
    safe = symbol.replace("/", "").replace(":", "")
    matches = sorted(directory.glob(f"*_{safe}_1h.csv"))
    if len(matches) == 1:
        return matches[0]
    return None


def bars_to_frame(raw: Iterable[list]) -> pd.DataFrame:
    rows = list(raw)
    if not rows:
        return pd.DataFrame(columns=list(OHLCV_COLUMNS))
    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame = frame.set_index("timestamp")
    return _normalize_ohlcv(frame)


def _normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    missing = set(OHLCV_COLUMNS) - set(out.columns)
    if missing:
        raise ValueError(f"OHLCV missing columns: {sorted(missing)}")
    out = out.loc[:, list(OHLCV_COLUMNS)].astype("float64")
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.dropna(subset=["open", "high", "low", "close"])


def merge_ohlcv(*frames: pd.DataFrame) -> pd.DataFrame:
    parts = [_normalize_ohlcv(f) for f in frames if f is not None and not f.empty]
    if not parts:
        return pd.DataFrame(columns=list(OHLCV_COLUMNS))
    return _normalize_ohlcv(pd.concat(parts))


def drop_incomplete_last_bar(
    frame: pd.DataFrame,
    timeframe: str = DEFAULT_TIMEFRAME,
    *,
    now: datetime | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    ms = TIMEFRAME_MS[timeframe]
    current = now or datetime.now(timezone.utc)
    last = frame.index[-1].to_pydatetime()
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last + timedelta(milliseconds=ms) > current:
        return frame.iloc[:-1]
    return frame


def resolve_since_ms(*, years: float = 2.0, since: str | None = None) -> int:
    if since:
        return int(pd.Timestamp(since, tz="UTC").timestamp() * 1000)
    start = datetime.now(timezone.utc) - timedelta(days=int(years * 365))
    return int(start.timestamp() * 1000)


def resolve_until_ms(until: str | None = None) -> int:
    if until:
        return int(pd.Timestamp(until, tz="UTC").timestamp() * 1000)
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _public_exchange(exchange_id: str):
    try:
        import ccxt  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "ccxt is not installed. Run: pip install 'alicia[exchange]'"
        ) from exc
    if not hasattr(ccxt, exchange_id):
        raise ValueError(f"Unknown ccxt exchange id: {exchange_id}")
    cls = getattr(ccxt, exchange_id)
    # Public market data only — never attach API keys here.
    return cls({"enableRateLimit": True, "timeout": 30_000})


def make_ccxt_fetch(exchange_id: str) -> FetchFn:
    """One public client for the whole pagination loop (keeps rate-limit state)."""
    exchange = _public_exchange(exchange_id)

    def _fetch(symbol: str, timeframe: str, since_ms: int | None, limit: int) -> list:
        return exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)

    return _fetch


def ccxt_fetch(
    exchange_id: str,
    symbol: str,
    timeframe: str,
    since_ms: int | None,
    limit: int,
) -> list:
    return make_ccxt_fetch(exchange_id)(symbol, timeframe, since_ms, limit)


def paginate_ohlcv(
    *,
    symbol: str,
    timeframe: str = DEFAULT_TIMEFRAME,
    since_ms: int,
    until_ms: int | None = None,
    limit: int = PAGE_LIMIT,
    fetch: FetchFn,
    on_page: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    if timeframe not in TIMEFRAME_MS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    step = TIMEFRAME_MS[timeframe]
    cursor = since_ms
    end = until_ms or resolve_until_ms()
    chunks: list[list] = []
    last_seen = -1
    while cursor < end:
        batch = fetch(symbol, timeframe, cursor, limit)
        if not batch:
            break
        if batch[-1][0] <= last_seen:
            break
        chunks.extend(batch)
        last_seen = batch[-1][0]
        cursor = last_seen + step
        if on_page is not None:
            on_page(len(chunks), last_seen)
        # A short page is often the venue max (OKX=300), not the end of history.
        if cursor >= end:
            break
    frame = bars_to_frame(chunks)
    if frame.empty:
        return frame
    end_ts = pd.Timestamp(end, unit="ms", tz="UTC")
    return frame.loc[frame.index <= end_ts]


@dataclass
class CacheMeta:
    exchange: str
    symbol: str
    timeframe: str
    rows: int
    first: str | None
    last: str | None
    fetched_at: str
    source: str = "ccxt-public"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2) + "\n"


def write_cache(frame: pd.DataFrame, csv_path: Path, meta: CacheMeta) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    ohlcv_to_csv(frame, csv_path)
    cache_meta_path(csv_path).write_text(meta.to_json(), encoding="utf-8")


def read_cache(csv_path: Path) -> pd.DataFrame:
    return ohlcv_from_csv(csv_path)


def _meta_for(frame: pd.DataFrame, exchange_id: str, symbol: str, timeframe: str) -> CacheMeta:
    first = last = None
    if not frame.empty:
        first = str(frame.index[0])
        last = str(frame.index[-1])
    return CacheMeta(
        exchange=exchange_id,
        symbol=symbol,
        timeframe=timeframe,
        rows=int(len(frame)),
        first=first,
        last=last,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def download_ohlcv(
    *,
    exchange_id: str = "binance",
    symbol: str = "BTC/USDT",
    timeframe: str = DEFAULT_TIMEFRAME,
    years: float = 2.0,
    since: str | None = None,
    until: str | None = None,
    directory: str | Path | None = None,
    force: bool = False,
    fetch: FetchFn | None = None,
    derive_4h: bool = True,
    on_page: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """Download public spot OHLCV and persist under the cache directory.

    Incremental: if a cache file exists and ``force`` is false, only bars after
    the last cached timestamp are requested, then merged.
    """
    path = cache_csv_path(exchange_id, symbol, timeframe, directory)
    existing = read_cache(path) if path.exists() and not force else None
    if existing is not None and not existing.empty and since is None:
        last = existing.index[-1]
        since_ms = int(last.timestamp() * 1000) + TIMEFRAME_MS[timeframe]
    else:
        since_ms = resolve_since_ms(years=years, since=since)
    until_ms = resolve_until_ms(until)

    if existing is not None and not existing.empty and since_ms >= until_ms:
        return drop_incomplete_last_bar(existing, timeframe)

    worker: FetchFn = fetch if fetch is not None else make_ccxt_fetch(exchange_id)

    fresh = paginate_ohlcv(
        symbol=symbol,
        timeframe=timeframe,
        since_ms=since_ms,
        until_ms=until_ms,
        fetch=worker,
        on_page=on_page,
    )
    combined = merge_ohlcv(existing, fresh) if existing is not None else fresh
    combined = drop_incomplete_last_bar(combined, timeframe)
    if combined.empty:
        raise RuntimeError(
            f"No public OHLCV returned for {symbol} on {exchange_id} {timeframe}."
        )
    write_cache(combined, path, _meta_for(combined, exchange_id, symbol, timeframe))
    if derive_4h and timeframe == "1h":
        h4 = resample_ohlcv_4h(combined)
        h4_path = cache_csv_path(exchange_id, symbol, "4h", directory)
        write_cache(h4, h4_path, _meta_for(h4, exchange_id, symbol, "4h"))
    write_active_pointer(
        exchange_id=exchange_id,
        symbol=symbol,
        timeframe=timeframe,
        csv_path=path,
        directory=directory,
    )
    return combined


def history_covers_request(
    frame: pd.DataFrame,
    *,
    years: float,
    since: str | None,
    until: str | None = None,
) -> bool:
    """Reject venues that ignore ``since`` or stop after one short page."""
    if frame.empty:
        return False
    end = pd.Timestamp(until, tz="UTC") if until else pd.Timestamp.now(tz="UTC")
    start = (
        pd.Timestamp(since, tz="UTC")
        if since
        else end - pd.Timedelta(days=int(years * 365))
    )
    first_gap = frame.index[0] - start
    last_gap = end - frame.index[-1]
    return first_gap <= pd.Timedelta(days=14) and last_gap <= pd.Timedelta(days=7)


def download_ohlcv_with_fallback(
    *,
    exchange_id: str = "binance",
    symbol: str = "BTC/USDT",
    years: float = 2.0,
    since: str | None = None,
    until: str | None = None,
    directory: str | Path | None = None,
    force: bool = False,
    fallbacks: tuple[str, ...] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_try: Callable[[str], None] | None = None,
    on_skip: Callable[[str, str], None] | None = None,
) -> tuple[pd.DataFrame, str]:
    """Try the preferred public venue, then others that honor historical ``since``."""
    chain: list[str] = []
    for name in (exchange_id, *(fallbacks if fallbacks is not None else PUBLIC_FALLBACKS)):
        if name not in chain:
            chain.append(name)
    errors: list[str] = []
    for name in chain:
        if on_try:
            on_try(name)
        try:
            frame = download_ohlcv(
                exchange_id=name,
                symbol=symbol,
                years=years,
                since=since,
                until=until,
                directory=directory,
                force=force,
                on_page=on_page,
            )
        except Exception as exc:
            if on_skip:
                on_skip(name, str(exc))
            errors.append(f"{name}: {exc}")
            continue
        if not history_covers_request(frame, years=years, since=since, until=until):
            msg = (
                f"only {len(frame)} bars "
                f"({frame.index[0]} → {frame.index[-1]}); venue likely ignores since"
            )
            if on_skip:
                on_skip(name, msg)
            errors.append(f"{name}: {msg}")
            continue
        return frame, name
    raise RuntimeError(
        "No public venue returned enough historical OHLCV.\n" + "\n".join(errors)
    )


def load_ohlcv(
    csv_path: str | Path | None = None,
    *,
    synthetic: bool = False,
) -> pd.DataFrame:
    if csv_path:
        return ohlcv_from_csv(csv_path)
    if synthetic:
        return generate_sample_ohlcv()
    raise FileNotFoundError(
        "No OHLCV path given. Pass a CSV, use synthetic=True, or download a cache."
    )


def fetch_public_ohlcv(
    symbol: str = "BTC/USDT",
    exchange_id: str = "binance",
    timeframe: str = "1h",
    limit: int = 1000,
) -> pd.DataFrame:
    """Recent public candles (no key). Prefer download_ohlcv for multi-year history."""
    raw = ccxt_fetch(exchange_id, symbol, timeframe, None, limit)
    return drop_incomplete_last_bar(bars_to_frame(raw), timeframe)
