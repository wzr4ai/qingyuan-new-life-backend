# qingyuan-new-life/backend/src/core/config.py
import os
from pydantic_settings import BaseSettings
from typing import Literal

class Settings(BaseSettings):
    """
    应用全局配置 - 使用 Pydantic 进行类型校验和设置管理
    所有敏感信息都从环境变量或 .env 文件加载
    """
    # --- 环境配置 ---
    ENVIRONMENT: Literal["dev", "test", "prod"] = "prod"

    # --- 核心安全配置 ---
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    # --- 应用运行配置 ---
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8002

    # --- 数据库配置 ---
    MYSQL_USERNAME: str
    MYSQL_PASSWORD: str
    MYSQL_HOST: str
    MYSQL_PORT: int
    DB_NAME: str = "qy_dev"

    # --- redis 配置 ---
    REDIS_PASSWORD: str

    @property
    def DATABASE_URI(self) -> str:
        """计算属性：根据其他配置动态拼接出完整的数据库连接 URI。"""
        return (
            f"mysql+asyncmy://{self.MYSQL_USERNAME}:{self.MYSQL_PASSWORD}@"
            f"{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.DB_NAME}"
        )

    # --- 腾讯云与 COS 配置 ---
    COS_BUCKET: str
    TENCENT_SECRET_ID: str
    TENCENT_SECRET_KEY: str
    COS_REGION: str
    COS_BUCKET_NAME: str
    COS_CDN_URL: str

    # --- 管理员配置 ---
    ADMIN_OPENID: str

    # --- 微信小程序配置 ---
    WECHAT_APP_ID: str
    WECHAT_APP_SECRET: str
    
    XHS_APP_ID: str
    XHS_APP_SECRET: str

    # --- 微信公众号配置 ---
    WECHAT_MP_APP_ID: str
    WECHAT_MP_APP_SECRET: str

    # --- LLM 服务提供商配置 ---
    FAST_MODEL_PROVIDERS: str
    DEEP_MODEL_PROVIDERS: str

    #REDIS_URL: str = property(lambda self: f"redis://:{self.REDIS_PASSWORD}@{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/0")
    REDIS_URL: str = "redis://localhost:6379"
    
    class Config:
        case_sensitive = True
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

# 在应用启动时打印出最终确定的模式和数据库 URI，方便调试
print(f"--- 应用运行在 {settings.ENVIRONMENT.upper()} 模式 ---")
print(f"数据库 URI: {settings.DATABASE_URI}")
print(f"使用的 COS 存储桶: {settings.COS_BUCKET}")
print("---------------------------------------------")