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

## 1m experiment (curiosity only)

**Not the product default.** Default CLI remains 1h entry / 4h EMA200.

```bash
python -m alicia download --timeframe 1m --days 60
python -m alicia backtest --timeframe 1m
```

| Item | Value |
| --- | --- |
| Run at | 2026-09-12 17:10 UTC |
| Venue | OKX public spot `BTC/USDT` 1m (Binance 451; 1h EMA resampled from 1m) |
| Entry TF | **1m** — same RSI(14), volume SMA20, ATR(14) rules |
| Trend TF | **1h EMA200** on completed hours only. 1m→1h is a 60× step vs product 1h→4h (4×); slower than a proportional 4m EMA. Warmup ≈ 200 hours (~8.3 days). |
| Window | Last **60 days**: 86,400 bars · 2026-07-14 17:11 UTC → 2026-09-12 17:10 UTC |
| Cache | `data/cache/okx_BTCUSDT_1m.csv` (does **not** replace the 1h active pointer) |
| Order book | **Skipped** — no historical L2 |
| Fees / slippage / sizing | Same as the 1h product run (10 bps / 5 bps / 2% risk / €2,000) |

### 1m results (fees + slippage included)

| Metric | 1m experiment | Product 1h/4h (2y) |
| --- | --- | --- |
| Trades | **109** (0 open) | 92 |
| Wins / losses | **0 / 109** | 38 / 54 |
| Win rate | **0.00%** | 41.30% |
| Equity | 2,000.00 → **1,450.86** | 2,000.00 → 1,498.36 |
| Return | **−27.46%** | −25.08% |
| Max drawdown | **−27.46%** | −28.92% |
| Closed PnL | −549.14 USDT | −501.64 USDT |
| Fees / slippage | 373.42 / 186.71 USDT | 316.00 / 158.00 USDT |
| Cost impact | 603.25 USDT (zero-cost equity 2,054.11) | 419.57 USDT |

Kill-switch tripped on monthly −10% drawdown (several UTC months). Every closed 1m trade hit the **stop**. On 1m bars, 1.5×ATR stop and 2×ATR target often sit inside the same candle; the engine assumes stop first (conservative, per SPEC). Combined with fees on 109 tiny round-trips, the path is worse than the 1h/4h −25% result.

Do not promote 1m to the main strategy from this section. Default remains:

```bash
python -m alicia backtest
```

## 2h + RR 1:2 experiment (curiosity / tuning)

**Not the product default.** Default CLI remains 1h entry / 4h EMA200 / stop **1.5×ATR** / TP **2×ATR** (~1:1.33). This run changes both the bar size and the target multiple.

```bash
python -m alicia download --timeframe 2h --years 2
python -m alicia backtest --timeframe 2h --reward-risk 2
```

| Item | Value |
| --- | --- |
| Run at | 2026-09-12 17:20 UTC |
| Venue | OKX public spot `BTC/USDT` **native 2h** (Binance 451; OKX honors `since`) |
| Entry TF | **2h** — same RSI(14) cross-up through 40 + volume > SMA20, ATR(14) on 2h bars |
| Trend TF | **8h EMA200** on completed 8h buckets only (UTC 00:00 / 08:00 / 16:00). 2h→8h is the same **4×** step as product 1h→4h. Chosen over 1D EMA200 (cleaner ratio; warmup ≈ 200×8h ≈ 67 days vs 200 days). |
| Stop / TP | Stop **1.5 × ATR(14, 2h)** below fill. TP **3.0 × ATR(14, 2h)** above fill. Reward distance = **2 ×** risk distance (**RR 1:2**). Product TP=2×ATR is only ~1:1.33. |
| Window | **~2 years**: 8,759 bars · 2024-09-12 18:00 UTC → 2026-09-12 14:00 UTC |
| Cache | `data/cache/okx_BTCUSDT_2h.csv` (does **not** replace the 1h active pointer). If a venue lacks native 2h, `backtest --timeframe 2h` resamples from the 1h cache. |
| Order book | **Skipped** — no historical L2 |
| Fees / slippage / sizing | Same as the 1h product run (10 bps / 5 bps / 2% risk / €2,000 / −10% monthly kill-switch) |

### 2h + RR 1:2 results (fees + slippage included)

| Metric | 2h + RR 1:2 | Product 1h/4h (2y) | 1m experiment (60d) |
| --- | --- | --- | --- |
| Trades | **47** (0 open) | 92 | 109 |
| Wins / losses | **15 / 32** | 38 / 54 | 0 / 109 |
| Win rate | **31.91%** | 41.30% | 0.00% |
| Equity | 2,000.00 → **1,734.11** | 2,000.00 → 1,498.36 | 2,000.00 → 1,450.86 |
| Return | **−13.29%** | −25.08% | −27.46% |
| Max drawdown | **−15.34%** | −28.92% | −27.46% |
| Closed PnL | −265.89 USDT | −501.64 USDT | −549.14 USDT |
| Fees / slippage | 167.85 / 83.93 USDT | 316.00 / 158.00 | 373.42 / 186.71 |
| Cost impact | 211.40 USDT (zero-cost equity 1,945.51) | 419.57 USDT | 603.25 USDT |

Last fills (newest): 2026-08-31 04:00 stop −24.08 · 2026-09-02 14:00 TP +41.71 · 2026-09-08 10:00 stop −20.02 · 2026-09-08 16:00 stop −22.79 · 2026-09-11 14:00 stop −28.08.

Better than the product 1h/4h **−25%** and the 1m **−27%** on this window (shallower DD, fewer trades, still **negative** after costs; zero-cost end equity 1,945.51 is still slightly underwater). Win rate dropped vs 1h because the target is farther.

Control on the **same 2h/8h series** with product TP=2×ATR (RR ~1:1.33, no `--reward-risk`): 47 trades, 20/27, 42.55% WR, return **−13.41%**, max DD −16.57%. Almost the same P&L as RR 1:2 — most of the lift vs 1h is the **2h/8h timeframe**, not the wider target. Monthly −10% kill-switch did **not** trip on the RR 1:2 run (it did on the 2h product-RR control).

Still not strong enough to promote. Default remains:

```bash
python -m alicia backtest
```

## 4h + 12h experiment (curiosity / tuning)

**Not the product default.** Default CLI remains 1h entry / 4h EMA200 / stop **1.5×ATR** / TP **2×ATR**. This run uses **4h entry** and keeps **RR 1:2** like the 2h experiment (stop 1.5×ATR, TP 3.0×ATR) so the two higher-TF trials are comparable.

```bash
python -m alicia download --timeframe 4h --years 2
python -m alicia backtest --timeframe 4h --reward-risk 2
```

`--timeframe 4h` derives trend as **12h** unless `--trend-timeframe` is set.

| Item | Value |
| --- | --- |
| Run at | 2026-09-12 18:50 UTC |
| Venue | OKX public spot `BTC/USDT` **native 4h** (Binance 451; OKX honors `since`) |
| Entry TF | **4h** — same RSI(14) cross-up through 40 + volume > SMA20 + ATR(14) on 4h bars |
| Trend TF | **12h EMA200** on completed 12h buckets only. Pandas resample `12h` (UTC, label/closed left) aligns to **00:00 and 12:00 UTC**. 4h→12h is a **3×** step (same spirit as product 1h→4h and 2h→8h, which were 4×). Warmup ≈ 200×12h ≈ 100 days. |
| Stop / TP | Stop **1.5 × ATR(14, 4h)** below fill. TP **3.0 × ATR(14, 4h)** above fill. Reward = **2 ×** risk (**RR 1:2**), matching the 2h experiment — not the product TP=2×ATR (~1:1.33). |
| Window | **~2 years**: 4,379 bars · 2024-09-12 20:00 UTC → 2026-09-12 12:00 UTC |
| Cache | `data/cache/okx_BTCUSDT_4h.csv` (does **not** replace the 1h active pointer). If no native 4h file matches the active venue, `backtest --timeframe 4h` resamples from the 1h cache. |
| Order book | **Skipped** — no historical L2 |
| Fees / slippage / sizing | Same as the 1h product run (10 bps / 5 bps / 2% risk / €2,000 / −10% monthly kill-switch) |

