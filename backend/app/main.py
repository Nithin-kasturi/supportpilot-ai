from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from app.ai.embeddings import get_model
from app.api.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    await run_in_threadpool(get_model)
    yield


app = FastAPI(title="SupportPilot AI", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)

app.include_router(chat_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
