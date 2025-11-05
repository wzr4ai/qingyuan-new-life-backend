# 共享模块 (shared)

该模块包含在整个应用程序中重用的跨领域代码，主要分为数据模型和共享依赖项。

## 模块职责

* **`models/`**: 定义所有核心的 SQLAlchemy 数据库模型 (即数据库表结构)。
* **`deps/`**: (当前) 定义 FastAPI 依赖项，用于获取 `arq` 连接池。

## 核心文件

* **`models/__init__.py`**:
    * 导入所有模型类，并使它们可被 Alembic 自动发现。
    * 定义 `Base` 类，所有模型都继承自它。

* **`models/user_models.py`**:
    * `User`: 核心用户表 (客户, 技师, 管理员)。
    * `SocialAccount`: 社交登录表 (如微信 OpenID)。
    * `technician_service_link_table`: 技师与服务的多对多关联表。

* **`models/resource_models.py`**:
    * `Location`: 工作地点 (门店)。
    * `Resource`: 物理资源 (如房间、床位)。
    * `Service`: 服务项目 (如推拿、针灸)。
    * `resource_service_link_table`: 物理资源与服务的'多对多'关联表。

* **`models/schedule_models.py`**:
    * `Shift`: 技师的排班表。

* **`models/appointment_models.py`**:
    * `Appointment`: 预约的主记录表。
    * `AppointmentTechnicianLink`: 预约与技师的时间占用关联。
    * `AppointmentResourceLink`: 预约与物理资源的时间占用关联。

* **`deps/arq.py`**:
    * 包含 `get_arq_pool` 依赖项 (如果未来使用 `arq` 作为后台任务队列)。