### 4h + 12h + RR 1:2 results (fees + slippage included)

| Metric | 4h/12h + RR 1:2 | 2h/8h + RR 1:2 | Product 1h/4h (2y) | 1m experiment (60d) |
| --- | --- | --- | --- | --- |
| Trades | **22** closed (**1 open** at end) | 47 | 92 | 109 |
| Wins / losses | **7 / 15** | 15 / 32 | 38 / 54 | 0 / 109 |
| Win rate | **31.82%** | 31.91% | 41.30% | 0.00% |
| Equity | 2,000.00 → **1,841.37** | 2,000.00 → 1,734.11 | 2,000.00 → 1,498.36 | 2,000.00 → 1,450.86 |
| Return | **−7.93%** | −13.29% | −25.08% | −27.46% |
| Max drawdown | **−14.44%** | −15.34% | −28.92% | −27.46% |
| Closed PnL | −147.71 USDT | −265.89 USDT | −501.64 USDT | −549.14 USDT |
| Fees / slippage | 84.13 / 42.07 USDT | 167.85 / 83.93 | 316.00 / 158.00 | 373.42 / 186.71 |
| Cost impact | 101.19 USDT (zero-cost equity 1,942.56) | 211.40 USDT | 419.57 USDT | 603.25 USDT |

Last fills (newest): 2025-09-24 08:00 stop −29.00 · 2026-05-19 08:00 stop −33.02 · 2026-09-02 16:00 TP +58.24 · 2026-09-08 16:00 stop −31.36 · 2026-09-11 16:00 **OPEN** (marked to last close; not a forced exit).

Least-bad of the TF experiments so far (shallower loss and DD, fewer trades) but still **negative** after costs; zero-cost end equity 1,942.56 is still slightly underwater. Win rate matches the 2h RR 1:2 run (~32%). Monthly −10% kill-switch did **not** trip.

Control on the **same native 4h/12h series** with product TP=2×ATR (no `--reward-risk`): 24 closed + 1 open, 10/14, 41.67% WR, return **−6.03%**, max DD −12.98%, closed PnL −109.50. Slightly better than RR 1:2 on this window — same pattern as 2h: the **higher entry TF** does most of the work vs 1h, not the wider target.

Still not clearly strong (losing after costs, one trade still open). Do not promote. Default remains:

```bash
python -m alicia backtest
```

## US session bot

**Not the product default. Not live-money advice.** Named profile `us-session` only allows **new** entries when the **completed bar close** falls in a US-liquidity UTC window. Stops and take-profits still manage **anytime** (no flat-by-end-of-session). Order-book filters are **skipped** (no historical L2). Same €2,000 / 2% risk / 10 bps fee / 5 bps slip / −10% monthly kill-switch.

```bash
python -m alicia backtest --profile us-session
```

Clock is **fixed UTC**, not DST-adjusted 9:30 ET. 4h/2h bars are even-hour aligned, so a ±1h nudge around 13:30–20:00 does **not** add or drop bars (documented no-op). Session is judged on bar **close** = index + TF length.

### Winning config (selected on train, checked on test)

