from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.orm import Session

from app.core.demo_identity import get_current_customer
from app.database.session import get_db
from app.models import Customer
from app.schemas.refunds import EligibilityRequest, EligibilityResult, RefundRequestOut
from app.schemas.tools import CreateRefundOutput, CreateRefundRequestInput, ToolResult
from app.services import order_service, refund_service
from app.services.order_service import OrderNotFoundError
from app.services.refund_eligibility_service import check_eligibility
from app.tools import support_tools
from app.tools.support_tools import ToolContext

router = APIRouter(prefix="/api", tags=["refunds"])

OrderNumber = Annotated[str, Path(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9-]+$")]
CurrentCustomer = Annotated[Customer, Depends(get_current_customer)]
DbSession = Annotated[Session, Depends(get_db)]

_ERROR_STATUS = {
    "ORDER_NOT_FOUND": 404,
    "NOT_ELIGIBLE": 409,
    "MANUAL_REVIEW_REQUIRED": 409,
    "DUPLICATE_REQUEST": 409,
}


def _http_status(result: ToolResult[CreateRefundOutput]) -> int:
    if not result.ok:
        return _ERROR_STATUS.get(result.error.code, 400)
    return 201 if result.data.outcome == "created" else 200


@router.get("/refund-requests", response_model=list[RefundRequestOut])
def list_my_refund_requests(customer: CurrentCustomer, db: DbSession) -> list[RefundRequestOut]:
    return refund_service.list_refund_requests(db, customer.id)


@router.post("/orders/{order_number}/refund-eligibility", response_model=EligibilityResult)
def check_my_refund_eligibility(
    order_number: OrderNumber, body: EligibilityRequest, customer: CurrentCustomer, db: DbSession
) -> EligibilityResult:
    try:
        order = order_service.get_order(db, customer.id, order_number)
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found.")
    return check_eligibility(order, body.reason, body.evidence_photo_count)


@router.post("/refund-requests", response_model=ToolResult[CreateRefundOutput])
def create_my_refund_request(
    body: CreateRefundRequestInput, response: Response, customer: CurrentCustomer, db: DbSession
) -> ToolResult[CreateRefundOutput]:
    result = support_tools.create_refund_request(ToolContext(db=db, customer=customer), body)
    response.status_code = _http_status(result)
    return result