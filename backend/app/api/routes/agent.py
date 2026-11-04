from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.actions import resolve_pending
from app.agent.graph import run_agent
from app.core.demo_identity import get_current_customer
from app.database.session import get_db
from app.models import Customer
from app.schemas.agent import AgentChatRequest, AgentChatResponse, ConfirmRequest, ConfirmResponse
from app.services.llm_service import LLMServiceError
from app.tools.support_tools import ToolContext

router = APIRouter(prefix="/api/agent", tags=["agent"])

CurrentCustomer = Annotated[Customer, Depends(get_current_customer)]
DbSession = Annotated[Session, Depends(get_db)]

_DB_UNAVAILABLE = "The order system is temporarily unavailable. Please try again shortly."


@router.post("/chat", response_model=AgentChatResponse)
def agent_chat(body: AgentChatRequest, customer: CurrentCustomer, db: DbSession) -> AgentChatResponse:
    ctx = ToolContext(db=db, customer=customer)
    try:
        return run_agent(ctx, body.conversation_id, body.message)
    except LLMServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE)


@router.post("/confirm", response_model=ConfirmResponse)
def agent_confirm(body: ConfirmRequest, customer: CurrentCustomer, db: DbSession) -> ConfirmResponse:
    """Deterministic: no LLM involved. Executes only the stored, owned, unexpired, single-use action."""
    try:
        return resolve_pending(ToolContext(db=db, customer=customer), body.confirmation_id, body.decision)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE)