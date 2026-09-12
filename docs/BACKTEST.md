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

**Not the product default. Not live-money advice.** Named profile `us-session` only allows **new** entries when the **completed bar close** falls in the empirical US peak-volume band. Stops and take-profits still manage **anytime** (including through the weekend). Order-book filters are **skipped** (no historical L2). Same €2,000 / 2% risk / 10 bps fee / 5 bps slip / −10% monthly kill-switch.

```bash
python -m alicia backtest --profile us-session
```

### Volume rationale (OKX BTC/USDT 1h, weekdays, America/New_York)

~2y cache `data/cache/okx_BTCUSDT_1h.csv` (2024-09-12 → 2026-09-12). Dollar volume = BTC volume × close. Weekend mean volume is ~56% of weekday (Sat lowest). Hour-of-day below is **Mon–Fri only**, DST-aware.

| NY hour | Mean BTC vol | Share of weekday vol | Mean notional |
| --- | ---: | ---: | ---: |
| 08 (London overlap start) | 408 | 4.7% | 35.4M |
| **09 (NY cash open)** | **660** | **7.5%** | **56.9M** |
| **10** | **766** | **8.8%** | **66.3M** |
| **11** | **591** | **6.8%** | **51.0M** |
| **12** | **478** | **5.5%** | **41.6M** |
| 13 | 419 | 4.8% | 36.2M |
| 14–15 (afternoon) | 366 / 394 | 4.2% / 4.5% | 31.6M / 34.7M |
| 03 (Asia/EU morning, not contiguous US) | 425 | 4.9% | 36.9M |
| Weekday average (all hours) | 365 | — | 31.7M |

Peak **contiguous US cluster** is hours **09–12 ET** (10 ET is the spike). Hour 08 is only marginally above average — London–NY overlap is weaker than the NY cash-open burst. Afternoon 13–16 ET is at or near the weekday mean, so it is **not** the peak. Winter vs summer ranks the same top four hours (10, 9, 11, 12).

Chosen entry window: **[09:00, 13:00) America/New_York, Mon–Fri NY**.

| Season | Local | UTC equivalent |
| --- | --- | --- |
| EDT (roughly mid-Mar–early Nov) | 09:00–13:00 ET | 13:00–17:00 UTC |
| EST (roughly early Nov–mid-Mar) | 09:00–13:00 ET | 14:00–18:00 UTC |

Weekends use the **same NY calendar**: no new entries Saturday/Sunday ET. Friday NY evening is still a weekday even if the UTC date is Saturday. A Friday signal may fill into the weekend; stop/TP then manage normally (no flat-Friday). On this 4h sample, NY weekdays vs UTC weekdays did not change fills.

### Winning config

| Item | Value |
| --- | --- |
| Profile | `us-session` (`--session us-peak`) |
| Entry / trend | **4h** / **12h EMA200** (2h + same window is worse: −7.41% full) |
| Session | **[09:00, 13:00) America/New_York Mon–Fri** |
| Stop / TP | **1.5 × ATR** / **3.0 × ATR** (RR **1:2**) |
| Data | OKX native 4h · 4,379 bars · 2024-09-12 20:00 → 2026-09-12 12:00 UTC |
| Split | Train entries **before 2025-09-12**; OOS **on/after**. Full-series indicators; fresh €2,000 per split. |

4h bars only close at 00/04/08/12/16/20 UTC. The only close inside the peak band is **16:00 UTC** (12:00 EDT / 11:00 EST). That is why this window **matches the previous UTC 13:00–17:00 overlap on 4h** — same eight closed trades. The change is the documented volume clock + DST-aware NY weekends, not a new 4h alpha.

### Full-sample results vs previous us-session (−0.69%)

