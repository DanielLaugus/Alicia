# Real-data backtest

This file records the last **public BTC/USDT spot** backtest run on cached 1h history.

- Data: ccxt public OHLCV, **no API key**
- 4h EMA200: resampled from the same 1h series (see `docs/SPEC.md`)
- Cache path: `data/cache/` (gitignored)
- Unit tests do **not** download this file; refresh it locally with:

```bash
pip install -e ".[exchange]"
python -m alicia download --years 2
python -m alicia backtest
```

Numbers below are filled after a real download + backtest. If this section still says “pending”, run the commands above.

## Latest run

Pending — will be replaced after the first successful public-data backtest.
