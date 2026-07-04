from app.agno_runtime.agui_interface import AgnoAguiInterface
from app.services.chat_service import _merge_text_chunks


def test_builds_status_and_message_events() -> None:
    ui = AgnoAguiInterface()

    status_event = ui.build_event(
        event_name="agent_started",
        payload={"agent": "demo-agent"},
        status="running",
        message="Agent is preparing to respond",
    )
    assert status_event["type"] == "status"
    assert status_event["status"] == "running"
    assert status_event["message"] == "Agent is preparing to respond"

    message_event = ui.build_event(
        event_name="RunResponseContent",
        payload={"content": "hello"},
        content="hello",
        is_assistant_content=True,
    )
    assert message_event["type"] == "message"
    assert message_event["message"]["content"] == "hello"
    assert message_event["message"]["role"] == "assistant"


def test_merge_text_chunks_adds_spacing_without_duplicate_overlaps() -> None:
    merged = ""
    merged = _merge_text_chunks(merged, "Nguyễn Văn Tuấn birth date: 1996-04-03")
    merged = _merge_text_chunks(merged, "Nguyễn Văn Tuấn sinh 1996-04-03.")

    assert merged == "Nguyễn Văn Tuấn birth date: 1996-04-03 Nguyễn Văn Tuấn sinh 1996-04-03."
