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


def _chat_url() -> str:
    return f"{settings.ollama_base_url}/api/chat"


def _payload(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    json_schema: dict | None = None,
) -> dict:
    payload: dict = {
        "model": settings.ollama_model,
        "stream": False,
        "options": {
            "temperature": settings.ollama_temperature if temperature is None else temperature
        },
        "messages": messages,
    }
    if json_schema is not None:
        payload["format"] = json_schema
    return payload


def _service_error(exc: httpx.HTTPError) -> LLMServiceError:
    if isinstance(exc, httpx.ConnectError):
        return LLMServiceError("Cannot reach Ollama. Make sure it is running.", 503)
    if isinstance(exc, httpx.TimeoutException):
        return LLMServiceError("The model took too long to respond. Please try again.", 504)
    return LLMServiceError("Unexpected error while contacting Ollama.", 502)


def _content(response: httpx.Response) -> str:
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


async def generate_reply(user_message: str, chunks: list[RetrievedChunk] | None = None) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(user_message, chunks)},
    ]
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
            response = await client.post(_chat_url(), json=_payload(messages))
    except httpx.HTTPError as exc:
        raise _service_error(exc)
    return _content(response)


def chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    json_schema: dict | None = None,
) -> str:
    """Synchronous Ollama chat used by the agent graph (runs in FastAPI's worker thread)."""
    try:
        with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
            response = client.post(_chat_url(), json=_payload(messages, temperature, json_schema))
    except httpx.HTTPError as exc:
        raise _service_error(exc)
    return _content(response)