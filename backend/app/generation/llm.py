"""The LLM adapter.

One provider, one class, behind one interface. There is deliberately no
multi-model abstraction layer: nothing in this system needs to switch
providers mid-request, and a premature abstraction over three different
streaming formats and three different tool-call shapes would cost more than it
saves. Swapping providers means writing one more class that satisfies
`LLMClient`.

Two model-specific details that are easy to get wrong on Claude 4.6+ models:

* `temperature`, `top_p` and `top_k` are **rejected with a 400**. Steering
  happens through the prompt.
* `max_tokens` bounds thinking *plus* answer text together. Sizing it tightly
  around the expected answer length silently truncates the answer once the
  model decides to think.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.api.errors import ConfigurationError
from app.core.config import estimate_cost_usd, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class Completion:
    """One model response, with everything needed to log and price it."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    latency_ms: int
    estimated_cost_usd: float = 0.0
    refusal_category: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def was_truncated(self) -> bool:
        return self.stop_reason == "max_tokens"

    @property
    def was_refused(self) -> bool:
        return self.stop_reason == "refusal"


@runtime_checkable
class LLMClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete(self, system: str, user: str) -> Completion: ...


class AnthropicClient:
    """Claude via the official SDK."""

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> None:
        settings = get_settings()
        if not settings.llm_configured:
            raise ConfigurationError(
                "ANTHROPIC_API_KEY is not set. Retrieval works without it; "
                "generation does not. Add a key to .env and restart."
            )
        self._settings = settings
        self._model = model or settings.anthropic_model
        self._max_tokens = max_tokens or settings.anthropic_max_tokens
        self._effort = effort or settings.anthropic_effort
        self._client: Any = None

    @property
    def model(self) -> str:
        return self._model

    def _sdk(self) -> Any:
        if self._client is None:
            import anthropic

            key = self._settings.anthropic_api_key
            assert key is not None  # guaranteed by llm_configured
            self._client = anthropic.Anthropic(
                api_key=key.get_secret_value(),
                timeout=self._settings.anthropic_timeout_seconds,
                max_retries=self._settings.anthropic_max_retries,
            )
        return self._client

    def complete(self, system: str, user: str) -> Completion:
        import anthropic

        client = self._sdk()
        started = time.perf_counter()

        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                # Effort, not temperature. Sampling parameters are rejected on
                # this model family.
                output_config={"effort": self._effort},
            )
        except anthropic.APIStatusError as exc:
            logger.error("llm_api_error", status=exc.status_code, message=str(exc))
            raise
        except anthropic.APIConnectionError as exc:
            logger.error("llm_connection_error", error=str(exc))
            raise

        latency_ms = int((time.perf_counter() - started) * 1000)

        # A refusal arrives as a normal 200 with an empty content list, so
        # indexing content[0] unconditionally would crash on it.
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )

        usage = response.usage
        cost = estimate_cost_usd(response.model, usage.input_tokens, usage.output_tokens)

        completion = Completion(
            text=text,
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            stop_reason=response.stop_reason,
            latency_ms=latency_ms,
            estimated_cost_usd=cost,
            refusal_category=getattr(
                getattr(response, "stop_details", None), "category", None
            ),
        )

        logger.info(
            "llm_complete",
            model=completion.model,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            stop_reason=completion.stop_reason,
            latency_ms=latency_ms,
            cost_usd=round(cost, 6),
        )
        return completion


class StubLLMClient:
    """A scripted client for tests. Records what it was asked."""

    def __init__(self, response: str = "Stub answer.", model: str = "stub-model") -> None:
        self.response = response
        self._model = model
        self.calls: list[tuple[str, str]] = []

    @property
    def model(self) -> str:
        return self._model

    def complete(self, system: str, user: str) -> Completion:
        self.calls.append((system, user))
        return Completion(
            text=self.response,
            model=self._model,
            input_tokens=len(system.split()) + len(user.split()),
            output_tokens=len(self.response.split()),
            stop_reason="end_turn",
            latency_ms=0,
        )
