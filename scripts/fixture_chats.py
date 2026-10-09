"""Sample assistant chats: their log lines and the trace of each one.

Each chat is one ``POST /v2/assistant/chat`` request. Its lines and its trace
share the request's ``trace_id``, and each line's span id is the span that
wrote it, with span names from the telemetry contract section 4.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from scripts.fixture_core import (
    CHAT_MODEL,
    CHAT_ROUTE,
    Ids,
    Line,
    Request,
    app_error_line,
    http_request_line,
    log_line,
    milliseconds,
    stamp,
)

_ASSISTANT = "assistant.services.assistant_service"
_NOT_AVAILABLE = "backend.app.exceptions.AssistantNotAvailableError"


@dataclass
class _Span:
    span_id: str
    parent_id: str | None
    name: str
    start: datetime
    end: datetime
    attributes: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "start": stamp(self.start),
            "end": stamp(self.end),
            "attributes": self.attributes,
            "events": self.events,
        }


class Chat:
    """Builds one chat request's lines and spans on a moving clock."""

    def __init__(
        self, ids: Ids, rng: random.Random, moment: datetime, user: str
    ) -> None:
        """Start a chat for ``user`` at ``moment``."""
        self._ids = ids
        self.rng = rng
        self.request = Request.new(ids, "POST", CHAT_ROUTE, user)
        self.started = moment
        self.now = moment
        self.lines: list[Line] = []
        self.root = _Span(
            self.request.span_id,
            None,
            f"POST {CHAT_ROUTE}",
            moment,
            moment,
            {"http.request.method": "POST", "http.route": CHAT_ROUTE},
        )
        self.spans = [self.root]

    def wait(self, median_ms: float) -> int:
        """Move the clock on by a lognormal duration; return it in ms."""
        took = max(1, round(median_ms * self.rng.lognormvariate(0, 0.3)))
        self.now += milliseconds(took)
        return took

    def open(self, name: str, parent: _Span, **attributes: Any) -> _Span:
        """Open a child span of ``parent`` at the current time."""
        span = _Span(
            self._ids.hex(16), parent.span_id, name, self.now, self.now, attributes
        )
        self.spans.append(span)
        return span

    def close(self, span: _Span) -> None:
        """Close ``span`` at the current time."""
        span.end = self.now

    def log(self, event: str, message: str, span: _Span, **attributes: Any) -> None:
        """Write a line from ``span`` at the current time."""
        self.lines.append(
            log_line(
                self.now,
                event,
                message,
                attributes,
                logger=_ASSISTANT,
                request=self.request,
                span_id=span.span_id,
            )
        )

    def answer(
        self, status: int, error_code: str | None
    ) -> tuple[list[Line], dict[str, Any]]:
        """Close the request; return its lines and its trace."""
        self.now += milliseconds(2)
        self.root.end = self.now
        self.root.attributes["http.response.status_code"] = status
        closing = http_request_line(
            self.started, self.now, self.request, status, error_code
        )
        trace = {
            "trace_id": self.request.trace_id,
            "spans": [span.to_json() for span in self.spans],
        }
        return [*self.lines, closing], trace


def ollama_call(chat: Chat, parent: _Span, outcomes: tuple[str, ...]) -> bool:
    """Call ``ollama_chat`` once per outcome, retrying failures; True on success."""
    for attempt, status in enumerate(outcomes, start=1):
        span = chat.open("dependency.ollama_chat", parent, attempt=attempt)
        chat.wait(2400 if status == "ok" else 30000)
        chat.close(span)
        chat.log(
            "dependency.call",
            f"Ollama chat call finished: {status}",
            span,
            dependency="ollama_chat",
            operation="chat",
            status=status,
            http_status=200 if status == "ok" else None,
            attempt=attempt,
            duration_ms=round((span.end - span.start).total_seconds() * 1000),
        )
        if status == "ok":
            return True
        if attempt < len(outcomes):
            wait_ms = 500 * 2 ** (attempt - 1)
            retry = {"attempt": attempt, "wait_ms": wait_ms, "cause": status}
            span.events.append(
                {"name": "retry", "timestamp": stamp(chat.now), "attributes": retry}
            )
            chat.log(
                "retry",
                "Ollama chat call failed; retrying",
                span,
                dependency="ollama_chat",
                operation="chat",
                max_attempts=len(outcomes),
                **retry,
            )
            chat.wait(wait_ms)
    return False


def retrieve(chat: Chat, top_score: float) -> None:
    """Embed the question and search the index."""
    retrieve_span = chat.open("assistant.retrieve", chat.root)
    embed = chat.open("assistant.embed", retrieve_span)
    dependency = chat.open("dependency.ollama_embed", embed, attempt=1)
    took = chat.wait(80)
    chat.close(dependency)
    chat.log(
        "dependency.call",
        "Ollama embed call finished: ok",
        dependency,
        dependency="ollama_embed",
        operation="embed",
        status="ok",
        http_status=200,
        attempt=1,
        duration_ms=took,
    )
    chat.close(embed)
    chat.wait(15)
    chat.close(retrieve_span)
    retrieve_span.attributes["top_score"] = top_score


def tool_call(chat: Chat, tool: str, status: str = "ok") -> None:
    """Run one assistant tool."""
    span = chat.open(f"assistant.tool.{tool}", chat.root)
    took = chat.wait(60)
    chat.close(span)
    error = "Unknown team in the served season" if status == "error" else None
    chat.log(
        "assistant.tool",
        f"Tool {tool} finished: {status}",
        span,
        tool=tool,
        status=status,
        duration_ms=took,
        error=error,
    )


