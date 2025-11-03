# src/modules/schedule/schemas.py

from enum import Enum
from pydantic import BaseModel, ConfigDict, Field
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


class LocationDay(BaseModel):
    date: date
    weekday: str
    has_any_shift: bool


class ServiceOption(BaseModel):
    uid: str
    name: str
    technician_duration: int
    room_duration: int
    buffer_time: int
    is_active: bool = True


class TechnicianOption(BaseModel):
    uid: str
    nickname: Optional[str] = None
    phone: Optional[str] = None
    is_available: bool = True
    disabled_reason: Optional[str] = None


class TechnicianShiftCreateItem(BaseModel):
    date: date
    period: ShiftPeriod
    location_uid: str


class TechnicianShiftCreateRequest(BaseModel):
    items: List[TechnicianShiftCreateItem]


class ScheduleCartHold(BaseModel):
    start_time: datetime
    end_time: datetime
    technician_uid: Optional[str] = None
    resource_uid: Optional[str] = None


class TechnicianFilterRequest(BaseModel):
    location_uid: str
    service_uids: List[str]


class PackageAvailabilityRequest(BaseModel):
    location_uid: str
    target_date: date
    ordered_service_uids: List[str]
    preferred_technician_uid: Optional[str] = None
    holds: List[ScheduleCartHold] = Field(default_factory=list)


class PackageSlotTechnician(BaseModel):
    uid: str
    nickname: Optional[str] = None
    phone: Optional[str] = None


class PackageSlotResource(BaseModel):
    uid: str
    name: Optional[str] = None


class PackageAvailabilitySlot(BaseModel):
    start_time: datetime
    technician: Optional[PackageSlotTechnician] = None
    resource: Optional[PackageSlotResource] = None


class PackageAvailabilityResponse(BaseModel):
    available_slots: List[PackageAvailabilitySlot]
