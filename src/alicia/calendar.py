"""Configurable CPI / Fed / NFP pause calendar."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from alicia.config import Settings

EVENT_TYPES = ("cpi", "fed", "nfp")


@dataclass(frozen=True)
class MacroEvent:
    day: date
    type: str
    label: str = ""


@dataclass(frozen=True)
class EventCalendar:
    events: tuple[MacroEvent, ...]
    pause_cpi: bool = True
    pause_fed: bool = True
    pause_nfp: bool = True

    def enabled_types(self) -> set[str]:
        enabled: set[str] = set()
        if self.pause_cpi:
            enabled.add("cpi")
        if self.pause_fed:
            enabled.add("fed")
        if self.pause_nfp:
            enabled.add("nfp")
        return enabled

    def pause_reason(self, day: date) -> str | None:
        enabled = self.enabled_types()
        hits = [e for e in self.events if e.day == day and e.type in enabled]
        if not hits:
            return None
        labels = ", ".join(sorted({e.label or e.type.upper() for e in hits}))
        return f"macro event pause: {labels}"

    def is_pause_day(self, ts: datetime | date) -> bool:
        day = ts.date() if isinstance(ts, datetime) else ts
        return self.pause_reason(day) is not None


def load_events(path: Path | None) -> tuple[MacroEvent, ...]:
    if path is None or not path.exists():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw: Iterable[dict] = payload.get("events", payload if isinstance(payload, list) else [])
    events: list[MacroEvent] = []
    for item in raw:
        day = date.fromisoformat(str(item["date"]))
        kind = str(item.get("type", "")).strip().lower()
        if kind not in EVENT_TYPES:
            continue
        events.append(MacroEvent(day=day, type=kind, label=str(item.get("label", ""))))
    return tuple(events)


def calendar_from_settings(settings: Settings) -> EventCalendar:
    return EventCalendar(
        events=load_events(settings.events_path),
        pause_cpi=settings.pause_cpi,
        pause_fed=settings.pause_fed,
        pause_nfp=settings.pause_nfp,
    )
