# src/shared/deps/arq.py
from fastapi import Request
from arq.connections import ArqRedis

def get_arq_pool(request: Request) -> ArqRedis:
    """
    一个 FastAPI 依赖项，用于从 app.state 中获取 arq 连接池。
    """
    return request.app.state.arq_pool