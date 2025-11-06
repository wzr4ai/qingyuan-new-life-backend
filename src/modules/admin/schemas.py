# src/modules/admin/schemas.py

from pydantic import BaseModel, ConfigDict, Field, AliasChoices
from typing import Optional, List, Literal
from enum import Enum as PyEnum
from datetime import datetime, date

from src.modules.schedule.schemas import ShiftPeriod

# --- Location Schemas ---

class LocationBase(BaseModel):
    """
    地点的基础模型，包含所有 API 都需要的基础字段
    """
    name: str
    address: Optional[str] = None

class LocationCreate(LocationBase):
    """
    用于 '创建地点' 接口的 Pydantic 模型
    """
    pass # 目前和 LocationBase 相同

class LocationUpdate(LocationBase):
    """
    用于 '更新地点' 接口的 Pydantic 模型
    (未来可能有部分更新，暂且设为与 Base 相同)
    """
    name: Optional[str] = None # 在更新时，所有字段都应是可选的
    address: Optional[str] = None

class LocationPublic(LocationBase):
    """
    用于 '返回地点' 接口的 Pydantic 模型 (例如 GET 请求)
    """
    uid: str
    name: str
    address: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class ServiceBase(BaseModel):
    """
    服务项目的基础模型
    """
    name: str
    technician_operation_duration: int
    room_operation_duration: int
    buffer_time: int = 15 # 根据我们 V2 设计，默认 15 分钟

class ServiceCreate(ServiceBase):
    """
    用于 '创建服务' 接口
    """
    pass

class ServiceUpdate(BaseModel):
    """
    用于 '更新服务' 接口 (所有字段可选)
    """
    name: Optional[str] = None
    technician_operation_duration: Optional[int] = None
    room_operation_duration: Optional[int] = None
    buffer_time: Optional[int] = None

class ServicePublic(ServiceBase):
    """
    用于 '返回服务' 接口
    """
    uid: str
    name: str
    technician_operation_duration: int
    room_operation_duration: int
    buffer_time: int
    model_config = ConfigDict(from_attributes=True)
    
class ResourceType(str, PyEnum):
    technician = "technician"
    room = "room"

class ResourceBase(BaseModel):
    """
    物理资源的基础模型 (床位/房间)
    """
    name: str
    type: ResourceType = ResourceType.room

class ResourceCreate(ResourceBase):
    """
    用于 '创建资源' 接口
    """
    location_uid: str # 必须指定这个资源属于哪个地点
    service_uids: List[str] = []

class ResourceUpdate(BaseModel):
    """
    用于 '更新资源' 接口
    """
    name: Optional[str] = None
    location_uid: Optional[str] = None # 允许移动资源到另一个地点
    type: Optional[ResourceType] = None
    service_uids: Optional[List[str]] = None

class ResourcePublic(ResourceBase):
    """
    用于 '返回资源' 接口 (V4: 只代表物理资源)
    """
    uid: str
    name: str
    location: LocationPublic 
    services: List[ServicePublic] = []
    model_config = ConfigDict(from_attributes=True)

class UserBaseInfo(BaseModel):
    """
    用于嵌套在其他模型中的最基本的用户信息
    """
    uid: str
    nickname: Optional[str] = None
    phone: Optional[str] = None
    role: str
    model_config = ConfigDict(from_attributes=True)

class TechnicianPublic(UserBaseInfo):
    """
    用于 '返回技师' 接口 (包含其技能列表)
    """
    # 使用 validation_alias 以兼容 SQLAlchemy 上的 `service` 关系名称
    services: List[ServicePublic] = Field(
        default_factory=list,
        validation_alias=AliasChoices('service', 'services')
    )
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class TechnicianSkillAssign(BaseModel):
    """
    用于 '为技师分配技能' 接口
    """
    service_uid: str # 传入要分配的技能(服务)的 UID

class UserRoleUpdate(BaseModel):
    """
    用于更新用户角色的模型
    """
    target_role: Literal['technician', 'admin']

class ShiftCreate(BaseModel):
    """
    用于 '创建排班' 接口 (基于班次的排班请求)
    """
    technician_uid: str
    location_uid: str
    date: date
    period: ShiftPeriod

    from pydantic import field_validator, model_validator

    @field_validator("date")
    @classmethod
    def ensure_future_date(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("排班日期不能早于今天")
        return value

    @model_validator(mode="after")
    def normalize_period(self) -> "ShiftCreate":
        # 兼容字符串传入
        if isinstance(self.period, str):
            try:
                self.period = ShiftPeriod(self.period)
            except ValueError as exc:
                raise ValueError("无效的班次时段") from exc
        return self

class ShiftPublic(BaseModel):
    """
    用于 '返回排班' 接口
    """
    uid: str
    start_time: datetime
    end_time: datetime
    period: Optional[str] = None
    locked_by_admin: bool = False
    is_cancelled: bool = False
    cancelled_at: Optional[datetime] = None
    created_by_user_id: Optional[str] = None
    cancelled_by_user_id: Optional[str] = None
    
    # 嵌套显示该排班所属的技师和地点
    technician: UserBaseInfo 
    location: LocationPublic 
    
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TechnicianPolicyBase(BaseModel):
    technician_uid: str
    location_uid: Optional[str] = None
    max_daily_online: Optional[int] = Field(default=None, ge=0)
    max_morning_online: Optional[int] = Field(default=None, ge=0)
    max_afternoon_online: Optional[int] = Field(default=None, ge=0)
    auto_assign_priority: int = Field(default=50)
    allow_public_booking: bool = True


class TechnicianPolicyCreate(TechnicianPolicyBase):
    pass


class TechnicianPolicyUpdate(BaseModel):
    location_uid: Optional[str] = None
    max_daily_online: Optional[int] = Field(default=None, ge=0)
    max_morning_online: Optional[int] = Field(default=None, ge=0)
    max_afternoon_online: Optional[int] = Field(default=None, ge=0)
    auto_assign_priority: Optional[int] = None
    allow_public_booking: Optional[bool] = None


class TechnicianPolicyPublic(TechnicianPolicyBase):
    uid: str
    technician: Optional[UserBaseInfo] = None
    location: Optional[LocationPublic] = None
    model_config = ConfigDict(from_attributes=True)


class TechnicianServicePricingBase(BaseModel):
    service_uid: str
    technician_uid: Optional[str] = None
    location_uid: Optional[str] = None
    price: int = Field(ge=0)
    is_active: bool = True


class TechnicianServicePricingCreate(TechnicianServicePricingBase):
    pass


class TechnicianServicePricingUpdate(BaseModel):
    service_uid: Optional[str] = None
    technician_uid: Optional[str] = None
    location_uid: Optional[str] = None
    price: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class TechnicianServicePricingPublic(TechnicianServicePricingBase):
    uid: str
    service: Optional[ServicePublic] = None
    technician: Optional[UserBaseInfo] = None
    location: Optional[LocationPublic] = None
    model_config = ConfigDict(from_attributes=True)
