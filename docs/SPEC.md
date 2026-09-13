# Alicia strategy spec

Source of truth for the BTC/USDT spot bot. Implementation and tests must follow these rules exactly.

## Market and timeframes

| Item | Value |
| --- | --- |
| Market | BTC/USDT spot |
| Direction | LONG only (no shorts) |
| Entry timeframe | 1h |
| Trend timeframe | 4h |
| Indicators | EMA200(4h), RSI(14) 1h, volume vs MA20 1h, ATR(14) 1h, plus live L2 book filters |

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

## Orderbuch-Filter (additional entry gate)

OHLCV-only is **not** enough for paper or live entries. Before a new LONG, when order-book filters are enabled, **all three** L2 checks must pass. The five candle rules above stay unchanged; this layer only **blocks**.

Public depth is read with ccxt `fetch_order_book` (**no API key**). Practical default venue: **OKX** spot `BTC/USDT` (same public venue as the recorded OHLCV backtest). `ORDERBOOK_EXCHANGE` overrides; if that venue is geo-blocked, the client tries OKX / KuCoin / Gate.

### OB-1 — Spread

- `mid = (best_bid + best_ask) / 2`
- `spread_bps = (best_ask − best_bid) / mid × 10_000`
- Enter only if `spread_bps ≤ ORDERBOOK_MAX_SPREAD_BPS` (default **2**).

### OB-2 — Imbalance (top N)

- Top **N** levels (default `ORDERBOOK_LEVELS=10`), best first.
- `imbalance = (bid_vol − ask_vol) / (bid_vol + ask_vol)` in `[-1, +1]`
- Enter long only if `imbalance ≥ ORDERBOOK_IMBALANCE_MIN` (default **+0.20** = clearly bid-heavy, not merely non-ask-heavy).

### OB-3 — Bid depth near mid

- Sum **bid-side base size** (BTC) with `price ≥ mid × (1 − ORDERBOOK_DEPTH_BPS / 10_000)`
- Default band: **5 bps** from mid.
- Enter only if that size ≥ `ORDERBOOK_MIN_BID_DEPTH` (default **2.0 BTC**).

### Fail closed

If `ORDERBOOK_REQUIRE=true` (default for paper/live):

- missing book, empty book, crossed book, or fetch error → **no new entry**
- never invent a synthetic book to “pass” the gate

### Backtest honesty

Historical L2 is **not** available from the public REST history used for candles. The backtest **does not invent** order books.

- Default: `ORDERBOOK_IN_BACKTEST=false` — candle rules + fixed `SLIPPAGE_BPS` only. Reports must say the OB gate was skipped.
- Recorded JSON snapshots are for **unit tests and paper demos only**, not as a time series.
- Paper may report **half-spread** as estimated extra slippage vs mid at that instant. The historical backtest still uses configured `SLIPPAGE_BPS` until real L2 history is supplied later.

## API safety (mandatory)

- API keys, if used, must be **read + trade only**.
- This repository **must not** implement withdrawal, transfer, or funding-destination changes.
- Never commit secrets. Use `.env` locally from `.env.example`.

## Optional profile — US session bot

**Not the product default.** Product entries are 24/7 on 1h/4h. Enable with `python -m alicia backtest --profile us-session`.

Winning bundle after a small A/B (see `docs/BACKTEST.md` § US session bot):

| Item | Value |
| --- | --- |
| Entry / trend | 4h / 12h EMA200 |
| Session | **[09:00, 13:00) America/New_York**, Mon–Fri NY (DST-aware). = 13:00–17:00 UTC in EDT, 14:00–18:00 UTC in EST. Signal clock = **completed bar close**. |
| Off-hours | **No new entries.** Open positions still hit stop/TP anytime (no flat-by-close). |
| Stop / TP | 1.5×ATR / 3.0×ATR (RR 1:2) |
| Weekends | **No new entries** on Saturday/Sunday in **America/New_York** (Friday NY evening is still allowed even if UTC is Saturday). Open risk is managed through the weekend. |

Do not promote this profile to the product default unless a later sample is clearly profitable after fees.

## Optional second signal family — breakout / trend-follow

**Not the product default.** Product Rule 2 stays **RSI(14) cross up through 40 + volume**. This family is a separate LONG-only entry, enabled with `--signal breakout` or `--profile breakout` / `breakout-us`. Risk, sizing, kill-switch, and session windows are reused.

| Item | Value |
| --- | --- |
| Trend filter | Same Rule 1: price above **completed** trend-TF EMA200 (profiles use 4h entry / 12h EMA200). Optional `--ema-slope` requires a rising EMA200. |
| Entry (primary) | **Donchian / N-bar high breakout.** Close crosses **above** the prior N-bar high (default N=20). Channel = `high.rolling(N).max().shift(1)` — current bar excluded (no lookahead). Re-entry requires a fresh cross, not “close still above the channel”. **No RSI. No volume gate.** |
| Entry (optional A/B) | `--signal pullback` / `--profile pullback`: still above EMA200, enter when close **reclaims EMA20** after `prev close < EMA20`. |
| Stop / TP | Default experiment: 1.5×ATR stop + RR 1:2 (TP 3.0×ATR). A/B: `--trail-atr 1.5` (ratchet stop on completed close; no fixed TP) or `--stop-mode bar-low` (breakout-bar low if below fill, else ATR). Same-bar stop-before-TP still applies. |
| Sessions | `breakout` = 24/7 on 4h. `breakout-us` = NY peak `[09:00, 13:00) America/New_York` weekdays only (same window as `us-session`). |

See `docs/BACKTEST.md` for the comparison vs product RSI and `us-session`. Do not silently replace the RSI default.

**Regime switch (curiosity / paper):** `--signal regime` / `--profile regime` / `regime-20` / `paper-eth`. If ADX(14) on the entry bar is ≥ `adx_split` (25, or 20 for `regime-20` / `paper-eth`), use the Donchian breakout; otherwise use the product RSI bounce. Optional `--adx-min` / `--adx-max` / `--di-align` / `--vol-halt` / `--side short|both`. Shorts are **futures-like research**, not spot-executable. BTC product default for `backtest` without flags stays RSI.

## Official paper profile — ETH/USDT `regime-20`

**Locked for paper only.** Not live. Does not replace the BTC 1h/4h RSI product default.

| Item | Value |
| --- | --- |
| Symbol | **ETH/USDT** |
| Profile | **`paper-eth`** (same rules as `regime-20`) |
| Entry / trend | 4h / completed 12h EMA200 |
| Switch | ADX(14) ≥ **20** → Donchian-20 high breakout; else RSI(14) cross up through 40 + volume |
| Stop / TP | 1.5×ATR / 3.0×ATR (RR 1:2). Same-bar stop first |
| Sessions | 24/7 (no US-peak filter) |
| Paper L2 | Existing order-book gates (spread / imbalance / depth). Fail closed if `ORDERBOOK_REQUIRE` and the book is missing |
| Mode | Evaluate latest **closed** bar only. **No orders. No withdrawals. Live trading is disabled.** |

Recommended command: `python -m alicia paper --profile paper-eth`

Known caveats: the same bundle **fails on BTC**; ETH mid-sample OOS is thin; last 6 months **−7.27%**. See `docs/BACKTEST.md` § Re-test ETH regime-20.

## Execution assumptions (backtest)

- Fees: `FEE_BPS` on each side (entry and exit), applied to fill notional.
- Slippage: `SLIPPAGE_BPS` adverse (buy up, sell down).
- Spot long-only cash accounting in quote currency (USDT).
