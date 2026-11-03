from fastapi import APIRouter, HTTPException

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.llm_service import LLMServiceError, generate_reply

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        reply = await generate_reply(request.message)
    except LLMServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return ChatResponse(reply=reply)