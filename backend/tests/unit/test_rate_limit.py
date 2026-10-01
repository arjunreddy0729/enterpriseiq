"""The in-memory sliding-window limiter and client address resolution."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from app.core.config import Settings
from app.core.rate_limit import SlidingWindowLimiter, client_address


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_the_limit_then_blocks() -> None:
    limiter = SlidingWindowLimiter(clock=FakeClock())
    assert [limiter.hit("k", 3, 60) for _ in range(3)] == [None, None, None]
    assert limiter.hit("k", 3, 60) == pytest.approx(60.0)


def test_window_slides_rather_than_resetting() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(clock=clock)
    limiter.hit("k", 2, 60)  # t=1000
    clock.now += 30
    limiter.hit("k", 2, 60)  # t=1030
    clock.now += 31  # t=1061: the first hit has left the window, the second has not
    assert limiter.hit("k", 2, 60) is None
    assert limiter.hit("k", 2, 60) == pytest.approx(29.0)


def test_keys_are_independent() -> None:
    limiter = SlidingWindowLimiter(clock=FakeClock())
    limiter.hit("a", 1, 60)
    assert limiter.hit("a", 1, 60) is not None
    assert limiter.hit("b", 1, 60) is None


def test_blocked_attempts_do_not_extend_the_block() -> None:
    """Otherwise a client retrying in a loop would lock itself out forever."""
    clock = FakeClock()
    limiter = SlidingWindowLimiter(clock=clock)
    limiter.hit("k", 1, 60)
    for _ in range(10):
        limiter.hit("k", 1, 60)
    clock.now += 61
    assert limiter.hit("k", 1, 60) is None


def request_with(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_without_a_proxy_the_socket_address_is_used() -> None:
    assert client_address(request_with("10.0.0.5", "6.6.6.6"), proxy_hops=0) == "10.0.0.5"


def test_behind_one_proxy_the_rightmost_forwarded_entry_is_used() -> None:
    """The proxy appends the real client address. Anything left of it came
    from the client, so a forged value cannot buy a fresh rate-limit key."""
    request = request_with("10.0.0.1", "1.2.3.4, 203.0.113.9")
    assert client_address(request, proxy_hops=1) == "203.0.113.9"


def test_a_missing_forwarded_header_falls_back_to_the_socket() -> None:
    assert client_address(request_with("10.0.0.1"), proxy_hops=1) == "10.0.0.1"


# ---------------------------------------------------------------------------
# Demo settings guard
# ---------------------------------------------------------------------------
def demo_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "demo_mode": True,
        "llm_daily_budget_usd": 1.0,
        "demo_user_password": SecretStr("pw"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


def test_demo_mode_refuses_to_start_without_a_budget() -> None:
    with pytest.raises(ValidationError, match="LLM_DAILY_BUDGET_USD"):
        demo_settings(llm_daily_budget_usd=None)


def test_demo_mode_refuses_a_model_it_cannot_price() -> None:
    """An unpriced model costs $0 by our estimate, which disables the cap."""
    with pytest.raises(ValidationError, match="known price"):
        demo_settings(anthropic_model="some-new-model")


def test_demo_mode_accepts_a_dated_model_snapshot() -> None:
    assert demo_settings(anthropic_model="claude-haiku-4-5-20251001").demo_mode


def test_demo_mode_turns_rate_limits_on() -> None:
    assert demo_settings().rate_limits_active
    assert not Settings(_env_file=None).rate_limits_active  # type: ignore[call-arg]
