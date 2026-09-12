# Alicia

BTC/USDT **spot** trading bot. Backtesting first; paper and live come later.

The strategy is encoded as explicit, unit-tested rules in `src/alicia/strategy.py` and `src/alicia/risk.py`. The human-readable source of truth is [`docs/SPEC.md`](docs/SPEC.md).

No exchange keys are required to install, test, download public history, or dry-run.

## Strategy rules

Market: **BTC/USDT spot** · Entry TF: **1h** · Trend TF: **4h** · **LONG only**

1. **Trend filter.** New entries only when price is above EMA200 on the 4h chart. Otherwise no new entry.
2. **Entry.** LONG only when **both** are true on the closed 1h bar: RSI(14) crosses **up from below 40 to above 40**, **and** 1h volume is above its 20-period average.
3. **Stop & target.** Stop = 1.5 × ATR(14, 1h) below entry. Take-profit = 2 × ATR(14, 1h) above entry. **No averaging down.**
4. **Position sizing.** Notional positions up to **€200** are allowed. Above that, size so that a stop loss risks **1–3% of bot capital** (quantity derived from stop distance). **Max one open position.**
5. **Kill-switch.** Halt / pause on **−10% monthly drawdown**; pause on **CPI / Fed / NFP** days (flags + JSON calendar); pause on **API / latency** errors.

Indicators: EMA200(4h), RSI(14) 1h, volume vs MA20, ATR(14) 1h.

## Setup

Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

`.env` is gitignored. Leave `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET` empty for backtest and dry-run.

Public history (still no key) needs ccxt:

```bash
pip install -e ".[dev,exchange]"
```

## Real market data + backtest

Public BTC/USDT **spot** 1h candles come from ccxt (Binance by default). No API key. 4h bars used by the EMA200 trend filter are **resampled from 1h** so the series stays consistent.

Cache files live under `data/cache/` (gitignored). After the first download, backtests run offline.

```bash
# ~2 years of 1h BTC/USDT (paginated public fetch)
python -m alicia download --years 2

# Incremental update (only bars after the last cached timestamp)
python -m alicia download

# Reproducible backtest on the cache: fees + slippage, win rate, max DD
python -m alicia backtest
```

Useful variants:

If Binance (or another venue) geo-blocks public REST, `download` tries other public spot venues (OKX, KuCoin, Gate, …) and records the one that worked in `data/cache/active.json`. `backtest` follows that pointer.

```bash
python -m alicia download --exchange okx --years 2
python -m alicia download --since 2024-01-01 --force
python -m alicia download --no-fallback                # preferred venue only
python -m alicia backtest --csv path/to/btcusdt_1h.csv
python -m alicia backtest --synthetic                  # built-in demo series
```

A recorded run on downloaded Binance history is in [`docs/BACKTEST.md`](docs/BACKTEST.md). Re-run the two commands above to refresh those numbers.

**CI / unit tests never hit the network.** Live `download` + `backtest` is a manual/integration step.

## Synthetic dry-run

Uses fees (`FEE_BPS`) and adverse slippage (`SLIPPAGE_BPS`) on every fill. The dry-run series is deterministic and needs no cache.

```bash
python -m alicia dry-run
pytest
```

Print the five rules:

```bash
python -m alicia rules
```

## Paper path

Paper mode **evaluates the latest closed-bar signal only**. It does not place orders.

```bash
python -m alicia paper              # cached 1h if present, else synthetic
python -m alicia paper --public     # latest public 1h candles via ccxt (no key)
python -m alicia paper --csv path/to/btcusdt_1h.csv
```

A future live loop would: poll 1h/4h candles → same `evaluate_entry` / sizing / kill-switch → spot buy/sell only. That path is not enabled by this CLI.

## Safety notes

- Create exchange API keys with **read + trade only**. Never enable withdrawal.
- This repository **does not implement** withdraw, transfer, or wallet-move APIs. There is no CLI command for it.
- Kill-switch pauses **new entries** on −10% monthly drawdown (from the UTC month’s equity peak), on configured macro days, and on API/latency errors. Open trades still use their stop / take-profit.
- Macro days: set `PAUSE_CPI`, `PAUSE_FED`, `PAUSE_NFP` and optionally point `EVENTS_PATH` at a JSON file (see `data/events.example.json`).
- Do not commit `.env` or real keys.

## Config (env)

| Variable | Default | Meaning |
| --- | --- | --- |
| `BOT_CAPITAL_EUR` | `2000` | Bot capital for sizing and drawdown |
| `RISK_PCT` | `0.02` | Risk to stop, clamped to 1–3% |
| `MAX_SMALL_NOTIONAL_EUR` | `200` | Small-book notional allowance |
| `USDT_EUR_RATE` | `1` | Quote→EUR conversion for the €200 rule |
| `FEE_BPS` | `10` | Per-side fee (10 = 0.10%) |
| `SLIPPAGE_BPS` | `5` | Adverse slippage (5 = 0.05%) |
| `MONTHLY_DD_HALT` | `0.10` | Monthly drawdown kill-switch |
| `PAUSE_CPI` / `PAUSE_FED` / `PAUSE_NFP` | `true` | Event-day pauses |
| `EVENTS_PATH` | `data/events.example.json` | Extra calendar dates |
| `SYMBOL` / `EXCHANGE` | `BTC/USDT` / `binance` | Market (spot) |
| `DATA_CACHE_DIR` | `data/cache` | Public OHLCV cache (gitignored) |
| `ALICIA_MODE` | `backtest` | `backtest` \| `paper` \| `live` |
| `API_LATENCY_MS_LIMIT` | `5000` | Latency pause threshold |

## Layout

```
docs/SPEC.md          # strategy source of truth
docs/BACKTEST.md      # last real-data backtest numbers
src/alicia/           # strategy, risk, calendar, backtest, download
tests/                # unit tests (offline; mocked fetch)
data/events.example.json
data/cache/           # gitignored public OHLCV after `download`
.env.example
```