| Metric | **US-session now (NY peak)** | Prev us-session (UTC overlap) | 2h + NY peak | 4h/12h 24/7 | Product 1h/4h |
| --- | --- | --- | --- | --- | --- |
| Trades | **8** closed (**1 open**) | 8 + 1 open | 21 | 22 + 1 open | 92 |
| Wins / losses | **3 / 5** | 3 / 5 | 7 / 14 | 7 / 15 | 38 / 54 |
| Win rate | **37.50%** | 37.50% | 33.33% | 31.82% | 41.30% |
| Equity | 2,000.00 → **1,986.18** | 1,986.18 | 1,851.82 | 1,841.37 | 1,498.36 |
| Return | **−0.69%** | −0.69% | −7.41% | −7.93% | −25.08% |
| Max drawdown | **−6.61%** | −6.61% | −11.79% | −14.44% | −28.92% |
| Fees / slippage | 32.01 / 16.01 | 32.01 / 16.01 | 77.91 / — | 84.13 / 42.07 | 316 / 158 |
| Cost impact | 40.07 (zero-cost **2,026.24**) | 40.07 | — | 101.19 | 419.57 |

Same last fills as the previous overlap run (all 16:00 UTC signals). 2h + NY peak is not better. Product TP=2×ATR on 4h peak is worse (−3.94%).

### Train / OOS (unchanged vs previous overlap)

| Split | 4h + NY peak RR 1:2 | 2h + NY peak RR 1:2 |
| --- | --- | --- |
| Train | 6 trades · −1.55% · DD −6.53% | 17 · −5.37% · −11.79% |
| Test OOS | 2 + 1 open · **+0.87%** · DD −4.22% | 4 · −2.16% · −5.54% |
| Full | 8 + 1 · **−0.69%** · −6.61% | 21 · −7.41% · −11.79% |

### Honesty

Still **not profitable after fees** (−0.69% full sample). Moving from a guessed UTC overlap to the measured NY volume peak **did not change 4h P&L** — the qualifying 4h bar was already the high-volume one. OOS is still two trades. Do not promote. Product remains:

```bash
python -m alicia backtest
```

## Pattern review & proposals

Same ~2y OKX window, fees 10 bps / slip 5 bps. Product default is unchanged. New CLI: `--profile us-peak-1h` / `us-peak-best` / `us-peak-all`, plus `--ema-slope --ema50 --chop-filter --rsi-from 30 --breakeven-r 1`.

### What the closed trades show

- **Product 1h/4h (92 trades):** 38 TP / 54 stop. Avg win +16.71 vs avg loss −21.05. Expectancy **−5.45 USDT/trade**. Payoff 0.79 — costs flip the 1.33 RR. Zero-cost equity 1,917.93 is still negative (−4.1%). Losers slightly more Tue/Thu/Fri NY. RSI crosses are **shallow** (prev RSI ~36); only 4 from <30 (25% WR). Almost all entries are **below EMA50** (bounce into EMA200). Rising EMA200 is rare (16/92) and not a win filter. ATR% terciles are flat (~37–45% WR).
- **2h / 4h 24/7 RR 1:2:** Better payoff (~1.5–1.6) but WR ~32%. Still negative after costs; zero-cost still slightly negative.
- **us-session 4h (8 closed + 1 open):** Expectancy −0.26. All signals are the **12:00 UTC 4h bar** (07:00–08:00 ET open / 11:00–12:00 ET close). Small sample. Aug 2025 has a 3-stop cluster. RSI-from-30 and EMA50 would have blocked most of these anyway.
- **Fee drag:** Every 1h-in-peak variant that looks decent zero-cost (us-peak-1h RR 1:2 zc 2,097) **dies after fees** (1,856). Discard those as live candidates (rule F).

### Ranked full-sample A/B (after costs)

