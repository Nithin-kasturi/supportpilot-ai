from datetime import datetime
from typing import Annotated

from pydantic import PlainSerializer

# Database timestamps are naive UTC. Serialize with a trailing "Z" so browsers read them as UTC.
UtcDatetime = Annotated[
    datetime,
    PlainSerializer(lambda d: d.isoformat(timespec="seconds") + "Z", return_type=str),
]