"""
Explicit "remember" tool - AgentX v2.

PROBLEM THIS SOLVES: Agno's own agentic memory (agno.memory.v2.Memory +
MemoryManager, wired in _build_agno_agent via enable_user_memories=True)
decides WHAT is worth remembering via its own internal LLM call, AFTER
a run completes. That is inherently non-deterministic - there is no
guarantee that an explicit "hãy nhớ tôi là Tuấn" gets extracted, since
it depends on Agno's own MemoryManager prompt/model behavior, which this
codebase does not control.

This tool gives the Agent a DETERMINISTIC alternative for the common
case: the user explicitly asks to be remembered. Calling
`remember_fact` writes directly and synchronously to `agent_memories`
via the existing MemoryService.record() - no LLM judgment call in the
loop at all for this path. It complements (does not replace) Agno's own
automatic extraction, which still runs independently for implicit facts
the user didn't explicitly ask to be remembered.

Only available when user_id is present (same condition
enable_user_memories already uses) - remembering is meaningless without
knowing whose memory it is, same rationale as the existing Memory setup
in app/agno_runtime/engine.py::_build_agno_agent.
"""
from __future__ import annotations

import uuid
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.memory import MemoryType
from app.services.memory_service import MemoryService

logger = get_logger(__name__)

MEMORY_INSTRUCTIONS_SECTION = """# Memory
Bạn có khả năng ghi nhớ thông tin lâu dài về người dùng qua tool `remember_fact`.
BẮT BUỘC gọi tool `remember_fact` NGAY LẬP TỨC (không chỉ trả lời bằng lời) khi:
- Người dùng dùng các từ như "hãy nhớ", "ghi nhớ", "nhớ giúp tôi", "đừng quên"
- Người dùng cung cấp thông tin cá nhân quan trọng nên được nhớ cho lần sau
  (tên, vai trò, sở thích, thông tin liên hệ, ngữ cảnh công việc lặp lại...)
Không tự cho rằng cơ chế tự động sẽ lưu giúp bạn - nếu người dùng yêu cầu
tường minh, PHẢI gọi tool này, không chỉ xác nhận bằng lời rồi bỏ qua."""


def build_remember_tool(
    session: AsyncSession, agent_id: uuid.UUID, user_id: str | None
) -> Callable | None:
    """Returns the remember_fact tool callable, or None if user_id is
    absent (mirrors the same guard enable_user_memories already applies
    in _build_agno_agent) - callers can always safely append whatever
    this returns to the tools list without checking anything themselves."""
    if not user_id:
        return None

    memory_service = MemoryService(session)

    async def remember_fact(fact: str) -> str:
        """Save one specific fact about the current user for future
        conversations - e.g. their name, role, preference, or any
        explicit instruction to remember something. Call this
        IMMEDIATELY whenever the user asks you to remember/note
        something, rather than just acknowledging it in your reply.
        `fact` should be a short, self-contained statement (e.g. 'Tên
        người dùng là Tuấn'), not a full sentence copied verbatim from
        the conversation."""
        await memory_service.record(
            agent_id,
            user_id=user_id,
            memory_type=MemoryType.fact,
            content=fact,
        )
        logger.info("explicit_memory_saved", agent_id=str(agent_id), user_id=user_id, fact=fact)
        return f"Đã ghi nhớ: {fact}"

    return remember_fact