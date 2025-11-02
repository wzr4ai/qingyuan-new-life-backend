# src/modules/admin/schemas.py

from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime

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
    
class ResourceBase(BaseModel):
    """
    物理资源的基础模型 (床位/房间)
    """
    name: str

class ResourceCreate(ResourceBase):
    """
    用于 '创建资源' 接口
    """
    location_uid: str # 必须指定这个资源属于哪个地点

class ResourceUpdate(BaseModel):
    """
    用于 '更新资源' 接口
    """
    name: Optional[str] = None
    location_uid: Optional[str] = None # 允许移动资源到另一个地点

class ResourcePublic(ResourceBase):
    """
    用于 '返回资源' 接口 (V4: 只代表物理资源)
    """
    uid: str
    name: str
    location: LocationPublic 
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
    # 嵌套 ServicePublic 列表，展示该技师的所有技能
    services: List[ServicePublic] = [] 
    model_config = ConfigDict(from_attributes=True)

class TechnicianSkillAssign(BaseModel):
    """
    用于 '为技师分配技能' 接口
    """
    service_uid: str # 传入要分配的技能(服务)的 UID

class ShiftCreate(BaseModel):
    """
    用于 '创建排班' 接口
    """
    technician_uid: str
    location_uid: str
    start_time: datetime # 例如: "2025-10-27T08:30:00+08:00"
    end_time: datetime   # 例如: "2025-10-27T12:00:00+08:00"

    # Pydantic v2 验证器: 确保结束时间晚于开始时间
    from pydantic import model_validator
    @model_validator(mode='after')
    def check_times(self) -> 'ShiftCreate':
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValueError("排班结束时间 (end_time) 必须晚于开始时间 (start_time)")
        return self

class ShiftPublic(BaseModel):
    """
    用于 '返回排班' 接口
    """
    uid: str
    start_time: datetime
    end_time: datetime
    
    # 嵌套显示该排班所属的技师和地点
    technician: UserBaseInfo 
    location: LocationPublic 
    
    model_config = ConfigDict(from_attributes=True)