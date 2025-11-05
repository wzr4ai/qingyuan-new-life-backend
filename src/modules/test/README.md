# 测试模块 (test)

## 模块职责

此模块包含用于服务健康检查、基准测试和内存监控的非业务性 API 路由。它不应包含任何业务逻辑。

## 核心文件

* **`router.py`**:
    * `GET /test/`: 简单的健康检查。
    * `GET /test/benchmark`: 模拟 CPU 和异步工作的端点。
    * `GET /test/memory`: 报告当前进程的内存使用情况。