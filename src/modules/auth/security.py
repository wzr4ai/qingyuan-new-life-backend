# src/modules/auth/security.py

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from jose import jwt, JWTError

from src.core.config import settings
from src.core.database import get_db
from src.shared.models.user_models import User
from src.modules.auth.schemas import TokenPayload

# 这是 FastAPI 用来从 Header 中提取 "Authorization: Bearer <token>" 的标准工具
# tokenUrl="auth/login" 只是一个形式，它告诉文档这个 token 从哪里来
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# 定义我们的 JWT 设置
JWT_SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"

# --- 标准错误 ---

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="无法验证凭据",
    headers={"WWW-Authenticate": "Bearer"},
)

FORBIDDEN_EXCEPTION = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="您没有足够的权限执行此操作",
)

# --- 依赖项 1：获取当前登录的用户（无论角色） ---

async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    解码 JWT Token，获取用户。
    如果 Token 无效或用户不存在，则抛出 401 异常。
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        user_uid: str | None = payload.get("sub")
        
        if user_uid is None:
            raise CREDENTIALS_EXCEPTION
            
        token_data = TokenPayload(sub=user_uid)
        
    except JWTError:
        raise CREDENTIALS_EXCEPTION
    
    # 从数据库中获取用户
    query = select(User).where(User.uid == token_data.sub)
    result = await db.execute(query)
    user = result.scalars().first()
    
    if user is None:
        raise CREDENTIALS_EXCEPTION
        
    return user

# --- 依赖项 2：获取当前管理员用户 (我们即将使用的) ---

async def get_current_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    一个依赖于 get_current_user 的依赖项。
    它确保当前用户不仅已登录，而且角色是 'admin'。
    如果不是 'admin'，则抛出 403 异常。
    """
    if current_user.role != "admin":
        raise FORBIDDEN_EXCEPTION
        
    # 如果角色是 'admin'，则安全返回用户信息
    return current_user