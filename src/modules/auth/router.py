# src/modules/auth/router.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.auth.security import get_current_user
from src.shared.models.user_models import User
from src.core.database import get_db
from . import service as auth_service
from .schemas import WxLoginRequest, TokenResponse, AdminLoginRequest, UserInfoResponse

router = APIRouter(
    tags=["Authentication 用户认证"],
    responses={404: {"description": "Not found"}},
)

@router.post(
    "/wx-login",
    response_model=TokenResponse,
    summary="微信小程序登录"
)
async def wx_login(
    request_data: WxLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    V3:
    - 接收前端 `wx.login()` 获取的 code。
    - 向微信服务器换取 openid。
    - 查找或创建 SocialAccount，并关联/创建 User。
    - 返回 JWT access_token。
    """
    
    # 1. 用 code 换取 session
    try:
        wechat_session = await auth_service.exchange_code_for_session(request_data.code)
    except HTTPException as e:
        raise e 
        
    openid = wechat_session.get("openid")
    if not openid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未能从微信获取 openid"
        )
    
    # --- 2. V3 逻辑变更 ---
    # 调用新的 service 函数
    user = await auth_service.get_or_create_user_by_social(
        db=db,
        provider="wechat",
        provider_id=openid
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="无法获取或创建用户"
        )

    # 3. 创建 Access Token (保持不变)
    access_token = auth_service.create_access_token(subject=user.uid)
    
    return TokenResponse(access_token=access_token)

@router.post(
    "/admin-login",
    response_model=TokenResponse,
    summary="管理员 H5 登录 (手机号+密码)"
)
async def admin_login(
    login_data: AdminLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    (Admin/Technician Only)
    用于 H5 管理后台的登录。
    """
    user = await auth_service.authenticate_admin_user(db, login_data)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="手机号或密码错误，或账户非管理员/技师",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 登录成功，创建 Token
    access_token = auth_service.create_access_token(subject=user.uid)
    
    return TokenResponse(access_token=access_token)

@router.get(
    "/me",
    response_model=UserInfoResponse,
    summary="获取当前登录用户信息 (V7)"
)
async def read_users_me(
    current_user: User = Depends(get_current_user) # <-- 核心：自动验证 Token
):
    """
    (Customer, Technician, Admin)
    获取当前已认证用户的详细信息。
    前端在登录成功后必须调用此接口，以获取用户的 `role`。
    """
    # current_user 是从 get_current_user 依赖注入的
    # SQLAlchemy (Async) 模型对象
    return current_user

# --- 未来扩展 ---
# @router.post("/xhs-login", ...)
# async def xhs_login(...):
#     ...
#     xhs_session = await auth_service.exchange_xhs_code(...)
#     xhs_open_id = xhs_session.get("open_id")
#     user = await auth_service.get_or_create_user_by_social(
#         db=db,
#         provider="xiaohongshu",
#         provider_id=xhs_open_id
#     )
#     ...
#     return TokenResponse(...)