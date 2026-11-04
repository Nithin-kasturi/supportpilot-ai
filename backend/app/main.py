from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from app.ai.embeddings import get_model
from app.api.routes.chat import router as chat_router
from app.api.routes.orders import router as orders_router
from app.api.routes.refunds import router as refunds_router
from app.api.routes.tickets import router as tickets_router
from app.core.demo_identity import log_demo_identity_warning
from app.database.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    await run_in_threadpool(init_db)
    log_demo_identity_warning()
    await run_in_threadpool(get_model)
    yield


app = FastAPI(title="SupportPilot AI", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)

app.include_router(chat_router)
app.include_router(orders_router)
app.include_router(refunds_router)
app.include_router(tickets_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}