| Rank | Variant | Trades | WR | Return | Max DD | vs us-session / product |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| — | **us-session 4h NY peak RR 1:2** (current profile) | 8+1 | 37.5% | **−0.69%** | −6.61% | baseline / +24 pp vs product |
| 1 | us-peak-1h + EMA50 + chop, RR 1:2 (`us-peak-best`) | 8 | 37.5% | −1.48% | −2.89% | worse return, shallower DD |
| 2 | us-peak-1h + EMA50, RR 1:2 | 8 | 37.5% | −1.48% | −2.89% | chop did not change this set |
| 3 | us-peak-1h + slope AND EMA50 | 2 | 50% | −1.05% | −2.68% | n=2 — not usable |
| 4 | us-peak-1h + RSI from <30 | 1 | 0% | −0.95% | −0.95% | n=1 — starves |
| 5 | us-session 4h + chop | 6 | 33% | −1.65% | −7.51% | worse |
| 6 | us-peak-1h + chop, RR 1:2 | 38 | 36.8% | −4.87% | −8.80% | more trades, still worse |
| 7 | product 1h + EMA50 | 13 | 38.5% | −4.93% | −6.11% | helps 24/7 1h, not enough |
| 8 | us-peak-1h RR 1:2 (no extras) | 40 | 35% | −7.21% | −9.61% | zc +4.9% — **fees kill it** |
| 9 | us-peak-1h product TP | 40 | 40% | −11.83% | −14.42% | 1:2 beat product TP here |
| 10 | product + chop | 76 | 41% | −21.99% | −25.69% | weak |
| 11 | **product 1h/4h** | 92 | 41.3% | **−25.08%** | −28.92% | baseline product |
| 12 | us-peak-1h + BE@1R | 40 | 45% | −19.03% | −21.92% | **discard** (worse zc too) |
| 13 | product + BE@1R | 95 | 54% | −33.71% | −34.71% | **discard** |
| 14 | **us-peak-all** (slope+EMA50+chop+RSI30+BE) | **0** | — | 0% | 0% | over-filtered |

### Train / OOS (2025-09-12 split)

| Variant | Train | OOS |
| --- | --- | --- |
| us-session 4h | 6 · −1.55% | 2+1 · **+0.87%** |
| us-peak-1h + EMA50 / best | 6 · **+0.70%** | 2 · **−2.16%** (0% WR) |
| us-peak-1h + chop | 28 · −5.03% | 10 · +0.17% |
| product + EMA50 | 9 · −3.08% | 4 · −1.90% |

OOS samples are tiny except chop (10 trades, flat). EMA50 “won” in-sample and **lost** out of sample.

### Recommendation

**None ready to promote.** Keep product 1h/4h as default. Keep `us-session` as the curiosity profile (least-bad after costs, still negative). Do not switch to `us-peak-1h` or `us-peak-all`.

```bash
python -m alicia backtest --profile us-peak-1h          # 1h in NY peak, 4h EMA200, RR 1:2
python -m alicia backtest --profile us-peak-best        # + EMA50 + chop
python -m alicia backtest --profile us-peak-all         # all gates; 0 trades on this sample
python -m alicia backtest --ema-slope --ema50 --chop-filter --rsi-from 30 --breakeven-r 1
```

## Second signal family — Donchian breakout (curiosity only)

**Not the product default.** Product Rule 2 stays RSI(14) cross + volume. This is a separate LONG-only entry: **close crosses above the prior N-bar high**, only if price is above the completed trend-TF EMA200. Opposite of the RSI mean-reversion bounce.

Design choices (see `docs/SPEC.md` § Optional second signal family):

| Choice | Decision |
| --- | --- |
| Primary entry | Donchian N=20 **cross** (not “still above the channel”) so we do not re-enter every bar |
| Channel | `high.rolling(N).max().shift(1)` — current bar excluded, no lookahead |
| Trend | Price > completed 12h EMA200 on 4h bars (same higher-TF step as other 4h experiments). `--ema-slope` optional |
| Volume / RSI | **Off.** Different family; do not smuggle the bounce filters back in |
| Optional A/B entry | `--signal pullback` — reclaim EMA20 after `prev close < EMA20`, still > EMA200 |
| Default exits | 1.5×ATR stop + RR 1:2 (TP 3.0×ATR). Same-bar **stop first** |
| Exit A/B | `--trail-atr 1.5` ratchets the stop on each **completed** close (no intra-bar trail, no fixed TP). `--stop-mode bar-low` uses the signal-bar low if it is below the fill |
| Sessions | `breakout` = 4h 24/7; `breakout-us` = same NY peak as `us-session` (`[09:00, 13:00)` America/New_York, weekdays) |
| Reused | 1–3% risk-to-stop, €200 small-notional, max one position, −10% monthly kill-switch, CPI/Fed/NFP pause, 10 bps fee / 5 bps slip |
| Not used | Historical L2 (none exists; not invented) |

