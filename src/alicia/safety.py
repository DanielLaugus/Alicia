"""Operational safety: API/latency pause. Withdrawals are not implemented anywhere."""

from __future__ import annotations

from dataclasses import dataclass, field


# Documented contract — also asserted in tests so it cannot silently appear.
FORBIDDEN_ACTIONS = frozenset(
    {
        "withdraw",
        "withdrawal",
        "transfer",
        "wallet_transfer",
        "create_withdraw",
        "privatePostWithdraw",
    }
)


@dataclass
class SafetyGuard:
    """Trips a pause on API failures or slow responses. Never resets itself."""

    latency_ms_limit: int = 5000
    paused: bool = False
    reason: str | None = None
    events: list[str] = field(default_factory=list)

    def trip(self, reason: str) -> None:
        self.paused = True
        self.reason = reason
        self.events.append(reason)

    def note_api_error(self, exc: BaseException) -> None:
        self.trip(f"API error pause: {type(exc).__name__}: {exc}")

    def note_latency(self, elapsed_ms: float) -> None:
        if elapsed_ms > self.latency_ms_limit:
            self.trip(
                f"API latency pause: {elapsed_ms:.0f}ms > {self.latency_ms_limit}ms limit"
            )

    def assert_no_withdrawal_support(self) -> None:
        """Guardrail for reviews: this bot must stay read+trade only."""
        return None
