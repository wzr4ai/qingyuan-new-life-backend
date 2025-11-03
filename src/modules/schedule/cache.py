import json
from datetime import datetime
from typing import Optional

from redis import Redis

REDIS_EXPIRE_SECONDS = 30


def get_redis_client() -> Optional[Redis]:
    try:
        return Redis(host='localhost', port=6379, decode_responses=True)
    except Exception:
        return None


def build_cache_key(prefix: str, *parts: str) -> str:
    base_parts = [prefix, *parts]
    return ':'.join(filter(None, base_parts))


def get_cache_value(key: str) -> Optional[dict]:
    client = get_redis_client()
    if not client:
        return None
    raw = client.get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if 'timestamp' in data:
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return data
    except Exception:
        return None


def set_cache_value(key: str, value: dict, expire_seconds: int = REDIS_EXPIRE_SECONDS) -> None:
    client = get_redis_client()
    if not client:
        return
    payload = value.copy()
    if 'timestamp' in payload and isinstance(payload['timestamp'], datetime):
        payload['timestamp'] = payload['timestamp'].isoformat()
    client.set(key, json.dumps(payload), ex=expire_seconds)


def clear_cache(prefix: str, *parts: str) -> None:
    client = get_redis_client()
    if not client:
        return
    pattern = build_cache_key(prefix, *parts)
    for key in client.scan_iter(pattern + '*'):
        client.delete(key)
