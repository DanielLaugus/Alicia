# Alicia

BTC/USDT **spot** trading bot. Backtesting first; paper and live come later.

The strategy is encoded as explicit, unit-tested rules in `src/alicia/strategy.py` and `src/alicia/risk.py`. The human-readable source of truth is [`docs/SPEC.md`](docs/SPEC.md).

No exchange keys are required to install, test, or dry-run.

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

Optional public-data fetch (still no key):

```bash
pip install -e ".[exchange]"
```

## Backtest

Uses fees (`FEE_BPS`) and adverse slippage (`SLIPPAGE_BPS`) on every fill. Default data is a deterministic synthetic 1h BTC series (enough history for EMA200 on 4h). Pass `--csv` for your own candles (`timestamp,open,high,low,close,volume`).

```bash
python -m alicia backtest
python -m alicia backtest --csv path/to/btcusdt_1h.csv
```

Dry-run (no keys; prints the report plus sample entry decisions):

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
python -m alicia paper              # synthetic or --csv
python -m alicia paper --public     # ccxt public OHLCV, no API key
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
| `ALICIA_MODE` | `backtest` | `backtest` \| `paper` \| `live` |
| `API_LATENCY_MS_LIMIT` | `5000` | Latency pause threshold |

## Layout

```
docs/SPEC.md          # strategy source of truth
src/alicia/           # strategy, risk, calendar, backtest, paper
tests/                # unit tests + dry-run proof
data/events.example.json
.env.example
```