def route_check(chat: Chat, matched: bool) -> None:
    """Run the season router's check."""
    span = chat.open("assistant.route", chat.root, matched=matched)
    chat.wait(2)
    chat.close(span)


def generate(
    chat: Chat, round_number: int, outcomes: tuple[str, ...] = ("ok",)
) -> bool:
    """Run one model round; True when the model answered."""
    span = chat.open("assistant.generate", chat.root, round=round_number)
    answered = ollama_call(chat, span, outcomes)
    chat.close(span)
    return answered


def _answer_line(
    chat: Chat, path: str, retrieved: int, top_score: float | None, tool_rounds: int
) -> None:
    by_model = path != "router"
    chat.log(
        "assistant.answer",
        f"Chat answered on the {path} path",
        chat.root,
        path=path,
        question_chars=chat.rng.randint(18, 160),
        retrieved_count=retrieved,
        top_score=top_score,
        confidence=round(top_score or 0.9, 2) if by_model else 0.95,
        tool_rounds=tool_rounds,
        model=CHAT_MODEL,
        prompt_tokens=chat.rng.randint(900, 2400) if by_model else None,
        completion_tokens=chat.rng.randint(80, 320) if by_model else None,
        cost_usd=None,
        duration_ms=round((chat.now - chat.started).total_seconds() * 1000),
    )


def degraded(chat: Chat) -> tuple[list[Line], dict[str, Any]]:
    """The assistant did not load at startup, so the chat gets a 503."""
    chat.wait(3)
    chat.lines.append(
        log_line(
            chat.now,
            "component.degraded",
            "Chat needs the assistant, which is not loaded",
            {"component": "assistant", "route": CHAT_ROUTE},
            logger="backend.app.dependencies",
            request=chat.request,
        )
    )
    error = "Assistant not available"
    chat.lines.append(
        app_error_line(chat.now, chat.request, 503, error, _NOT_AVAILABLE)
    )
    return chat.answer(503, error)


def with_tools(chat: Chat, tools: tuple[str, ...]) -> tuple[list[Line], dict[str, Any]]:
    """The model calls ``tools`` in one round, then answers."""
    route_check(chat, matched=False)
    retrieve(chat, top_score=0.78)
    generate(chat, 1)
    for tool in tools:
        tool_call(chat, tool)
    generate(chat, 2)
    _answer_line(chat, "model_with_tools", 5, 0.78, 1)
    return chat.answer(200, None)


def model_only(
    chat: Chat, top_score: float, outcomes: tuple[str, ...] = ("ok",)
) -> tuple[list[Line], dict[str, Any]]:
    """The model answers from retrieval alone, after ``outcomes`` attempts."""
    route_check(chat, matched=False)
    retrieve(chat, top_score=top_score)
    if not generate(chat, 1, outcomes):
        error = "Assistant not available"
        chat.lines.append(
            app_error_line(chat.now, chat.request, 503, error, _NOT_AVAILABLE)
        )
        return chat.answer(503, error)
    _answer_line(chat, "model", 5, top_score, 0)
    if top_score < 0.4:
        chat.log(
            "assistant.abstain",
            "The answer says the assistant does not know",
            chat.root,
            reason="low_score",
        )
    return chat.answer(200, None)


def season_router(chat: Chat) -> tuple[list[Line], dict[str, Any]]:
    """The season router answers with a tool and no model call."""
    route_check(chat, matched=True)
    tool_call(chat, "league_table")
    _answer_line(chat, "router", 0, None, 0)
    return chat.answer(200, None)


def tool_limit(chat: Chat) -> tuple[list[Line], dict[str, Any]]:
    """The tool loop hits its round limit; the model answers without tools."""
    route_check(chat, matched=False)
    retrieve(chat, top_score=0.66)
    for round_number, (tool, status) in enumerate(
        (("team_matches", "ok"), ("predict_match", "error"), ("predict_match", "ok")),
        start=1,
    ):
        generate(chat, round_number)
        tool_call(chat, tool, status)
    chat.log(
        "fallback",
        "Tool round limit reached; answering without tools",
        chat.root,
        from_path="tool_calling",
        to_path="answer_without_tools",
        cause="tool_round_limit",
    )
    generate(chat, 4)
    _answer_line(chat, "model_with_tools", 5, 0.66, 3)
    return chat.answer(200, None)


def chats(
    ids: Ids, rng: random.Random, users: tuple[str, ...], starts: tuple[datetime, ...]
) -> tuple[list[Line], list[dict[str, Any]]]:
    """Return the lines and traces of the ten sample chats, one per start time."""
    plans = (
        degraded,
        degraded,
        lambda c: model_only(c, 0.74, ("timeout", "timeout", "ok")),
        lambda c: model_only(c, 0.70, ("connection_error",) * 3),
        lambda c: with_tools(c, ("predict_match",)),
        season_router,
        lambda c: model_only(c, 0.31),
        tool_limit,
        lambda c: with_tools(c, ("upcoming_fixtures", "explain_match")),
        lambda c: model_only(c, 0.81),
    )
    lines: list[Line] = []
    traces: list[dict[str, Any]] = []
    for index, (plan, moment) in enumerate(zip(plans, starts, strict=True)):
        chat_lines, trace = plan(Chat(ids, rng, moment, users[index % len(users)]))
        lines += chat_lines
        traces.append(trace)
    return lines, traces
