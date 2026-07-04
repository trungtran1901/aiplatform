from __future__ import annotations

from typing import Any


class AgnoAguiInterface:
    """Small compatibility layer for emitting AG-UI style progress events.

    The installed Agno version in this workspace does not expose an
    ``agno.agui`` module, so this adapter provides a lightweight, local
    implementation that can be used by the SSE chat stream to surface
    assistant progress and message deltas to a UI layer.
    """

    def __init__(self) -> None:
        self._last_status: str | None = None

    def build_event(
        self,
        *,
        event_name: str,
        payload: dict[str, Any] | None = None,
        content: Any = None,
        is_assistant_content: bool = False,
        status: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        payload = payload or {}
        event_name = event_name or "event"
        normalized_status = self._normalize_status(event_name, status)
        self._last_status = normalized_status

        if content is not None and is_assistant_content:
            return {
                "type": "message",
                "status": normalized_status,
                "message": {
                    "role": "assistant",
                    "content": str(content),
                },
                "event": event_name,
                "payload": payload,
            }

        return {
            "type": "status",
            "status": normalized_status,
            "message": message or self._default_message(event_name),
            "event": event_name,
            "payload": payload,
        }

    def _normalize_status(self, event_name: str, status: str | None) -> str:
        if status:
            return status
        lowered = event_name.lower()
        if "error" in lowered:
            return "error"
        if "tool" in lowered:
            return "tool_call"
        if "reason" in lowered:
            return "thinking"
        if "completed" in lowered or "complete" in lowered:
            return "completed"
        if "started" in lowered:
            return "running"
        return "running"

    def _default_message(self, event_name: str) -> str:
        if "error" in event_name.lower():
            return "The agent hit an error while processing the request."
        if "tool" in event_name.lower():
            return "The agent is using a tool to continue."
        if "reason" in event_name.lower():
            return "The agent is thinking through the request."
        return "The agent is processing your request."


def _merge_text_chunks(existing_text: str, chunk: Any) -> str:
    """Merge streamed assistant text chunks into a coherent message.

    The runtime can emit either incremental deltas or full sentence-sized
    fragments depending on the underlying Agno event payload. This helper
    makes the concatenation deterministic by inserting a separator when
    needed and avoiding duplicate concatenation when the new chunk is the
    same as the existing content.
    """

    if chunk is None:
        return existing_text

    text = str(chunk)
    if not text:
        return existing_text

    if not existing_text:
        return text

    if existing_text == text:
        return existing_text

    if existing_text.endswith(text):
        return existing_text

    if existing_text.endswith((" ", "\n", "\t")) or text.startswith((" ", "\n", "\t")):
        return existing_text + text

    if existing_text[-1] in ".!?:;)]}" and text[0] not in ".,!?;:)]}":
        return existing_text + " " + text

    return existing_text + " " + text
