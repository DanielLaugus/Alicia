from datetime import date
from pathlib import Path

from alicia.calendar import EventCalendar, MacroEvent, load_events


def test_pauses_on_enabled_event_type():
    cal = EventCalendar(
        events=(MacroEvent(date(2024, 2, 2), "nfp", "NFP"),),
        pause_cpi=False,
        pause_fed=False,
        pause_nfp=True,
    )
    assert cal.is_pause_day(date(2024, 2, 2))
    assert "NFP" in (cal.pause_reason(date(2024, 2, 2)) or "")
    assert not cal.is_pause_day(date(2024, 2, 3))


def test_flag_disables_event_type():
    cal = EventCalendar(
        events=(MacroEvent(date(2024, 2, 2), "nfp", "NFP"),),
        pause_nfp=False,
    )
    assert not cal.is_pause_day(date(2024, 2, 2))


def test_loads_example_calendar():
    path = Path("data/events.example.json")
    events = load_events(path)
    assert events
    assert {e.type for e in events} <= {"cpi", "fed", "nfp"}
