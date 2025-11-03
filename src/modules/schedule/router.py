# src/modules/schedule/router.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from datetime import date

from src.core.database import get_db
from src.modules.auth.security import get_current_user # 1. 导入 get_current_user (普通用户即可)
from src.shared.models.user_models import User
from src.shared.models.resource_models import Service
from . import schemas
from . import service as schedule_service

router = APIRouter(
    tags=["Schedule (Customer)"],
    responses={404: {"description": "Not found"}},
)

@router.get(
    "/availability",
    response_model=schemas.AvailabilityResponse,
    summary="查询可用预约时间槽 (核心)"
)
async def get_availability(
    location_uid: str = Query(..., description="地点UID"),
    service_uid: str = Query(..., description="服务UID"),
    target_date: date = Query(..., description="查询日期 (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    # 2. 保护此接口，必须是登录用户才能查询
    current_user: User = Depends(get_current_user) 
):
    """
    (Customer Facing) 实时查询可预约的时间。
    
    这是系统的核心调度接口，基于 V6 架构 (排班表) 运行。
    """
    try:
        slots = await schedule_service.get_available_slots(
            db=db,
            location_uid=location_uid,
            service_uid=service_uid,
            target_date=target_date
        )
        
        return schemas.AvailabilityResponse(available_slots=slots)
        
    except Exception as e:
        # 捕获 service 层可能抛出的异常
        print(f"Error in get_availability: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e) or "查询可用时间失败"
        )
    
@router.post(
    "/appointments",
    response_model=schemas.AppointmentPublic,
    status_code=status.HTTP_201_CREATED,
    summary="创建新预约 (核心)"
)
async def create_new_appointment(
    appointment_data: schemas.AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user) # <-- 必须登录
):
    """
    (Customer Facing) 客户提交预约。
    
    服务器将在此处执行最终的可用性检查（防止竞态条件）。
    """
    try:
        new_appointment = await schedule_service.create_appointment(
            db=db,
            customer=current_user,
            appt_data=appointment_data
        )
        
        # 使用我们 V1 的简单
        return schemas.AppointmentPublic.from_orm_simple(new_appointment)
        
    except Exception as e:
        # 捕获 service 层抛出的所有异常 (例如 "技师已被预约")
        print(f"Error in create_new_appointment: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, # 409 Conflict (资源冲突)
            detail=str(e) or "预约失败，该时间段可能刚被预订"
        )


@router.get(
    "/my-shifts",
    response_model=schemas.TechnicianShiftCalendar,
    summary="技师查看未来排班"
)
async def get_my_shifts(
    days: int = Query(14, ge=1, le=60, description="返回未来多少天的排班"),
    include_cancelled: bool = Query(False, description="是否包含已取消的排班"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ("technician", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅技师或管理员可查看排班")

    return await schedule_service.get_technician_shift_calendar(
        db=db,
        technician=current_user,
        days=days,
        include_cancelled=include_cancelled
    )


@router.post(
    "/my-shifts",
    response_model=schemas.TechnicianShiftCalendar,
    status_code=status.HTTP_201_CREATED,
    summary="技师新增排班"
)
async def create_my_shifts(
    payload: schemas.TechnicianShiftCreateRequest,
    days: int = Query(14, ge=1, le=60, description="返回未来多少天的排班"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ("technician", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅技师或管理员可操作排班")

    try:
        await schedule_service.create_shifts_for_technician(
            db=db,
            technician=current_user,
            items=payload.items,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return await schedule_service.get_technician_shift_calendar(
        db=db,
        technician=current_user,
        days=days
    )


@router.get(
    "/locations",
    response_model=List[schemas.LocationOption],
    summary="获取排班可用地点列表"
)
async def get_schedule_locations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    locations = await schedule_service.list_schedule_locations(db)
    return [
        schemas.LocationOption(uid=loc.uid, name=loc.name or '未命名地点')
        for loc in locations
    ]


@router.get(
    "/location-days",
    response_model=List[schemas.LocationDay],
    summary="获取地点可排班日期"
)
async def get_location_days(
    location_uid: str = Query(..., description="地点UID"),
    days: int = Query(14, ge=1, le=schedule_service.MAX_SHIFT_PLAN_DAYS, description="返回未来多少天"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await schedule_service.get_location_day_summary(
        db=db,
        location_uid=location_uid,
        days=days
    )


@router.get(
    "/location-services",
    response_model=List[schemas.ServiceOption],
    summary="获取地点可用服务"
)
async def get_location_services(
    location_uid: str = Query(..., description="地点UID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await schedule_service.list_service_options_for_location(db, location_uid)


@router.post(
    "/location-technicians",
    response_model=List[schemas.TechnicianOption],
    summary="获取地点技师偏好列表"
)
async def get_location_technicians(
    payload: schemas.TechnicianFilterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await schedule_service.list_technicians_for_location_services(
        db=db,
        location_uid=payload.location_uid,
        service_uids=payload.service_uids
    )


@router.post(
    "/package-availability",
    response_model=schemas.PackageAvailabilityResponse,
    summary="查询服务组合可用时间"
)
async def get_package_availability(
    payload: schemas.PackageAvailabilityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        services_query = select(Service).where(Service.uid.in_(payload.ordered_service_uids))
        service_result = await db.execute(services_query)
        service_map = {service.uid: service for service in service_result.scalars().all()}

        ordered_services = []
        for service_uid in payload.ordered_service_uids:
            service = service_map.get(service_uid)
            if not service:
                raise ValueError(f"服务 {service_uid} 不存在")
            ordered_services.append(service)

        slots = await schedule_service.get_available_slots_for_package(
            db=db,
            location_uid=payload.location_uid,
            ordered_services=ordered_services,
            target_date=payload.target_date,
            preferred_technician_uid=payload.preferred_technician_uid,
            holds=payload.holds
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return schemas.PackageAvailabilityResponse(available_slots=slots)