```bash
python -m alicia backtest --profile breakout           # 4h/12h 24/7, Donchian 20, RR 1:2
python -m alicia backtest --profile breakout-us        # + NY peak
python -m alicia backtest --profile breakout-trail     # 24/7, trail 1.5×ATR, no fixed TP
python -m alicia backtest --profile breakout-us-trail
python -m alicia backtest --profile breakout-2h
python -m alicia backtest --profile pullback
python -m alicia backtest --signal breakout --timeframe 4h --reward-risk 2 --ema-slope
```

Same ~2y OKX window as the product run: 4h native cache 4,379 bars · 2024-09-12 20:00 → 2026-09-12 12:00 UTC (`data/cache/okx_BTCUSDT_4h.csv`). 2h variant uses the native 8,759-bar OKX 2h file. Capital €2,000 · 2% risk · 10 bps / 5 bps. Order book skipped.

### Full-sample comparison (fees + slippage included)

| Variant | Trades | WR | Return | Max DD | Zero-cost ret | Expectancy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Product RSI 1h/4h 24/7** (default) | 92 | 41.30% | **−25.08%** | −28.92% | −4.10% | −5.45 |
| **us-session RSI 4h NY peak RR 1:2** | 8+1 | 37.50% | **−0.69%** | −6.61% | +1.31% | −0.26 |
| breakout-trail 4h 24/7 (1.5×ATR trail) | 47 | 31.91% | −6.23% | −19.47% | **+6.66%** | −2.65 |
| breakout 4h + rising EMA200, RR 1:2 | 32 | 37.50% | −6.61% | −13.40% | +0.99% | −4.13 |
| **breakout-us** 4h NY peak RR 1:2 | 25 | 36.00% | −6.72% | −11.98% | −0.79% | −5.37 |
| breakout-us-trail | 25 | 24.00% | −9.22% | −17.20% | −2.59% | −7.37 |
| **breakout** 4h 24/7 RR 1:2 ATR | 54 | 33.33% | −16.30% | −28.11% | −4.67% | −6.04 |
| breakout 4h N=55 RR 1:2 | 44 | 31.82% | −17.04% | −25.29% | −7.69% | −7.74 |
| breakout 4h RR 1:2 bar-low stop | 55 | 32.73% | −18.82% | −29.11% | −6.92% | −6.84 |
| pullback 4h EMA20 reclaim RR 1:2 | 62 | 32.26% | −22.38% | −23.01% | −10.23% | −7.22 |
| breakout-2h 24/7 RR 1:2 | 113 | 30.97% | −30.86% | −34.72% | −3.55% | −5.46 |
| breakout 4h N=10 RR 1:2 | 76 | 26.32% | −38.00% | −43.45% | −27.05% | −10.00 |

Notes:

- Product and us-session **reproduced** the previously recorded −25.08% and −0.69%.
- `breakout` 24/7 tripped the **−10% monthly kill-switch** (−10.74%) on this sample.
- ATR stop beat bar-low. N=20 beat N=10 (noise) and N=55 (fewer, still worse). Pullback is not better than Donchian.
- **Trail 24/7** is the only breakout variant with a clear **zero-cost** edge (+6.66%). After 10 bps / 5 bps it is still −6.23% — same “fees kill it” pattern as `us-peak-1h`. Do not treat it as live-ready.
- Rising EMA200 and `breakout-us` cut trades and drawdown vs 24/7 RR 1:2, but both remain worse than us-session RSI after costs.

