# Real-data backtest

Public **BTC/USDT spot** 1h history via ccxt (**no API key**). 4h EMA200 is resampled from the same 1h series (`docs/SPEC.md`). Cache is `data/cache/` (gitignored).

```bash
pip install -e ".[exchange]"
python -m alicia download --years 2
python -m alicia backtest
```

Unit tests mock the exchange and do **not** perform this download.

## Order-book filters are not in this backtest

Alicia’s paper/live path requires L2 **spread, imbalance, and depth** (see `docs/SPEC.md` → Orderbuch-Filter). **This file’s numbers do not include those gates.**

Public candle history has no matching historical order book. We do **not** invent fake L2 for 17k hours. The engine skips OB filters in `python -m alicia backtest` / `dry-run` and keeps fixed `SLIPPAGE_BPS`. Paper can fetch a **live** public book (`python -m alicia book` / `paper`) and may quote half-spread as extra slip vs mid — that is a now-cast, not a replay.

Treat the table below as **OHLCV + fees + fixed slippage only**. Live/paper trade counts will be lower once the book gate blocks wide/thin/ask-heavy snapshots.

Paper/live defaults are now tighter (**spread ≤ 2 bps**, **imbalance ≥ +0.20**, **≥ 2.0 BTC bids within 5 bps of mid**). Those gates still **do not run** in this backtest.

## Latest run

| Item | Value |
| --- | --- |
| Run at | 2026-09-12 17:00 UTC (re-run after tighter OB defaults; OB still skipped) |
| Venue | OKX public spot (`okx`) — Binance returned HTTP 451 from this runner; download fell back automatically |
| Symbol / TF | BTC/USDT · 1h (4h derived) |
| Bars | 17,520 · 2024-09-12 17:00 UTC → 2026-09-12 16:00 UTC |
| Cache | `data/cache/okx_BTCUSDT_1h.csv` |
| Capital | €2,000 (USDT treated 1:1) |
| Fees / slippage | 10 bps per side · 5 bps adverse |
| Risk | 2% of equity to stop · €200 small-notional rule · one position |
| Event pauses | example CPI/FOMC/NFP calendar on (`data/events.example.json`) |

### Results (fees + slippage included)

| Metric | Value |
| --- | --- |
| Closed trades | **92** (0 open at end) |
| Wins / losses | 38 / 54 |
| Win rate | **41.30%** |
| Start capital | 2,000.00 |
| End equity | 1,498.36 |
| Return | **−25.08%** |
| Max drawdown | **−28.92%** (peak-to-trough on the equity curve) |
| Closed PnL | −501.64 USDT |
| Fees paid | 316.00 USDT |
| Slippage cost | 158.00 USDT |
| Fees+slippage impact | **419.57 USDT** (zero-cost end equity 1,917.93 vs 1,498.36) |

Last fills (newest):

- 2026-08-26 16:00 · TP · pnl +17.81
- 2026-08-31 01:00 · TP · pnl +13.42
- 2026-09-02 14:00 · TP · pnl +15.11
- 2026-09-08 10:00 · stop · pnl −12.97
- 2026-09-08 15:00 · TP · pnl +11.18

This window lost money after costs. The zero-cost run is still slightly negative, so the edge is not rescued by turning fees off — costs made a large existing drag worse. Numbers are a historical simulation, not a live or paper trading record.
