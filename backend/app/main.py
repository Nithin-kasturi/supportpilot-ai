import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.embeddings import get_model
from app.api.routes.admin import router as admin_router
from app.api.routes.agent import router as agent_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.orders import router as orders_router
from app.api.routes.refunds import router as refunds_router
from app.api.routes.staff import router as staff_router
from app.api.routes.tickets import router as tickets_router
from app.core.config import settings
from app.database.session import init_db
from app.security.logging_filter import install_redaction
from app.security.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware

install_redaction()
logger = logging.getLogger("supportpilot")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_for_serving()  # refuses to start with an insecure configuration
    await run_in_threadpool(init_db)
    await run_in_threadpool(get_model)
    yield


is_dev = settings.app_env == "development"
app = FastAPI(
    title="SupportPilot AI",
    version="0.5.0",
    lifespan=lifespan,
    docs_url="/docs" if is_dev else None,
    redoc_url=None,
    openapi_url="/openapi.json" if is_dev else None,
)

# Added innermost first: body limit -> security headers -> CORS (outermost).
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "X-Requested-With", "Authorization"],
)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    # Generic body for clients; the log gets the exception type (redacted), not internals.
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, type(exc).__name__,
                 exc_info=is_dev)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


for router in (
    auth_router, chat_router, agent_router, orders_router,
    refunds_router, tickets_router, staff_router, admin_router,
):
    app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}