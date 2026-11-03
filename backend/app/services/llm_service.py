import httpx

from app.core.config import settings
from app.core.prompts import SYSTEM_PROMPT


class LLMServiceError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def generate_reply(user_message: str) -> str:
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
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