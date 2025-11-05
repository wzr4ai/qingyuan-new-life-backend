# 认证模块 (auth)

## 模块职责

此模块处理所有与用户身份验证和授权相关的逻辑。

## 核心文件

* **`router.py`**:
    * `POST /auth/wx-login`: 微信小程序登录/注册的入口点。
    * `POST /auth/admin-login`: 管理员/技师使用手机号和密码登录的入口点。
    * `GET /auth/me`: 允许已认证用户获取自己详细信息 (如 `role`) 的入口点。
* **`service.py`**:
    * `exchange_code_for_session`: 调用微信 API 用 code 换取 openid。
    * `get_or_create_user_by_social`: 核心登录逻辑，根据 openid 查找或创建 `User` 和 `SocialAccount`。
    * `authenticate_admin_user`: 验证管理员/技师的手机号和密码。
    * `create_access_token`: 生成 JWT。
* **`security.py`**:
    * 定义 FastAPI 的核心安全依赖项。
    * `oauth2_scheme`: 定义 Bearer Token 方案。
    * `get_current_user`: **(极其重要)** 解码 JWT 并从数据库中获取当前登录的 `User` 对象。这是保护大多数 API 的基础。
    * `get_current_admin_user`: 依赖于 `get_current_user`，并额外检查 `user.role == 'admin'`。
* **`schemas.py`**:
    * 定义认证相关的 Pydantic 模型，如 `WxLoginRequest`, `TokenResponse`, `UserInfoResponse`。
* **`tasks.py`**:
    * (示例) 定义了使用 `funboost` 的后台任务，如 `send_email_task`。

## 依赖的数据模型

* `User` (主要创建和查询的对象)
* `SocialAccount` (用于关联 `User` 和 `openid`)