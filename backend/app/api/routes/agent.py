from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.agent.actions import resolve_pending
from app.agent.graph import run_agent
from app.schemas.agent import AgentChatRequest, AgentChatResponse, ConfirmRequest, ConfirmResponse
from app.security import ai_safety
from app.security.deps import customer_context, rate_limit_user
from app.security.permissions import Permission
from app.services.llm_service import LLMServiceError
from app.tools.support_tools import ToolContext

router = APIRouter(prefix="/api/agent", tags=["agent"])

AgentCtx = Annotated[ToolContext, Depends(customer_context(Permission.AGENT_USE))]
_DB_UNAVAILABLE = "The order system is temporarily unavailable. Please try again shortly."


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    dependencies=[Depends(rate_limit_user("agent_chat", "chat_rate_limit"))],
)
def agent_chat(body: AgentChatRequest, ctx: AgentCtx) -> AgentChatResponse:
    message = ai_safety.sanitize_user_text(body.message)
    if not message:
        raise HTTPException(status_code=422, detail="Message is empty.")
    ctx = ToolContext(db=ctx.db, customer=ctx.customer, principal=ctx.principal, channel="agent")
    try:
        return run_agent(ctx, body.conversation_id, message)
    except LLMServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except SQLAlchemyError:
        ctx.db.rollback()
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE)


@router.post(
    "/confirm",
    response_model=ConfirmResponse,
    dependencies=[Depends(rate_limit_user("agent_confirm", "sensitive_rate_limit"))],
)
def agent_confirm(body: ConfirmRequest, ctx: AgentCtx) -> ConfirmResponse:
    """Deterministic: no LLM involved. Executes only the stored, owned, unexpired, single-use action."""
    ctx = ToolContext(db=ctx.db, customer=ctx.customer, principal=ctx.principal, channel="agent")
    try:
        return resolve_pending(ctx, body.confirmation_id, body.decision)
    except SQLAlchemyError:
        ctx.db.rollback()
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE)