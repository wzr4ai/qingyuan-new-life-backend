# 青元新生 预约系统 API 文档 (V6)

**Base URL:** `http://<your_server_address>:8002`

**认证 (Authentication):**
* **客户接口** (Customer Endpoints)：需要一个标准的 Bearer Token。
* **管理接口** (Admin Endpoints)：需要一个 `role='admin'` 用户的 Bearer Token。
* 所有 Token 都通过 `POST /auth/wx-login` 接口获取，并应在后续请求的 `Authorization` 头中发送：`Authorization: Bearer <your_token>`。

---

### 模块一：认证 (`/auth`)

#### 1. `POST /auth/wx-login`
* **概要:** 微信小程序登录或注册
* **权限:** Public
* **描述:**
    接收前端 `wx.login()` 获取的临时 `code`。后端将用此 `code` 换取 `openid`。
    1.  如果 `SocialAccount` 已存在，则登录该用户。
    2.  如果 `SocialAccount` 不存在，将自动创建一个新的 `User` (昵称默认为 "微信用户") 和 `SocialAccount` 记录。
    3.  返回一个用于后续所有请求的 JWT `access_token`。
* **Request Body:**
    ```json
    {
      "code": "string" 
    }
    ```
* **Response (200 OK):**
    ```json
    {
      "access_token": "string (JWT)",
      "token_type": "bearer"
    }
    ```

---

### 模块二：管理后台 (`/admin`)

**注意：** 此模块下的所有接口都需要**管理员 (Admin)** 权限。

#### 2.1 地点管理 (Locations)

* **`POST /admin/locations`**
    * **概要:** (Admin) 创建新地点
    * **Request Body:**
        ```json
        {
          "name": "string (required)",
          "address": "string (optional)"
        }
        ```
    * **Response (201 Created):** `LocationPublic` 对象

* **`GET /admin/locations`**
    * **概要:** (Admin) 获取所有地点列表
    * **Response (200 OK):** `List[LocationPublic]`

* **`PUT /admin/locations/{location_uid}`**
    * **概要:** (Admin) 更新指定地点
    * **Request Body:** (所有字段可选)
        ```json
        {
          "name": "string",
          "address": "string"
        }
        ```
    * **Response (200 OK):** `LocationPublic` 对象

#### 2.2 服务项目管理 (Services)

* **`POST /admin/services`**
    * **概要:** (Admin) 创建新服务项目 (推拿、针灸等)
    * **Request Body:**
        ```json
        {
          "name": "string (required)",
          "technician_operation_duration": "integer (分钟, required)",
          "room_operation_duration": "integer (分钟, required)",
          "buffer_time": "integer (分钟, default: 15)"
        }
        ```
    * **Response (201 Created):** `ServicePublic` 对象

* **`GET /admin/services`**
    * **概要:** (Admin) 获取所有服务项目列表
    * **Response (200 OK):** `List[ServicePublic]`

* **`PUT /admin/services/{service_uid}`**
    * **概要:** (Admin) 更新指定服务项目
    * **Request Body:** (所有字段可选)
    * **Response (200 OK):** `ServicePublic` 对象

#### 2.3 物理资源管理 (Resources - 床位/房间)

* **`POST /admin/resources`**
    * **概要:** (Admin) 创建新物理资源 (床位/房间)
    * **Request Body:**
        ```json
        {
          "name": "string (required)",
          "location_uid": "string (required, 地点UID)"
        }
        ```
    * **Response (201 Created):** `ResourcePublic` 对象 (将嵌套所属的 `location` 信息)

* **`GET /admin/locations/{location_uid}/resources`**
    * **概要:** (Admin) 获取指定地点的所有物理资源
    * **Response (200 OK):** `List[ResourcePublic]`

* **`PUT /admin/resources/{resource_uid}`**
    * **概要:** (Admin) 更新物理资源 (名称或所属地点)
    * **Request Body:** (所有字段可选)
        ```json
        {
          "name": "string",
          "location_uid": "string (新的地点UID)"
        }
        ```
    * **Response (200 OK):** `ResourcePublic` 对象

#### 2.4 技师技能管理 (Technicians)

* **`GET /admin/technicians`**
    * **概要:** (Admin) 获取所有技师及其技能列表
    * **描述:** 返回所有 `role='technician'` 的用户，并嵌套显示他们掌握的 `services` (技能) 列表。
    * **Response (200 OK):** `List[TechnicianPublic]`

