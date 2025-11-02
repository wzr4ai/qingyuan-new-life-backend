import time
import asyncio
import psutil
import os
from fastapi import APIRouter

router = APIRouter(
    tags=["Test 测试"],
    responses={404: {"description": "Not found"}},
)

@router.get("/")
async def test_endpoint():
    """简单的健康检查端点，返回200状态码"""
    return {
        "status": "success", 
        "message": "test endpoint", 
        "timestamp": time.time()
    }

@router.get("/benchmark")
async def benchmark_endpoint():
    """模拟一些计算工作的基准测试端点"""
    # 模拟一些CPU工作
    start = time.time()
    n = 1000
    result = sum(i * i for i in range(n))
    
    # 模拟数据库查询或API调用（异步等待）
    await asyncio.sleep(0.001)  # 1ms的异步等待
    
    processing_time = time.time() - start
    
    return {
        "status": "success",
        "result": result,
        "processing_time_ms": round(processing_time * 1000, 2),
        "timestamp": time.time()
    }

@router.get("/memory")
async def memory_info():
    process = psutil.Process(os.getpid())
    return {
        "memory_mb": process.memory_info().rss / 1024 / 1024
        #"workers": 2  # 你的worker数量
    }