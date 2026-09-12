from alicia.paper import evaluate_latest
from alicia.sample_data import generate_sample_ohlcv


def test_paper_snapshot_does_not_require_keys(settings):
    snap = evaluate_latest(generate_sample_ohlcv(n_1h=1000, seed=3), settings)
    assert snap.price > 0
    assert snap.decision.reason
    assert snap.stop is None or snap.stop < snap.price < (snap.take_profit or snap.price + 1)
