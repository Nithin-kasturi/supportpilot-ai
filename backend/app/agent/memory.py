import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationMemory:
    history: list[dict[str, str]] = field(default_factory=list)
    last_order_number: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)


class MemoryStore:
    """In-process conversation memory keyed by (customer id, conversation id).

    Keying by customer id means a conversation id can never reach another customer's history.
    State is lost on restart; pending confirmations live in SQLite instead.
    """

    def __init__(self, max_conversations: int = 200) -> None:
        self._data: OrderedDict[tuple[int, str], ConversationMemory] = OrderedDict()
        self._max = max_conversations
        self._lock = threading.Lock()

    def get(self, customer_id: int, conversation_id: str) -> ConversationMemory:
        key = (customer_id, conversation_id)
        with self._lock:
            memory = self._data.get(key)
            if memory is None:
                memory = ConversationMemory()
                self._data[key] = memory
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
            return memory


MEMORY = MemoryStore()