### Train / OOS (2025-09-12 UTC split; indicators on the full series, entries gated)

| Variant | Train | OOS |
| --- | --- | --- |
| product RSI 1h/4h | 64 · −20.16% | 28 · −6.17% |
| us-session RSI 4h | 6 · −1.55% | 2+1 · **+0.87%** |
| breakout 4h 24/7 RR 1:2 | 36 · −13.87% | 21 · −6.95% |
| breakout-us | 13 · −4.38% | 12 · −2.44% |
| breakout-trail | 30 · −5.04% | 18 · −2.66% |
| breakout + rising EMA200 | 20 · −5.74% | 12 · −0.93% |
| pullback 4h | 41 · −9.27% | 21 · −14.45% |
| breakout-2h | 70 · −22.49% | 43 · −10.80% |

Enough trades to read: every Donchian / pullback variant **loses in both windows**. us-session’s tiny OOS plus is still n=2.

### Recommendation

**Curiosity profiles only — do not promote.** Product default stays 1h/4h RSI. `us-session` remains the least-bad named profile after costs (−0.69%, small n). Breakout is a valid **second signal family** for later research (especially trail or rising-EMA if fees ever drop), but on this ~2y OKX sample with honest costs it is not an upgrade.

## Potential search

Mandate: keep trying until something has **real potential**, defined as **all** of:

1. After **10 bps / 5 bps**, full-sample return **> +5%** on ~2y (or clearly better risk-adjusted than us-session −0.69% with DD ≤ 15%).
2. Train **and** OOS (split **2025-09-12** UTC) both **≥ 0%** after costs.
3. Preferably ≥ 20 closed OOS **or** ≥ 40 full-sample; fewer = fragile, keep searching.
4. No lookahead, no fake L2, no discarding costs. Maker 2–4 bps is a secondary score only.

Product RSI default is unchanged. Primary venue remains OKX public spot.

### Winner (only config that cleared the written bar)

**ETH/USDT · `regime-20` · 4h entry / 12h EMA200 · ADX split 20 · RR 1:2 · 24/7 · 10/5 bps**

When ADX(14) ≥ 20 on the closed 4h bar: Donchian-20 high breakout (price > completed 12h EMA200). When ADX < 20: product RSI bounce (cross up through 40 + volume). Same risk, kill-switch, stop-before-TP.

```bash
python -m alicia download --exchange okx --symbol ETH/USDT --timeframe 4h --years 2
python -m alicia backtest --symbol ETH/USDT --profile regime-20
# or: python -m alicia backtest --csv data/cache/okx_ETHUSDT_4h.csv --profile regime-20
```

| Window | Trades | WR | Return | Max DD |
| --- | ---: | ---: | ---: | ---: |
| Full ~2y (2024-09-12 → 2026-09-12, 4,379 4h bars) | **44** | 40.91% | **+11.47%** | −16.07% |
| Train to 2025-09-12 | 28 | 42.86% | **+10.88%** | −16.07% |
| OOS from 2025-09-12 | 16 | 37.50% | **+0.52%** | −15.58% |
| Zero-cost full | 44 | — | +20.58% (eq 2,411.52) | — |

Meets: (1) +11.47% > +5% at 10/5; (2) train and mid-sample OOS both ≥ 0; (3) 44 full-sample trades; (4) honest costs, no L2 invention.

**Caveats (do not skip):**

- This is **ETH**, not BTC. The same `regime-20` bundle on BTC 4h is **−15.85%** (57 trades). Do not port it blindly.
- OOS is **thin**: 16 trades, **+0.52%**. Alternate splits are not stable: 2025-06-01 train −3.66% / OOS +15.7%; 2025-12-01 train +20.2% / OOS **−7.27%**. The pre-declared mid split passes; other cuts do not.
- ADX 20 vs 25 vs 30 was a one-parameter A/B. Split 25 on ETH is +22.7% full but OOS **−3.0%** (fails rule 2). Split 20 is the one that cleared OOS.
- DD −16% is not pretty. The run also tripped the **−10% monthly kill-switch** twice. Not live-money advice. Curiosity profile only — **do not replace the BTC RSI product default.**

