# src/modules/admin/router.py

from fastapi import APIRouter, Depends, HTTPException, Response, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_, or_, delete
from typing import List, Optional
from datetime import date, datetime, time

from src.core.database import get_db
from src.shared.models.resource_models import (
    Location,
    Service,
    Resource,
    resource_service_link_table,
)
from src.shared.models.schedule_models import Shift
from sqlalchemy.orm import joinedload
from src.modules.auth.security import get_current_admin_user # 2. 导入管理员依赖
from src.shared.models.user_models import User, technician_service_link_table # 3. 导入 User (用于类型注解)
from src.shared.models.appointment_models import Appointment, AppointmentResourceLink
from . import schemas # 4. 导入我们刚创建的 schemas
from src.modules.schedule import service as schedule_service
from src.modules.schedule import schemas as schedule_schemas

# 我们创建一个专门用于管理后台的 'admin' 路由
# 它不带 prefix，我们将在 main.py 中统一添加
router = APIRouter(
    responses={
        404: {"description": "Not found"},
        403: {"description": "Operation not permitted"},
    }
)

# --- Locations CRUD ---

@router.post(
    "/locations", 
    response_model=schemas.LocationPublic, 
    status_code=status.HTTP_201_CREATED,
    summary="创建新地点"
)
async def create_location(
    location_data: schemas.LocationCreate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 关键：保护此接口
):
    """
    (Admin Only) 创建一个新的工作地点。
    """
    # 检查地点名称是否已存在 (可选，但推荐)
    query = select(Location).where(Location.name == location_data.name)
    existing_location = (await db.execute(query)).scalars().first()
    if existing_location:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="已存在同名地点"
        )
        
    new_location = Location(
        name=location_data.name,
        address=location_data.address
    )
    db.add(new_location)
    await db.commit()
    await db.refresh(new_location)
    
    return new_location

@router.get(
    "/locations", 
    response_model=List[schemas.LocationPublic],
    summary="获取所有地点列表"
)
async def get_all_locations(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 关键：保护此接口
):
    """
    (Admin Only) 获取所有工作地点的列表。
    
    (注意: 客户查看地点列表将是另一个 *公开* 接口，这个是管理后台用的)
    """
    query = select(Location).order_by(Location.name)
    result = await db.execute(query)
    locations = result.scalars().all()
    
    return locations

@router.put(
    "/locations/{location_uid}", 
    response_model=schemas.LocationPublic,
    summary="更新指定地点"
)
async def update_location(
    location_uid: str,
    location_data: schemas.LocationUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 关键：保护此接口
):
    """
    (Admin Only) 更新一个已存在地点的名称或地址。
    """
    query = select(Location).where(Location.uid == location_uid)
    result = await db.execute(query)
    db_location = result.scalars().first()
    
    if not db_location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="地点不存在"
        )
    
    # 使用 Pydantic 的 .model_dump() 来安全地更新字段
    # exclude_unset=True 意味着只更新客户端传入的字段
    update_data = location_data.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(db_location, key, value)
        
    db.add(db_location)
    await db.commit()
    await db.refresh(db_location)
    
    return db_location

