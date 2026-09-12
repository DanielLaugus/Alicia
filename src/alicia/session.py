"""US-session entry window. Stops/TPs still manage anytime; no new entries off-hours."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from alicia.indicators import TREND_COMPLETE
from alicia.strategy import ExtraFilters

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
    """Named experiment bundle. Product default is 'default' (no session, 1h/4h, RSI)."""

    name: str
    entry_timeframe: str
    trend_timeframe: str
    session: SessionWindow | None
    reward_risk: float | None
    stop_atr: float = 1.5
    extra: ExtraFilters = ExtraFilters()
    breakeven_r: float | None = None
    signal: str = "rsi"
    donchian_n: int = 20
    trail_atr: float | None = None
    stop_mode: str = "atr"


PROFILE_US_SESSION = StrategyProfile(
    name="us-session",
    entry_timeframe="4h",
    trend_timeframe="12h",
    session=US_PEAK,
    reward_risk=2.0,
    stop_atr=1.5,
)

# 1h entries only inside the NY peak band; 4h EMA200 trend.
PROFILE_US_PEAK_1H = StrategyProfile(
    name="us-peak-1h",
    entry_timeframe="1h",
    trend_timeframe="4h",
    session=US_PEAK,
    reward_risk=2.0,
    stop_atr=1.5,
)

# Filters that individually helped on 1h-in-peak without starving the sample.
PROFILE_US_PEAK_BEST = StrategyProfile(
    name="us-peak-best",
    entry_timeframe="1h",
    trend_timeframe="4h",
    session=US_PEAK,
    reward_risk=2.0,
    stop_atr=1.5,
    extra=ExtraFilters(require_ema50=True, chop_filter=True),
)

# All optional gates stacked (may produce zero trades — see BACKTEST.md).
PROFILE_US_PEAK_ALL = StrategyProfile(
    name="us-peak-all",
    entry_timeframe="1h",
    trend_timeframe="4h",
    session=US_PEAK,
    reward_risk=2.0,
    stop_atr=1.5,
    extra=ExtraFilters(
        require_ema_slope=True,
        require_ema50=True,
        chop_filter=True,
        rsi_from=30.0,
    ),
    breakeven_r=1.0,
)

# Second signal family: Donchian breakout (not RSI). Same risk/kill-switch/session helpers.
PROFILE_BREAKOUT = StrategyProfile(
    name="breakout",
    entry_timeframe="4h",
    trend_timeframe="12h",
    session=None,
    reward_risk=2.0,
    stop_atr=1.5,
    signal="breakout",
    donchian_n=20,
    stop_mode="atr",
)

PROFILE_BREAKOUT_US = StrategyProfile(
    name="breakout-us",
    entry_timeframe="4h",
    trend_timeframe="12h",
    session=US_PEAK,
    reward_risk=2.0,
    stop_atr=1.5,
    signal="breakout",
    donchian_n=20,
    stop_mode="atr",
)

PROFILE_BREAKOUT_TRAIL = StrategyProfile(
    name="breakout-trail",
    entry_timeframe="4h",
    trend_timeframe="12h",
    session=None,
    reward_risk=None,
    stop_atr=1.5,
    signal="breakout",
    donchian_n=20,
    trail_atr=1.5,
    stop_mode="atr",
)

PROFILE_BREAKOUT_US_TRAIL = StrategyProfile(
    name="breakout-us-trail",
    entry_timeframe="4h",
    trend_timeframe="12h",
    session=US_PEAK,
    reward_risk=None,
    stop_atr=1.5,
    signal="breakout",
    donchian_n=20,
    trail_atr=1.5,
    stop_mode="atr",
)

PROFILE_BREAKOUT_2H = StrategyProfile(
    name="breakout-2h",
    entry_timeframe="2h",
    trend_timeframe="8h",
    session=None,
    reward_risk=2.0,
    stop_atr=1.5,
    signal="breakout",
    donchian_n=20,
    stop_mode="atr",
)

PROFILE_PULLBACK = StrategyProfile(
    name="pullback",
    entry_timeframe="4h",
    trend_timeframe="12h",
    session=None,
    reward_risk=2.0,
    stop_atr=1.5,
    signal="pullback",
)

PROFILES = {
    "default": StrategyProfile("default", "1h", "4h", None, None, 1.5),
    "us-session": PROFILE_US_SESSION,
    "us-session-1h": PROFILE_US_PEAK_1H,
    "us-peak-1h": PROFILE_US_PEAK_1H,
    "us-peak-best": PROFILE_US_PEAK_BEST,
    "us-peak-all": PROFILE_US_PEAK_ALL,
    "breakout": PROFILE_BREAKOUT,
    "breakout-us": PROFILE_BREAKOUT_US,
    "breakout-trail": PROFILE_BREAKOUT_TRAIL,
    "breakout-us-trail": PROFILE_BREAKOUT_US_TRAIL,
    "breakout-2h": PROFILE_BREAKOUT_2H,
    "pullback": PROFILE_PULLBACK,
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
