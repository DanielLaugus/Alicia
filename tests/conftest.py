from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from alicia.config import Settings
from alicia.sample_data import generate_sample_ohlcv


@pytest.fixture
def settings() -> Settings:
    return Settings(
        symbol="BTC/USDT",
        exchange_id="binance",
        capital_eur=2000.0,
        risk_pct=0.02,
        max_small_notional_eur=200.0,
        usdt_eur_rate=1.0,
        fee_bps=10.0,
        slippage_bps=5.0,
        monthly_dd_halt=0.10,
        pause_cpi=False,
        pause_fed=False,
        pause_nfp=False,
        events_path=None,
        mode="backtest",
        api_key="",
        api_secret="",
        api_latency_ms_limit=5000,
        orderbook_enabled=False,
        orderbook_require=False,
        orderbook_in_backtest=False,
        orderbook_max_spread_bps=5.0,
        orderbook_levels=10,
        orderbook_imbalance_min=0.0,
        orderbook_min_bid_depth=1.0,
        orderbook_depth_bps=10.0,
        orderbook_limit=20,
        orderbook_exchange="",
    )


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    return generate_sample_ohlcv()


def utc(y, m, d, h=0) -> datetime:
    return datetime(y, m, d, h, tzinfo=timezone.utc)