@router.delete(
    "/locations/{location_uid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除指定地点"
)
async def delete_location(
    location_uid: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    (Admin Only) 删除一个地点。仅当地点未关联资源、排班或预约时允许删除。
    """
    query = select(Location).where(Location.uid == location_uid)
    result = await db.execute(query)
    db_location = result.scalars().first()

    if not db_location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="地点不存在"
        )

    has_resources = (await db.execute(
        select(Resource.uid).where(Resource.location_id == location_uid).limit(1)
    )).scalars().first()
    if has_resources:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先删除该地点下的资源后再尝试删除地点"
        )

    has_shifts = (await db.execute(
        select(Shift.uid).where(Shift.location_id == location_uid).limit(1)
    )).scalars().first()
    if has_shifts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该地点存在排班记录，无法删除"
        )

    has_appointments = (await db.execute(
        select(Appointment.uid).where(Appointment.location_id == location_uid).limit(1)
    )).scalars().first()
    if has_appointments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该地点存在预约记录，无法删除"
        )

    await db.delete(db_location)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post(
    "/services", 
    response_model=schemas.ServicePublic, 
    status_code=status.HTTP_201_CREATED,
    summary="创建新服务项目"
)
async def create_service(
    service_data: schemas.ServiceCreate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 保护接口
):
    """
    (Admin Only) 创建一个新的服务项目 (如 推拿, 针灸)。
    """
    # 检查名称是否唯一
    query = select(Service).where(Service.name == service_data.name)
    existing_service = (await db.execute(query)).scalars().first()
    if existing_service:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="已存在同名服务项目"
        )
        
    new_service = Service(
        name=service_data.name,
        technician_operation_duration=service_data.technician_operation_duration,
        room_operation_duration=service_data.room_operation_duration,
        buffer_time=service_data.buffer_time
    )
    db.add(new_service)
    await db.commit()
    await db.refresh(new_service)
    
    return new_service

@router.get(
    "/services", 
    response_model=List[schemas.ServicePublic],
    summary="获取所有服务项目列表"
)
async def get_all_services(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 保护接口
):
    """
    (Admin Only) 获取所有服务项目的列表。
    """
    query = select(Service).order_by(Service.name)
    result = await db.execute(query)
    services = result.scalars().all()
    
    return services

@router.put(
    "/services/{service_uid}", 
    response_model=schemas.ServicePublic,
    summary="更新指定服务项目"
)
async def update_service(
    service_uid: str,
    service_data: schemas.ServiceUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 保护接口
):
    """
    (Admin Only) 更新一个服务项目的时长或名称。
    """
    query = select(Service).where(Service.uid == service_uid)
    result = await db.execute(query)
    db_service = result.scalars().first()
    
    if not db_service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="服务项目不存在"
        )
    
    update_data = service_data.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(db_service, key, value)
        
    db.add(db_service)
    await db.commit()
    await db.refresh(db_service)
    
    return db_service

@router.delete(
    "/services/{service_uid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除指定服务项目"
)
async def delete_service(
    service_uid: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    (Admin Only) 删除一个服务项目。若仍存在预约或技师关联则拒绝删除。
    """
    query = select(Service).where(Service.uid == service_uid)
    result = await db.execute(query)
    db_service = result.scalars().first()

    if not db_service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="服务项目不存在"
        )

    has_appointments = (await db.execute(
        select(Appointment.uid).where(Appointment.service_id == service_uid).limit(1)
    )).scalars().first()
    if has_appointments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该服务已关联预约记录，无法删除"
        )

    has_resource_bindings = (await db.execute(
        select(resource_service_link_table.c.resource_id)
        .where(resource_service_link_table.c.service_id == service_uid)
        .limit(1)
    )).scalars().first()
    if has_resource_bindings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该服务仍绑定在资源上，无法删除"
        )

    await db.execute(
        delete(technician_service_link_table).where(
            technician_service_link_table.c.service_id == service_uid
        )
    )

    db_service.resources = []
    await db.delete(db_service)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post(
    "/resources",
    response_model=schemas.ResourcePublic,
    status_code=status.HTTP_201_CREATED,
    summary="创建新物理资源(床位/房间)"
)
async def create_resource(
    resource_data: schemas.ResourceCreate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 保护接口
):
    """
    (Admin Only) 创建一个新的物理资源 (如 1号床)，并将其分配给一个地点。
    """
    # 1. 验证 Location 是否存在
    db_location = (await db.execute(
        select(Location).where(Location.uid == resource_data.location_uid)
    )).scalars().first()
    
    if not db_location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"UID 为 {resource_data.location_uid} 的地点不存在"
        )
        
    # 2. 创建 Resource 并直接关联 Location 对象
    incoming_type = resource_data.type
    if isinstance(incoming_type, schemas.ResourceType):
        resolved_type = incoming_type.value
    else:
        resolved_type = str(incoming_type or schemas.ResourceType.room.value)

    # 2. 解析资源类型
    new_resource = Resource(
        name=resource_data.name,
        type=resolved_type,
        location=db_location  # <-- 直接关联对象
    )
    # 3. 绑定服务能力
    service_uids = list(dict.fromkeys(resource_data.service_uids or []))
    if not service_uids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请至少选择一个可提供的服务"
        )
    service_query = select(Service).where(Service.uid.in_(service_uids))
    service_result = await db.execute(service_query)
    services = service_result.scalars().all()
    found_service_uids = {service.uid for service in services}
    missing = set(service_uids) - found_service_uids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"以下服务不存在: {', '.join(sorted(missing))}"
        )
    new_resource.services = services

    db.add(new_resource)
    await db.commit()
    # 确保关联关系在返回前已加载，避免 Lazy Load 触发 MissingGreenlet
    await db.refresh(new_resource, attribute_names=["location", "services"])
    
    # 3. 返回。因为 location 关系是在 session 中被赋的，
    # Pydantic (with from_attributes=True) 可以正确地嵌套 LocationPublic
    return new_resource

