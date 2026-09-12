"""US-session entry window. Stops/TPs still manage anytime; no new entries off-hours."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from alicia.indicators import TREND_COMPLETE


def parse_hhmm(value: str) -> int:
    """Return minutes from UTC midnight. Accepts '13:30' or '13'."""
    text = value.strip()
    if ":" in text:
        hour_s, minute_s = text.split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
    else:
        hour, minute = int(text), 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid HH:MM: {value}")
    return hour * 60 + minute


def format_hhmm(minutes: int) -> str:
    minutes = minutes % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class SessionWindow:
    """Fixed UTC clock (not DST-adjusted ET). Half-open for start, inclusive end.

    A signal is allowed when the **completed bar's close** is in [start, end]
    (minutes from midnight UTC). Bar index is the open (left label).
    """

    start_minute: int
    end_minute: int
    weekdays_only: bool = True
    name: str = "us"

    @property
    def label(self) -> str:
        days = "Mon–Fri UTC" if self.weekdays_only else "all days"
        return f"{self.name} {format_hhmm(self.start_minute)}–{format_hhmm(self.end_minute)} UTC ({days})"

    def allows(self, close_ts: pd.Timestamp) -> bool:
        stamp = pd.Timestamp(close_ts)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        else:
            stamp = stamp.tz_convert("UTC")
        if self.weekdays_only and stamp.weekday() >= 5:
            return False
        minute = stamp.hour * 60 + stamp.minute
        start, end = self.start_minute, self.end_minute
        if start <= end:
            return start <= minute <= end
        # Window crossing midnight (not used by the US profile).
        return minute >= start or minute <= end


# Primary brief: NY cash open ~13:30 UTC through late US afternoon + London overlap.
US_PRIMARY = SessionWindow(13 * 60 + 30, 20 * 60, True, "us-primary")
# London–NY overlap peak only.
US_OVERLAP = SessionWindow(13 * 60, 17 * 60, True, "us-overlap")
# ±1h around primary (one of the three discrete session variants).
US_WIDE = SessionWindow(12 * 60 + 30, 21 * 60, True, "us-wide")

SESSION_PRESETS = {
    "us": US_PRIMARY,
    "us-primary": US_PRIMARY,
    "us-overlap": US_OVERLAP,
    "us-wide": US_WIDE,
}


@dataclass(frozen=True)
class StrategyProfile:
    """Named experiment bundle. Product default is 'default' (no session, 1h/4h)."""

    name: str
    entry_timeframe: str
    trend_timeframe: str
    session: SessionWindow | None
    reward_risk: float | None
    stop_atr: float = 1.5


# Winning bundle after train/test A/B (see docs/BACKTEST.md § US session bot).
# 4h + 12h + RR 1:2 + London–NY overlap beat 2h and the wider 13:30–20:00 window.
PROFILE_US_SESSION = StrategyProfile(
    name="us-session",
    entry_timeframe="4h",
    trend_timeframe="12h",
    session=US_OVERLAP,
    reward_risk=2.0,
    stop_atr=1.5,
)

PROFILES = {
    "default": StrategyProfile("default", "1h", "4h", None, None, 1.5),
    "us-session": PROFILE_US_SESSION,
}


def bar_close_time(bar_open: pd.Timestamp, timeframe: str) -> pd.Timestamp:
    if timeframe not in TREND_COMPLETE:
        raise ValueError(f"Unsupported timeframe for session close: {timeframe}")
    stamp = pd.Timestamp(bar_open)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp + TREND_COMPLETE[timeframe]


def session_allows_signal(
    bar_open: pd.Timestamp,
    timeframe: str,
    window: SessionWindow | None,
) -> bool:
    if window is None:
        return True
    return window.allows(bar_close_time(bar_open, timeframe))
