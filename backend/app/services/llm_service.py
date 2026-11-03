import httpx

from app.core.config import settings
from app.core.prompts import NO_POLICY_FOUND, SYSTEM_PROMPT
from app.services.retrieval_service import RetrievedChunk

_CONTEXT_TAGS = ("<policy_context>", "</policy_context>")


class LLMServiceError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _neutralize(text: str) -> str:
    for tag in _CONTEXT_TAGS:
        text = text.replace(tag, "")
    return text


def build_user_prompt(question: str, chunks: list[RetrievedChunk] | None) -> str:
    """chunks=None: no retrieval was attempted. chunks=[]: retrieval found nothing relevant."""
    question = _neutralize(question)
    if chunks is None:
        return question

    if chunks:
        context = "\n\n".join(
            f"[{i}] {chunk.source} - {chunk.section}\n{_neutralize(chunk.text)}"
            for i, chunk in enumerate(chunks, start=1)
        )
    else:
        context = NO_POLICY_FOUND

    return f"<policy_context>\n{context}\n</policy_context>\n\nCustomer question: {question}"


async def generate_reply(user_message: str, chunks: list[RetrievedChunk] | None = None) -> str:
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "options": {"temperature": settings.ollama_temperature},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(user_message, chunks)},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
            response = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
    except httpx.ConnectError:
        raise LLMServiceError("Cannot reach Ollama. Make sure it is running.", 503)
    except httpx.TimeoutException:
        raise LLMServiceError("The model took too long to respond. Please try again.", 504)
    except httpx.HTTPError:
        raise LLMServiceError("Unexpected error while contacting Ollama.", 502)

    if response.status_code == 404:
        raise LLMServiceError(
            f"Model '{settings.ollama_model}' is not installed. Run: ollama pull {settings.ollama_model}",
            503,
        )
    if response.status_code != 200:
        raise LLMServiceError(f"Ollama returned status {response.status_code}.", 502)

    try:
        return response.json()["message"]["content"]
    except (ValueError, KeyError, TypeError):
        raise LLMServiceError("Received an unexpected response from Ollama.", 502)