from pathlib import Path

from alicia.safety import FORBIDDEN_ACTIONS, SafetyGuard


def test_latency_and_api_errors_pause():
    guard = SafetyGuard(latency_ms_limit=100)
    guard.note_latency(50)
    assert not guard.paused
    guard.note_latency(250)
    assert guard.paused
    assert "latency" in (guard.reason or "").lower()

    other = SafetyGuard()
    other.note_api_error(TimeoutError("exchange timed out"))
    assert other.paused
    assert "API error" in (other.reason or "")


def test_source_tree_has_no_withdrawal_or_transfer_features():
    root = Path("src/alicia")
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for token in FORBIDDEN_ACTIONS:
            # Mentions in the forbidden-set definition / comments are the deny-list itself.
            if token.lower() in text and path.name != "safety.py" and path.name != "cli.py":
                # cli.py documents the deny-list in help text.
                if path.name == "cli.py":
                    continue
                offenders.append(f"{path}: {token}")
    assert offenders == []


def test_cli_has_no_withdraw_command():
    from alicia import cli

    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "add_parser(\"withdraw" not in source
    assert "add_parser('withdraw" not in source