* **`POST /admin/technicians/{user_uid}/services`**
    * **概要:** (Admin) 为技师分配一项新技能(服务)
    * **Request Body:**
        ```json
        {
          "service_uid": "string (required, 服务UID)"
        }
        ```
    * **Response (200 OK):** `TechnicianPublic` 对象 (更新后的技师信息)

* **`DELETE /admin/technicians/{user_uid}/services/{service_uid}`**
    * **概要:** (Admin) 移除技师的某项技能
    * **Response (200 OK):** `TechnicianPublic` 对象 (更新后的技师信息)

#### 2.5 排班管理 (Shifts - V6)

* **`POST /admin/shifts`**
    * **概要:** (Admin) 创建新排班
    * **描述:** 为技师在指定地点和时段创建排班。**包含技师排班防重叠检查**。
    * **Request Body:**
        ```json
        {
          "technician_uid": "string (required, 技师UID)",
          "location_uid": "string (required, 地点UID)",
          "start_time": "string (ISO Datetime, e.g., 2025-10-27T08:30:00+08:00)",
          "end_time": "string (ISO Datetime, e.g., 2025-10-27T12:00:00+08:00)"
        }
        ```
    * **Response (201 Created):** `ShiftPublic` 对象 (嵌套 `technician` 和 `location` 信息)

* **`GET /admin/shifts`**
    * **概要:** (Admin) 查询排班
    * **Query Parameters (全部可选):**
        * `location_uid: string`
        * `technician_uid: string`
        * `start_date: string (YYYY-MM-DD)`
        * `end_date: string (YYYY-MM-DD)`
    * **Response (200 OK):** `List[ShiftPublic]`

* **`DELETE /admin/shifts/{shift_uid}`**
    * **概要:** (Admin) 删除排班
    * **Response (204 No Content):** (无返回体)

---

### 模块三：预约调度 (客户端) (`/api/v1/schedule`)

**注意：** 此模块下的所有接口都需要**标准客户 (Customer)** 权限（即已登录）。

#### 3.1 `GET /api/v1/schedule/availability`
* **概要:** (Customer) 查询可用预约时间槽 (核心)
* **权限:** Customer
* **描述:**
    系统的核心调度接口。基于 V6 架构（技师排班、技能、房间资源、现有预约）实时计算出所选日期所有可用的时间槽。
* **Query Parameters (全部必填):**
    * `location_uid: string` (客户选择的地点UID)
    * `service_uid: string` (客户选择的服务UID)
    * `target_date: string (YYYY-MM-DD)` (客户选择的日期)
* **Response (200 OK):**
    ```json
    {
      "available_slots": [
        "08:30",
        "08:40",
        "09:10"
      ]
    }
    ```

#### 3.2 `POST /api/v1/schedule/appointments`
* **概要:** (Customer) 创建新预约
* **权限:** Customer
* **描述:**
    客户提交预约。服务器将在一个数据库事务中**重新验证**技师和房间的可用性（防止并发冲突）。
* **Request Body:**
    ```json
    {
      "service_uid": "string (required, 服务UID)",
      "location_uid": "string (required, 地点UID)",
      "start_time": "string (ISO Datetime, e.g., 2025-10-27T09:10:00+08:00)"
    }
    ```
* **Response (201 Created):**
    ```json
    {
      "uid": "string (新预约的UID)",
      "status": "confirmed",
      "start_time": "2025-10-27T09:10:00+08:00",
      "service_uid": "string (服务UID)",
      "location_uid": "string (地点UID)"
    }
    ```
* **Error Response (409 Conflict):**
    如果该时间槽在客户提交时已被他人抢占，将返回 409 错误，并附带 `detail` 信息（例如 "该时间段的技师已被预约，请选择其他时间"）。

---

### 模块四：辅助接口 (待开发)

正如我们所讨论的，为了让前端能正常工作，我们还需要开发以下几个**辅助性接口**。

* `GET /api/v1/locations` (Public/Customer, 用于客户浏览地点列表)
* `GET /api/v1/services` (Public/Customer, 用于客户浏览服务列表)
* `GET /api/v1/appointments/mine` (Customer, 查询“我未来的预约”)
* `GET /api/v1/appointments/history` (Customer, 查询“我历史的预约”)
* `GET /auth/me` (Customer, 获取自己的个人资料，如昵称、手机号)