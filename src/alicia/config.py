"""Environment-driven settings. No secrets belong in the repo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

MIN_RISK_PCT = 0.01
MAX_RISK_PCT = 0.03


def _as_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _as_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _as_path(name: str, default: str | None) -> Path | None:
    raw = os.getenv(name, default)
    if raw is None or raw.strip() == "":
        return None
    return Path(raw)


@dataclass(frozen=True)
class Settings:
    symbol: str
    exchange_id: str
    capital_eur: float
    risk_pct: float
    max_small_notional_eur: float
    usdt_eur_rate: float
    fee_bps: float
    slippage_bps: float
    monthly_dd_halt: float
    pause_cpi: bool
    pause_fed: bool
    pause_nfp: bool
    events_path: Path | None
    mode: str
    api_key: str
    api_secret: str
    api_latency_ms_limit: int
    orderbook_enabled: bool
    orderbook_require: bool
    orderbook_in_backtest: bool
    orderbook_max_spread_bps: float
    orderbook_levels: int
    orderbook_imbalance_min: float
    orderbook_min_bid_depth: float
    orderbook_depth_bps: float
    orderbook_limit: int
    orderbook_exchange: str

    @property
    def risk_pct_clamped(self) -> float:
        return min(max(self.risk_pct, MIN_RISK_PCT), MAX_RISK_PCT)

    @property
    def fee_rate(self) -> float:
        return self.fee_bps / 10_000.0

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000.0

    def notional_eur(self, quote_notional_usdt: float) -> float:
        return quote_notional_usdt * self.usdt_eur_rate

    @property
    def orderbook_venue(self) -> str:
        return self.orderbook_exchange or self.exchange_id


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    if env_file:
        path = Path(env_file)
        if path.exists():
            load_dotenv(path)
        elif Path(".env").exists():
            load_dotenv(".env")
    else:
        load_dotenv()

    return Settings(
        symbol=os.getenv("SYMBOL", "BTC/USDT"),
        exchange_id=os.getenv("EXCHANGE", "binance"),
        capital_eur=_as_float("BOT_CAPITAL_EUR", 2000.0),
        risk_pct=_as_float("RISK_PCT", 0.02),
        max_small_notional_eur=_as_float("MAX_SMALL_NOTIONAL_EUR", 200.0),
        usdt_eur_rate=_as_float("USDT_EUR_RATE", 1.0),
        fee_bps=_as_float("FEE_BPS", 10.0),
        slippage_bps=_as_float("SLIPPAGE_BPS", 5.0),
        monthly_dd_halt=_as_float("MONTHLY_DD_HALT", 0.10),
        pause_cpi=_as_bool("PAUSE_CPI", True),
        pause_fed=_as_bool("PAUSE_FED", True),
        pause_nfp=_as_bool("PAUSE_NFP", True),
        events_path=_as_path("EVENTS_PATH", "data/events.example.json"),
        mode=os.getenv("ALICIA_MODE", "backtest").strip().lower(),
        api_key=os.getenv("EXCHANGE_API_KEY", "").strip(),
        api_secret=os.getenv("EXCHANGE_API_SECRET", "").strip(),
        api_latency_ms_limit=_as_int("API_LATENCY_MS_LIMIT", 5000),
        orderbook_enabled=_as_bool("ORDERBOOK_ENABLED", True),
        orderbook_require=_as_bool("ORDERBOOK_REQUIRE", True),
        orderbook_in_backtest=_as_bool("ORDERBOOK_IN_BACKTEST", False),
        orderbook_max_spread_bps=_as_float("ORDERBOOK_MAX_SPREAD_BPS", 5.0),
        orderbook_levels=_as_int("ORDERBOOK_LEVELS", 10),
        orderbook_imbalance_min=_as_float("ORDERBOOK_IMBALANCE_MIN", 0.0),
        orderbook_min_bid_depth=_as_float("ORDERBOOK_MIN_BID_DEPTH", 1.0),
        orderbook_depth_bps=_as_float("ORDERBOOK_DEPTH_BPS", 10.0),
        orderbook_limit=_as_int("ORDERBOOK_LIMIT", 20),
        orderbook_exchange=os.getenv("ORDERBOOK_EXCHANGE", "").strip(),
    )