@router.get(
    "/locations/{location_uid}/resources",
    response_model=List[schemas.ResourcePublic],
    summary="获取指定地点的所有物理资源"
)
async def get_resources_for_location(
    location_uid: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 保护接口
):
    """
    (Admin Only) 获取特定地点下的所有物理资源 (床位/房间) 列表。
    """
    query = (
        select(Resource)
        .where(Resource.location_id == location_uid)
        # 关键: 必须 Eager Load 'location' 关系
        # 否则 ResourcePublic schema 会因为缺少 location 数据而失败
        .options(joinedload(Resource.location), joinedload(Resource.services))
        .order_by(Resource.name)
    )
    result = await db.execute(query)
    resources = result.unique().scalars().all()
    
    return resources

@router.put(
    "/resources/{resource_uid}",
    response_model=schemas.ResourcePublic,
    summary="更新物理资源(床位/房间)"
)
async def update_resource(
    resource_uid: str,
    resource_data: schemas.ResourceUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 保护接口
):
    """
    (Admin Only) 更新一个物理资源的名称或其所属的地点。
    """
    query = (
        select(Resource)
        .where(Resource.uid == resource_uid)
        .options(joinedload(Resource.location), joinedload(Resource.services)) # 预加载以便返回
    )
    result = await db.execute(query)
    db_resource = result.unique().scalars().first()

    if not db_resource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="资源不存在"
        )
    
    update_data = resource_data.model_dump(exclude_unset=True)
    service_uids_update = update_data.pop("service_uids", None)
    
    # 检查是否需要更新 location_uid
    if "location_uid" in update_data:
        new_location_uid = update_data.pop("location_uid") # 从 update_data 中移除
        db_location = (await db.execute(
            select(Location).where(Location.uid == new_location_uid)
        )).scalars().first()
        
        if not db_location:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"UID 为 {new_location_uid} 的新地点不存在"
            )
        db_resource.location = db_location # 更新 location 关系
    
    # 更新其他字段 (例如 name)
    for key, value in update_data.items():
        if key == "type":
            if isinstance(value, schemas.ResourceType):
                setattr(db_resource, key, value.value)
            else:
                setattr(db_resource, key, str(value))
        else:
            setattr(db_resource, key, value)

    if service_uids_update is not None:
        service_uids_unique = list(dict.fromkeys(service_uids_update))
        if not service_uids_unique:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请至少选择一个可提供的服务"
            )
        services_query = select(Service).where(Service.uid.in_(service_uids_unique))
        services_result = await db.execute(services_query)
        services = services_result.scalars().all()
        found_service_uids = {service.uid for service in services}
        missing = set(service_uids_unique) - found_service_uids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"以下服务不存在: {', '.join(sorted(missing))}"
            )
        db_resource.services = services
        
    db.add(db_resource)
    await db.commit()
    await db.refresh(db_resource, ["location", "services"]) # 确保关联关系被刷新
    
    return db_resource

