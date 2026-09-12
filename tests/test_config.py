import os

from alicia.config import load_settings


def test_load_settings_defaults_without_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith(("BOT_", "RISK_", "FEE_", "PAUSE_", "ALICIA_", "EXCHANGE_", "ORDERBOOK_")):
            monkeypatch.delenv(key, raising=False)
    settings = load_settings(env_file=None)
    assert settings.symbol == "BTC/USDT"
    assert settings.api_key == ""
    assert 0.01 <= settings.risk_pct_clamped <= 0.03
    assert settings.orderbook_enabled
    assert settings.orderbook_require
    assert not settings.orderbook_in_backtest


def test_env_example_has_no_secret_values():
    text = open(".env.example", encoding="utf-8").read()
    assert "EXCHANGE_API_KEY=" in text
    assert "EXCHANGE_API_SECRET=" in text
    # No committed key material after the equals sign on those lines.
    for line in text.splitlines():
        if line.startswith("EXCHANGE_API_KEY=") or line.startswith("EXCHANGE_API_SECRET="):
            assert line.split("=", 1)[1] == ""
