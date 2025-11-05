# 预约调度模块 (schedule)

## 模块职责

此模块是**客户**面向的核心功能，处理所有与**查询可用时间**和**创建预约**相关的复杂调度逻辑。

## 核心文件

* **`router.py`**:
    * `GET /schedule/availability`: 客户查询可用时间槽的 API。
    * `POST /schedule/appointments`: 客户提交新预约的 API。
    * `GET /schedule/my-shifts`, `POST /schedule/my-shifts`: 技师查看和提报自己排班的 API。
    * (辅助接口): `GET /locations`, `GET /location-days`, `GET /location-services` 等，用于支持前端预约流程。
* **`service.py`**:
    * `get_available_slots`: **(核心算法)** 系统的主要调度逻辑。它根据地点、服务和日期，结合技师排班、技师技能、资源(房间)可用性以及现有预约，计算出所有可用的时间槽。
    * `create_appointment`: **(核心事务)** 创建预约的逻辑。它在一个数据库事务中锁定资源，防止并发冲突 (竞态条件)，并创建 `Appointment`, `AppointmentTechnicianLink`, 和 `AppointmentResourceLink` 记录。
    * (排班相关): `get_technician_shift_calendar`, `create_shifts_for_technician` 等。
* **`schemas.py`**:
    * 定义客户预约流程所需的 Pydantic 模型，如 `AvailabilityResponse`, `AppointmentCreate`, `TechnicianShiftCalendar`。
* **`cache.py`**:
    * (示例) 提供了连接 Redis 和进行基本 `get/set/clear` 缓存的辅助函数。

## 依赖的数据模型

* `Appointment`, `AppointmentTechnicianLink`, `AppointmentResourceLink` (主要创建的对象)
* `Shift`, `User`, `Service`, `Resource` (调度算法的核心查询对象)