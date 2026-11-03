from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.schemas.chat import ChatRequest, ChatResponse, Source
from app.services.llm_service import LLMServiceError, generate_reply
from app.services.retrieval_service import KnowledgeBaseEmptyError, needs_policy_lookup, retrieve

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    chunks = None
    if needs_policy_lookup(request.message):
        try:
            chunks = await run_in_threadpool(retrieve, request.message)
        except KnowledgeBaseEmptyError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

    try:
        reply = await generate_reply(request.message, chunks)
    except LLMServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    sources = [
        Source(
            document=c.source,
            category=c.category,
            section=c.section,
            chunk_id=c.chunk_id,
            similarity=c.similarity,
        )
        for c in chunks or []
    ]
    return ChatResponse(reply=reply, sources=sources)