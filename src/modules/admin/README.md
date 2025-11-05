# 管理后台模块 (admin)

## 模块职责

此模块定义了所有**仅限管理员**使用的 API 路由，用于管理系统的核心资源 (CRUD)。

所有路由都通过 `src.modules.auth.security.get_current_admin_user` 依赖项进行保护，确保只有 `role='admin'` 的用户才能访问。

## 核心文件

* **`router.py`**:
    * 定义 `/admin/*` API 路由。
    * 处理所有与地点 (`Location`)、服务 (`Service`)、物理资源 (`Resource`)、技师技能 (`Technician`) 和排班 (`Shift`) 相关的 CRUD 操作。
* **`schemas.py`**:
    * 定义此模块中所有 API 路由所需的 Pydantic 模型 (请求体和响应体)。
    * 例如 `LocationCreate`, `ServiceUpdate`, `TechnicianPublic`, `ShiftCreate` 等。

## 依赖的数据模型

* `Location`, `Service`, `Resource`, `Shift` (主要管理对象)
* `User` (用于查询技师、分配技能、更新角色)
* `Appointment` (用于在删除资源前进行检查)