| Item | Value |
| --- | --- |
| Profile | `us-session` |
| Entry / trend | **4h** / **12h EMA200** |
| Session | **13:00–17:00 UTC Mon–Fri** (`us-overlap`, London–NY peak) |
| Stop / TP | **1.5 × ATR** / **3.0 × ATR** (RR **1:2**) |
| Off-hours / weekends | No new entries. Existing positions keep stop/TP. |
| Data | OKX native 4h · 4,379 bars · 2024-09-12 20:00 → 2026-09-12 12:00 UTC |
| Split | Train entries **before 2025-09-12**; OOS entries **on/after 2025-09-12**. Indicators computed on the full series (no warmup hole). Fresh €2,000 at the start of each split run. |

### Why this bundle

Discrete A/B only (no RSI-level search):

1. **TF × RR** on primary 13:30–20:00 weekdays (train): **4h + RR 1:2** (−5.03%, DD −7.76%) beat 4h product-TP, 2h+1:2, and 2h product-TP.
2. **Session** on that winner (train): **overlap 13:00–17:00** (−1.55%) beat primary 13:30–20:00 (−5.03%) and a 12:00–20:00 window that actually adds the 12:00-close 4h bar (−10.25%). `us-wide` (±1h) matched primary exactly. Weekends-on matched weekdays (no extra 4h fills).
3. **OOS** (2025-09-12 → 2026-09-12): overlap and primary produced the **same two trades**, **+0.87%**, DD −4.22%. Too few trades to claim a live edge — only that the train pick did not blow up.

### Full-sample results (fees + slippage included)

| Metric | **US-session winner** | 4h/12h 24/7 RR 1:2 | 2h/8h 24/7 RR 1:2 | Product 1h/4h | 1m (60d) |
| --- | --- | --- | --- | --- | --- |
| Trades | **8** closed (**1 open**) | 22 + 1 open | 47 | 92 | 109 |
| Wins / losses | **3 / 5** | 7 / 15 | 15 / 32 | 38 / 54 | 0 / 109 |
| Win rate | **37.50%** | 31.82% | 31.91% | 41.30% | 0.00% |
| Equity | 2,000.00 → **1,986.18** | 1,841.37 | 1,734.11 | 1,498.36 | 1,450.86 |
| Return | **−0.69%** | −7.93% | −13.29% | −25.08% | −27.46% |
| Max drawdown | **−6.61%** | −14.44% | −15.34% | −28.92% | −27.46% |
| Closed PnL | −2.05 USDT | −147.71 | −265.89 | −501.64 | −549.14 |
| Fees / slippage | 32.01 / 16.01 | 84.13 / 42.07 | 167.85 / 83.93 | 316.00 / 158.00 | 373.42 / 186.71 |
| Cost impact | 40.07 (zero-cost equity **2,026.24**) | 101.19 | 211.40 | 419.57 | 603.25 |

Last fills: 2025-08-22 16:00 stop −41.11 · 2025-08-25 16:00 stop −41.02 · 2026-09-02 16:00 TP +62.82 · 2026-09-08 16:00 stop −33.82 · 2026-09-11 16:00 **OPEN**.

### Train / test (winner vs primary window)

| Split | Overlap 13:00–17:00 (winner) | Primary 13:30–20:00 |
| --- | --- | --- |
| Train | 6 trades · −1.55% · DD −6.53% | 10 · −5.03% · −7.76% |
| Test OOS | 2 trades + 1 open · **+0.87%** · DD −4.22% | same 2 + 1 · **+0.87%** · −4.22% |
| Full | 8 + 1 · **−0.69%** · −6.61% | 12 + 1 · −4.20% · −7.85% |

### Honesty

After fees this profile is **still slightly negative** on the full ~2y sample (−0.69%). Zero-cost equity is only +1.3% — costs consume a thin edge. The OOS “profit” is **two trades** and is not evidence the bot is ready for live money. Max DD stayed inside the −20% goal. Better than 24/7 4h/2h/1h/1m on this window because it **trades less**, not because a large US-hours alpha appeared.

Do not promote to the product default. Product remains:

```bash
python -m alicia backtest
```

