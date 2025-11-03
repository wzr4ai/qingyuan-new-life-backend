# src/modules/schedule/router.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import date

from src.core.database import get_db
from src.modules.auth.security import get_current_user # 1. 导入 get_current_user (普通用户即可)
from src.shared.models.user_models import User
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