@router.delete(
    "/resources/{resource_uid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除物理资源(床位/房间)"
)
async def delete_resource(
    resource_uid: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    (Admin Only) 删除一个物理资源。如果资源仍与预约关联，则拒绝删除。
    """
    query = (
        select(Resource)
        .where(Resource.uid == resource_uid)
        .options(joinedload(Resource.location), joinedload(Resource.services))
    )
    result = await db.execute(query)
    db_resource = result.unique().scalars().first()

    if not db_resource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="资源不存在"
        )

    has_links = (await db.execute(
        select(AppointmentResourceLink.uid).where(
            AppointmentResourceLink.resource_id == resource_uid
        ).limit(1)
    )).scalars().first()
    if has_links:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该资源仍被预约记录占用，无法删除"
        )

    db_resource.services = []
    await db.delete(db_resource)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get(
    "/customers",
    response_model=List[schemas.UserBaseInfo],
    summary="获取所有客户列表"
)
async def get_all_customers(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    (Admin Only) 获取所有角色为 'customer' 的用户列表。
    """
    query = (
        select(User)
        .where(User.role == 'customer')
        .order_by(User.nickname)
    )
    result = await db.execute(query)
    customers = result.scalars().all()
    return customers

@router.put(
    "/customers/{user_uid}/role",
    response_model=schemas.UserBaseInfo,
    summary="将客户升级为技师或管理员"
)
async def update_customer_role(
    user_uid: str,
    role_data: schemas.UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    (Admin Only) 将客户身份更新为技师或管理员。
    """
    query = select(User).where(User.uid == user_uid)
    result = await db.execute(query)
    db_user = result.scalars().first()

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    if db_user.role != 'customer':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持从客户身份升级角色"
        )

    db_user.role = role_data.target_role
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    return db_user

@router.get(
    "/technicians",
    response_model=List[schemas.TechnicianPublic],
    summary="获取所有技师及其技能列表"
)
async def get_all_technicians(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 保护接口
):
    """
    (Admin Only) 获取所有角色为 'technician' 的用户列表，
    并包含他们所掌握的服务 (技能)。
    """
    query = (
        select(User)
        .where(User.role.in_(('technician', 'admin')))
        # 关键: 必须 Eager Load 'service' 多对多关系
        # 否则 TechnicianPublic schema 会因为缺少 services 数据而失败
        .options(joinedload(User.service))
        .order_by(User.nickname)
    )
    result = await db.execute(query)
    technicians = result.scalars().unique().all()
    
    return technicians

@router.post(
    "/technicians/{user_uid}/services",
    response_model=schemas.TechnicianPublic,
    summary="为技师分配一项新技能(服务)"
)
async def assign_service_to_technician(
    user_uid: str,
    skill_data: schemas.TechnicianSkillAssign,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 保护接口
):
    """
    (Admin Only) 为指定技师添加一项他能提供的服务。
    """
    # 1. 查找技师，并预加载他已有的技能
    query = (
        select(User)
        .where(User.uid == user_uid)
        .options(joinedload(User.service)) # 必须预加载才能 .append()
    )
    result = await db.execute(query)
    db_technician = result.unique().scalars().first()

    if not db_technician or db_technician.role not in ('technician', 'admin'):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该技师用户不存在"
        )
        
    # 2. 查找服务
    db_service = (await db.execute(
        select(Service).where(Service.uid == skill_data.service_uid)
    )).scalars().first()
    
    if not db_service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该服务项目不存在"
        )
        
    # 3. 检查是否已分配
    if db_service in db_technician.service:
        await db.refresh(db_technician, ["service"])
        return db_technician
        
    # 4. 分配技能 (SQLAlchemy 会自动处理多对多关联表)
    db_technician.service.append(db_service)
    
    db.add(db_technician)
    await db.commit()
    await db.refresh(db_technician, ["service"]) # 刷新关系
    
    return db_technician

@router.delete(
    "/technicians/{user_uid}/services/{service_uid}",
    response_model=schemas.TechnicianPublic,
    summary="移除技师的某项技能(服务)"
)
async def remove_service_from_technician(
    user_uid: str,
    service_uid: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 保护接口
):
    """
    (Admin Only) 移除技师的一项服务技能。
    """
    # 1. 查找技师，并预加载他已有的技能
    query = (
        select(User)
        .where(User.uid == user_uid)
        .options(joinedload(User.service))
    )
    result = await db.execute(query)
    db_technician = result.unique().scalars().first()

    if not db_technician or db_technician.role not in ('technician', 'admin'):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该技师用户不存在"
        )
        
    # 2. 查找服务
    db_service = (await db.execute(
        select(Service).where(Service.uid == service_uid)
    )).scalars().first()
    
    if not db_service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该服务项目不存在"
        )
        
    # 3. 检查技师是否真的掌握该技能
    if db_service not in db_technician.service:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该技师并未掌握此技能"
        )
        
    # 4. 移除技能 (SQLAlchemy 会自动处理多对多关联表)
    db_technician.service.remove(db_service)
    
    db.add(db_technician)
    await db.commit()
    await db.refresh(db_technician, ["service"])
    
    return db_technician

@router.post(
    "/shifts",
    response_model=schemas.ShiftPublic,
    status_code=status.HTTP_201_CREATED,
    summary="创建新排班 (V6)"
)
async def create_shift(
    shift_data: schemas.ShiftCreate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 保护接口
):
    """
    (Admin Only) 为技师在指定地点创建排班。
    - 包含技师排班防重叠检查。
    """
    # 1. 验证技师是否存在
    db_technician = (await db.execute(
        select(User).where(User.uid == shift_data.technician_uid)
    )).scalars().first()
    if not db_technician or db_technician.role not in ('technician', 'admin'):
        raise HTTPException(status_code=404, detail="技师用户不存在")

    # 2. 验证地点是否存在
    db_location = (await db.execute(
        select(Location).where(Location.uid == shift_data.location_uid)
    )).scalars().first()
    if not db_location:
        raise HTTPException(status_code=404, detail="地点不存在")

    try:
        start_time, end_time = schedule_service.compute_period_window(
            shift_data.date,
            shift_data.period.value if isinstance(shift_data.period, schedule_schemas.ShiftPeriod) else shift_data.period
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # 3. (关键) 检查该技师的排班是否重叠
    # 查找该技师已有的、与新排班时间 [start, end] 有任何重叠的排班
    # 重叠条件: (existing.start < new.end) AND (existing.end > new.start)
    overlap_query = select(Shift).where(
        Shift.technician_id == shift_data.technician_uid,
        Shift.is_cancelled == False,
        Shift.start_time < end_time, # 已有排班的开始 < 新排班的结束
        Shift.end_time > start_time   # 已有排班的结束 > 新排班的开始
    )
    existing_shift = (await db.execute(overlap_query)).scalars().first()
    
    if existing_shift:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, # 409 Conflict 冲突
            detail=f"该技师在 {existing_shift.start_time} - {existing_shift.end_time} 已有排班，无法创建重叠排班"
        )

    # 4. 创建新排班
    new_shift = Shift(
        technician_id=shift_data.technician_uid,
        location_id=shift_data.location_uid,
        start_time=start_time,
        end_time=end_time,
        period=(shift_data.period.value if isinstance(shift_data.period, schedule_schemas.ShiftPeriod) else shift_data.period),
        created_by_user_id=admin_user.uid,
        locked_by_admin=True,
        technician=db_technician,
        location=db_location
    )
    db.add(new_shift)
    await db.commit()
    await db.refresh(new_shift, ["technician", "location"])
    
    return new_shift

@router.get(
    "/shifts",
    response_model=List[schemas.ShiftPublic],
    summary="查询排班 (V6)"
)
async def get_shifts(
    location_uid: Optional[str] = None,
    technician_uid: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    include_cancelled: bool = False,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user) # <-- 保护接口
):
    """
    (Admin Only) 查询排班表，可按地点、技师、日期范围过滤。
    """
    query = (
        select(Shift)
        .options(
            joinedload(Shift.technician), # 预加载技师信息
            joinedload(Shift.location)    # 预加载地点信息
        )
        .order_by(Shift.start_time)
    )

    if location_uid:
        query = query.where(Shift.location_id == location_uid)
    if technician_uid:
        query = query.where(Shift.technician_id == technician_uid)
    if start_date:
        start_dt = datetime.combine(start_date, time.min, tzinfo=schedule_service.LOCAL_TIMEZONE)
        query = query.where(Shift.end_time >= start_dt)
    if end_date:
        end_dt = datetime.combine(end_date, time.max, tzinfo=schedule_service.LOCAL_TIMEZONE)
        query = query.where(Shift.start_time <= end_dt)
    if not include_cancelled:
        query = query.where(Shift.is_cancelled == False)

    result = await db.execute(query)
    shifts = result.scalars().unique().all()
    
    return shifts


@router.get(
    "/technicians/{technician_uid}/shift-calendar",
    response_model=schedule_schemas.TechnicianShiftCalendar,
    summary="管理员查看技师排班日历"
)
async def get_technician_shift_calendar_for_admin(
    technician_uid: str,
    days: int = Query(14, ge=1, le=schedule_service.MAX_SHIFT_PLAN_DAYS, description="返回未来多少天的排班"),
    include_cancelled: bool = Query(False, description="是否包含已取消排班"),
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    technician = (await db.execute(
        select(User).where(User.uid == technician_uid)
    )).scalars().first()

    if not technician or technician.role not in ("technician", "admin"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技师不存在")

    return await schedule_service.get_technician_shift_calendar(
        db=db,
        technician=technician,
        days=days,
        include_cancelled=include_cancelled
    )


@router.patch(
    "/shifts/{shift_uid}/cancel",
    response_model=schemas.ShiftPublic,
    summary="取消排班"
)
async def cancel_shift(
    shift_uid: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    try:
        shift = await schedule_service.cancel_shift_by_admin(db, shift_uid, admin_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return shift