### Agenda log (honest failures)

| Step | What we ran | Outcome |
| --- | --- | --- |
| **A BTC regime** | ADX switch / trend-only / range-only on 4h and 2h, ± NY peak | 24/7 regime −5% to −17%. **regime-us** +2.33% / train +1.66% / OOS +0.66% / DD −10.3% — green train+OOS but **n=18, fragile**. Adding slope → +5.92% but n=14. More trades (2h, 1h, split 20) went red. |
| **B funding** | OKX public `funding-rate-history` (~290 prints, 2026-06-08 → 2026-09-12 only). Binance `fapi` **HTTP 451**. Bybit/Coinglass not used. | **Not a 2y filter.** On the 3-month overlap, funding caps left 0–3 trades. Documented skip for full-sample research — series was not invented. |
| **C maker 2–4 bps** | Re-score BTC `breakout-trail` and `us-peak-1h` | Trail at **2/2 bps**: +3.16%, train +0.88%, OOS +0.99%, n=47, DD −12.8%. At **10/5 still −6.23%**. us-peak-1h 2/2: +2.39% but train −1.26%. **Potential only with maker fills** — use `--fee-bps 2 --slip-bps 2`. Not a primary-score win. |
| **D ETH** | Same venue/window, ETH/USDT 1h+4h OKX | Product RSI −28.4%. us-session n=3. **regime-20 is the only bar-clearing config** (above). ETH breakout+slope +8.1% / +5.2% / +2.7% but n=23 (fragile). ETH trail +9.3% fails OOS (−1.5%). |
| **E long+short** | Mirrored Donchian/RSI/regime below EMA200. Futures-like; **not spot-executable**. | BTC both-side 4h −15% to −21%, DD ~−30%. Short-only −4.6% (OOS +0.46%, train −5%). ETH both-side +1% to +5% with OOS −10% to −14%. No bar clear. |
| **F vol targeting** | Skip ATR% ≥ 200-bar 90th; optional qty scale to 2% ATR | BTC trail+vol-halt −5.4% (train +4.0%, OOS **−10.3%** — overfit train). us-session+vol-halt **+5.72%** but n=5 (fragile). Did not stabilize a 40-trade BTC book. |

### BTC leaderboard (10/5 unless noted)

| Variant | n | Return | DD | Train | OOS | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| us-session + vol-halt | 5 | +5.72% | −4.2% | +4.8% | +0.87% | fragile |
| regime-us + slope | 14 | +5.92% | −5.0% | +1.66% | +4.19% | fragile |
| **regime-us** | 18 | +2.33% | −10.3% | +1.66% | +0.66% | closest BTC, still <40 |
| trail 2/2 maker | 47 | +3.16% | −12.8% | +0.88% | +0.99% | not 10/5 |
| us-session RSI | 8+1 | −0.69% | −6.6% | −1.55% | +0.87% | prior curiosity |
| trail 10/5 | 47 | −6.23% | −19.5% | −5.04% | −2.66% | zc +6.7% |
| product RSI 1h | 92 | −25.08% | −28.9% | −20.2% | −6.17% | default |

### How to run the search flags

```bash
python -m alicia backtest --profile regime              # ADX 25 switch, 4h
python -m alicia backtest --profile regime-20           # ADX 20 (ETH winner; BTC loses)
python -m alicia backtest --profile regime-us
python -m alicia backtest --profile trend-adx           # breakout only if ADX>=25 and +DI>-DI
python -m alicia backtest --profile range-adx           # RSI only if ADX<=20
python -m alicia backtest --profile breakout-trail --fee-bps 2 --slip-bps 2   # maker check
python -m alicia backtest --profile breakout --side both   # futures-like research
```

