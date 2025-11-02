# src/core/database.py

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

# 从您的 config.py 导入 settings 实例
from src.core.config import settings

# 1. 创建异步引擎
#    我们直接使用您在 config.py 中定义的 DATABASE_URI
engine = create_async_engine(
    settings.DATABASE_URI,
    echo=True,  # 在开发环境中打印 SQL 语句，方便调试
    pool_pre_ping=True
)

# 2. 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # 异步会话中推荐
)

# 3. 创建所有模型都将继承的 Base 类
class Base(DeclarativeBase):
    pass

# 4. 数据库依赖项 (异步版本)
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖项，用于获取异步数据库会话。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # 注意：在异步中，我们通常不在依赖项中 commit。
            # Service 层负责 commit 或 rollback。
            # 如果您希望在请求结束时自动提交，可以取消下面这行注释
            # await session.commit() 
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()