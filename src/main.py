# qingyuan-new-life/backend/src/main.py
from fastapi import FastAPI
#from core.lifespan import lifespan

from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.modules.auth.router import router as auth_router
from src.modules.test.router import router as test_router
from src.modules.admin.router import router as admin_router
from src.modules.schedule.router import router as schedule_router

import asyncio
import time
import psutil
import os

# 根据不同环境动态设置 API 根路径
api_root_path = ""
if settings.ENVIRONMENT and settings.ENVIRONMENT.lower() != "prod":
    api_root_path = f"/{settings.ENVIRONMENT}"

app = FastAPI(
    title="青元新生 后端服务",
    description="青元新生项目的后端服务，提供API接口支持。",
    version="0.0.1",
    #lifespan=lifespan,
    root_path=api_root_path,
    # 仅在非生产环境下启用文档
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
)

# 定义允许的跨域来源
origins = [
    "http://localhost",
    "http://localhost:8000",
    "http://localhost:3000",
    "https://admin.qyxs.online",
    "https://qyxs.online",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 添加一个根路径，用于健康检查或欢迎信息
@app.get("/status", summary="服务根路径", tags=["Default"])
async def read_root():
    """
    欢迎信息或健康检查端点
    """
    status = {
        "service": "Qingyuan New Life Backend",
        "status": "running",
        "environment": settings.ENVIRONMENT,
        "timestamp": time.time()
    }
    return status

app.include_router(auth_router, prefix="/auth") # 用户认证相关路由
app.include_router(test_router, prefix="/test") # 测试相关路由
app.include_router(admin_router, prefix="/admin") # 管理后台相关路由
app.include_router(schedule_router, prefix="/schedule") # 预约调度相关路由
