# src/modules/auth/schemas.py

from pydantic import BaseModel, ConfigDict
from typing import Optional, List

class WxLoginRequest(BaseModel):
    """
    微信登录请求体
    """
    code: str

class TokenResponse(BaseModel):
    """
    返回给客户端的 Token
    """
    access_token: str
    token_type: str = "bearer"

class TokenPayload(BaseModel):
    """
    JWT Token 中存储的数据
    """
    sub: str  # subject, 存储 user_uid

class AdminLoginRequest(BaseModel):
    """
    管理员 H5 登录请求体
    """
    phone: str
    password: str

class UserInfoResponse(BaseModel):
    """
    用于 'GET /auth/me' 接口返回
    """
    uid: str
    role: str
    nickname: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)