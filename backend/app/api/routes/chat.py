from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.schemas.chat import ChatRequest, ChatResponse, Source
from app.security import ai_safety, pii
from app.security.deps import rate_limit_user, require_permission
from app.security.permissions import Permission
from app.security.principal import Principal
from app.services.llm_service import LLMServiceError, generate_reply
from app.services.retrieval_service import KnowledgeBaseEmptyError, needs_policy_lookup, retrieve

router = APIRouter(prefix="/api", tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(rate_limit_user("chat", "chat_rate_limit"))],
)
async def chat(
    request: ChatRequest,
    _: Annotated[Principal, Depends(require_permission(Permission.AGENT_USE))],
) -> ChatResponse:
    message = pii.mask_pii(ai_safety.sanitize_user_text(request.message))
    if not message:
        raise HTTPException(status_code=422, detail="Message is empty.")

    chunks = None
    if needs_policy_lookup(message):
        try:
            chunks = await run_in_threadpool(retrieve, message)
        except KnowledgeBaseEmptyError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        chunks, _quarantined = ai_safety.screen_chunks(chunks)

    try:
        reply = await generate_reply(message, chunks)
    except LLMServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    sources = [
        Source(document=c.source, category=c.category, section=c.section,
               chunk_id=c.chunk_id, similarity=c.similarity)
        for c in chunks or []
    ]
    return ChatResponse(reply=ai_safety.filter_reply(reply, []), sources=sources)