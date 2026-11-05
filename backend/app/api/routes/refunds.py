from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from app.schemas.refunds import EligibilityRequest, EligibilityResult, RefundRequestOut
from app.schemas.tools import (
    CheckRefundEligibilityInput,
    CreateRefundOutput,
    CreateRefundRequestInput,
    ToolResult,
)
from app.security import audit
from app.security.deps import customer_context, rate_limit_user
from app.security.permissions import Permission
from app.services import refund_service
from app.tools import support_tools
from app.tools.support_tools import ToolContext

router = APIRouter(prefix="/api", tags=["refunds"])

OrderNumber = Annotated[str, Path(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9-]+$")]
Reference = Annotated[str, Path(min_length=6, max_length=20, pattern=r"^[A-Za-z]{2}-[A-Za-z0-9]{4,16}$")]

ReadCtx = Annotated[ToolContext, Depends(customer_context(Permission.REFUNDS_READ_OWN))]
CheckCtx = Annotated[ToolContext, Depends(customer_context(Permission.REFUNDS_CHECK_OWN))]
CreateCtx = Annotated[ToolContext, Depends(customer_context(Permission.REFUNDS_CREATE_OWN))]

_ERROR_STATUS = {
    "ORDER_NOT_FOUND": 404,
    "FORBIDDEN": 403,
    "NOT_ELIGIBLE": 409,
    "MANUAL_REVIEW_REQUIRED": 409,
    "DUPLICATE_REQUEST": 409,
}


@router.get("/refund-requests", response_model=list[RefundRequestOut])
def list_my_refund_requests(ctx: ReadCtx) -> list[RefundRequestOut]:
    rows = refund_service.list_refund_requests(ctx.db, ctx.customer.id)
    audit.record("refund.list", "success", principal=ctx.principal, resource_type="refund_request",
                 detail=f"count={len(rows)}")
    return rows


@router.get("/refund-requests/{reference}", response_model=RefundRequestOut)
def get_my_refund_request(reference: Reference, ctx: ReadCtx) -> RefundRequestOut:
    row = refund_service.get_request(ctx.db, ctx.customer.id, reference)
    if row is None:
        audit.record_denied_lookup(ctx.principal, "refund_request", reference.upper())
        raise HTTPException(status_code=404, detail="Refund request not found.")
    audit.record("refund.view", "success", principal=ctx.principal, resource_type="refund_request",
                 resource_id=row.reference)
    return row


@router.post("/orders/{order_number}/refund-eligibility", response_model=EligibilityResult)
def check_my_refund_eligibility(
    order_number: OrderNumber, body: EligibilityRequest, ctx: CheckCtx
) -> EligibilityResult:
    result = support_tools.check_refund_eligibility(
        ctx,
        CheckRefundEligibilityInput(
            order_number=order_number, reason=body.reason, evidence_photo_count=body.evidence_photo_count
        ),
    )
    if not result.ok or result.data is None:
        code = result.error.code if result.error else ""
        raise HTTPException(
            status_code=_ERROR_STATUS.get(code, 400),
            detail=result.error.message if result.error else "Request failed.",
        )
    return result.data


@router.post(
    "/refund-requests",
    response_model=ToolResult[CreateRefundOutput],
    dependencies=[Depends(rate_limit_user("refund_create", "sensitive_rate_limit"))],
)
def create_my_refund_request(
    body: CreateRefundRequestInput, response: Response, ctx: CreateCtx
) -> ToolResult[CreateRefundOutput]:
    result = support_tools.create_refund_request(ctx, body)
    if not result.ok:
        response.status_code = _ERROR_STATUS.get(result.error.code, 400)
    else:
        response.status_code = 201 if result.data.outcome == "created" else 200
    return result