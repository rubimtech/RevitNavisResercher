import json
import time
from typing import Any

import pydantic

_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300


def cache_get(key: str) -> Any:
    entry = _cache.get(key)
    if entry and time.monotonic() - entry[0] < _CACHE_TTL:
        return entry[1]
    if entry:
        del _cache[key]
    return None


def cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)
    if len(_cache) > 200:
        stale = [k for k, v in _cache.items() if time.monotonic() - v[0] >= _CACHE_TTL]
        for k in stale:
            del _cache[k]


def cache_key(req: pydantic.BaseModel) -> str:
    return f"{type(req).__name__}:{json.dumps(req.model_dump(), sort_keys=True)}"
