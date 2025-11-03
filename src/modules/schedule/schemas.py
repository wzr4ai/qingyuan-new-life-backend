# src/modules/schedule/schemas.py

from enum import Enum
from pydantic import BaseModel, ConfigDict
from typing import List, Dict, Optional
from datetime import date, datetime

class AvailabilityResponse(BaseModel):
    """
    用于 '返回可用时间' 接口
    """
    # 我们返回一个字典，键是HH:MM格式的开始时间，值是分钟数
    # 这样前端可以更灵活地展示（例如 "9:00 (持续60分钟)")
    # 但为简单起见，V1 我们先只返回一个时间列表
    available_slots: List[str] # V1: ["08:30", "09:00"]

class AppointmentCreate(BaseModel):
    """
    用于 '创建预约' 接口 (客户提交)
    """
    service_uid: str
    location_uid: str
    # 客户将提交一个带时区的完整 ISO 格式时间字符串
    # 例如: "2025-10-24T09:00:00+08:00"
    start_time: datetime 

class AppointmentPublic(BaseModel):
    """
    用于 '返回预约' 接口 (创建成功或查询历史)
    """
    uid: str
    status: str
    start_time: datetime
    
    # 嵌套显示预约的服务和地点信息
    # (我们需要从 admin.schemas 导入 ServicePublic 和 LocationPublic)
    # (为了简化，我们先只返回 UID)
    service_uid: str
    location_uid: str
    
    # 告诉 Pydantic 如何从 ORM 模型中读取这些字段
    # (我们将使用 SQLAlchemy 的 hybrid_property 或在 service 层手动构造)
    # (V1 简化：我们将在 service 层查询 service_uid 和 location_uid)
    
    model_config = ConfigDict(from_attributes=True)

    # 简单的实现，只返回 UID
    @classmethod
    def from_orm_simple(cls, appt):
        return cls(
            uid=appt.uid,
            status=appt.status,
            start_time=appt.start_time,
            service_uid=appt.service_id,
            location_uid=appt.location_id
        )


class ShiftPeriod(str, Enum):
    morning = "morning"
    afternoon = "afternoon"


class TechnicianShiftSlot(BaseModel):
    is_active: bool
    shift_uid: Optional[str] = None
    location_uid: Optional[str] = None
    location_name: Optional[str] = None
    locked_by_admin: bool = False
    has_bookings: bool = False


class TechnicianShiftDay(BaseModel):
    date: date
    weekday: str
    morning: TechnicianShiftSlot
    afternoon: TechnicianShiftSlot


class LocationOption(BaseModel):
    uid: str
    name: str


class TechnicianShiftCalendar(BaseModel):
    generated_at: datetime
    days: List[TechnicianShiftDay]
    locations: List[LocationOption]


class TechnicianShiftCreateItem(BaseModel):
    date: date
    period: ShiftPeriod
    location_uid: str


class TechnicianShiftCreateRequest(BaseModel):
    items: List[TechnicianShiftCreateItem]
