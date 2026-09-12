"""US-session entry window. Stops/TPs still manage anytime; no new entries off-hours."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from alicia.indicators import TREND_COMPLETE

NY_TZ = "America/New_York"


def parse_hhmm(value: str) -> int:
    """Return minutes from midnight. Accepts '13:30' or '13'."""
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
    """Entry clock on a named timezone (DST-aware when tz is America/New_York).

    A signal is allowed when the **completed bar's close** is in [start, end]
    (or [start, end) if ``end_exclusive``). Bar index is the open (left label).
    Weekends use that same timezone — Friday NY evening is still a weekday even
    if the UTC date is Saturday.
    """

    start_minute: int
    end_minute: int
    weekdays_only: bool = True
    name: str = "us"
    timezone: str = "UTC"
    end_exclusive: bool = False

    @property
    def label(self) -> str:
        days = "Mon–Fri" if self.weekdays_only else "all days"
        span = f"{format_hhmm(self.start_minute)}–{format_hhmm(self.end_minute)}"
        if self.end_exclusive:
            span = f"[{format_hhmm(self.start_minute)}, {format_hhmm(self.end_minute)})"
        return f"{self.name} {span} {self.timezone} ({days})"

    def allows(self, close_ts: pd.Timestamp) -> bool:
        stamp = pd.Timestamp(close_ts)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        else:
            stamp = stamp.tz_convert("UTC")
        local = stamp.tz_convert(self.timezone)
        if self.weekdays_only and int(local.weekday()) >= 5:
            return False
        minute = int(local.hour) * 60 + int(local.minute)
        start, end = self.start_minute, self.end_minute
        if start <= end:
            if self.end_exclusive:
                return start <= minute < end
            return start <= minute <= end
        if self.end_exclusive:
            return minute >= start or minute < end
        return minute >= start or minute <= end


# Legacy UTC presets (kept for CLI A/B). Product us-session uses US_PEAK.
US_PRIMARY = SessionWindow(13 * 60 + 30, 20 * 60, True, "us-primary")
US_OVERLAP = SessionWindow(13 * 60, 17 * 60, True, "us-overlap")
US_WIDE = SessionWindow(12 * 60 + 30, 21 * 60, True, "us-wide")

# Empirical weekday peak on OKX 1h BTC/USDT (~2y): NY hours 09–12 (10 ET highest).
# Hour 08 (London overlap) is only marginally above average; afternoon 13–16 is weaker.
# [09:00, 13:00) America/New_York, Mon–Fri NY (DST-aware).
US_PEAK = SessionWindow(
    9 * 60,
    13 * 60,
    True,
    "us-peak",
    timezone=NY_TZ,
    end_exclusive=True,
)

SESSION_PRESETS = {
    "us": US_PEAK,
    "us-peak": US_PEAK,
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


PROFILE_US_SESSION = StrategyProfile(
    name="us-session",
    entry_timeframe="4h",
    trend_timeframe="12h",
    session=US_PEAK,
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
