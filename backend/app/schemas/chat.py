from typing import Annotated

from pydantic import BaseModel, StringConstraints

UserMessage = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ChatRequest(BaseModel):
    message: UserMessage


class ChatResponse(BaseModel):
    reply: str