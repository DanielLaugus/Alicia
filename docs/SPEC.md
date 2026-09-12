# Alicia strategy spec

Source of truth for the BTC/USDT spot bot. Implementation and tests must follow these rules exactly.

## Market and timeframes

| Item | Value |
| --- | --- |
| Market | BTC/USDT spot |
| Direction | LONG only (no shorts) |
| Entry timeframe | 1h |
| Trend timeframe | 4h |
| Indicators | EMA200(4h), RSI(14) 1h, volume vs MA20 1h, ATR(14) 1h |

## Rule 1 — Trend filter

- New entries only when **price is above EMA200 on 4h**.
- Otherwise: **no new entry**.
- Existing positions are not force-closed by the trend filter; they still exit via stop or take-profit.

**Implementation notes**

- Price = last **closed** 1h close.
- EMA200 is computed on **completed** 4h candles only (no lookahead into the in-progress 4h bar).
- EMA200 is treated as **not ready** until 200 completed 4h bars exist (no entries on a partial EMA).
- 4h buckets align to UTC `00:00, 04:00, 08:00, 12:00, 16:00, 20:00`.

## Rule 2 — Entry

LONG only when **both** are true on the closed 1h bar:

1. RSI(14) on 1h **crosses up from below 40 to above 40** (previous RSI `< 40` and current RSI `> 40`).
2. Volume on 1h is **above its 20-period simple average**.

RSI uses Wilder smoothing. Volume MA is SMA(20) of 1h volume.

A fill is simulated on the **next** 1h open (plus slippage). No market-on-close lookahead.

## Rule 3 — Stop and target

- Stop = entry − **1.5 × ATR(14, 1h)**
- Take-profit = entry + **2 × ATR(14, 1h)**
- ATR is the value on the signal bar (the closed 1h that triggered entry).
- **No averaging down.** Never add to an open position.
- If stop and take-profit would both trade in the same bar, the backtest assumes the **stop** is hit first (conservative).

## Rule 4 — Position sizing

- **Max one open position** at a time.
- Risk-to-stop is **1–3% of bot capital** (configured `RISK_PCT`, clamped to `[0.01, 0.03]`).
- Quantity (BTC) = `(capital × risk_pct) / (entry − stop)`.
- **Notional positions up to €200** are always allowed when the risk-derived notional is ≤ €200 (small-book path).
- **Above €200**, size comes only from the risk-to-stop formula (never an arbitrary larger notional).
- USDT is treated as 1:1 with EUR unless `USDT_EUR_RATE` is set (quote notional × rate ≤ / ≥ the €200 threshold).
- Quantity is also capped so the entry notional cannot exceed available cash.

## Rule 5 — Kill-switch

Halt or pause **new entries** when any of the following trip:

1. **Monthly drawdown ≤ −10%** from the peak equity reached in the current UTC calendar month.
2. **CPI / Fed (FOMC) / NFP days** — configurable flags (`PAUSE_CPI`, `PAUSE_FED`, `PAUSE_NFP`) plus an optional JSON calendar (`EVENTS_PATH`).
3. **API / latency errors** — any exchange exception or request slower than `API_LATENCY_MS_LIMIT` pauses the bot.

Open positions are not increased while paused; they still manage stop / take-profit until flat. After a monthly-drawdown halt, the bot stays halted until the next UTC month (backtest) or until the operator resets (paper/live).

## API safety (mandatory)

- API keys, if used, must be **read + trade only**.
- This repository **must not** implement withdrawal, transfer, or funding-destination changes.
- Never commit secrets. Use `.env` locally from `.env.example`.

## Execution assumptions (backtest)

- Fees: `FEE_BPS` on each side (entry and exit), applied to fill notional.
- Slippage: `SLIPPAGE_BPS` adverse (buy up, sell down).
- Spot long-only cash accounting in quote currency (USDT).
