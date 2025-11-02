# src/modules/schedule/service.py

from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_

from src.shared.models.resource_models import Service, Resource
from src.shared.models.user_models import User
from src.shared.models.schedule_models import Shift
from src.shared.models.appointment_models import AppointmentTechnicianLink, AppointmentResourceLink, Appointment

from .schemas import AppointmentCreate

# 定义时间槽的步长（例如每 10 分钟检查一次）
SLOT_INTERVAL_MINUTES = 10
# 定义时区 (您服务器或业务所在时区，例如东八区)
# 确保与数据库中存储的 timezone=True 匹配
# 这是一个示例，请根据您的服务器配置调整
LOCAL_TIMEZONE = timezone(timedelta(hours=8), 'Asia/Shanghai') 

# --- 辅助函数：时间范围重叠 ---
def is_overlap(range1_start, range1_end, range2_start, range2_end):
    """检查两个时间范围 [start, end) 是否重叠"""
    # 确保比较的是同类型（例如都是 aware datetime）
    return range1_start < range2_end and range1_end > range2_start

# --- 核心调度算法 ---

async def get_available_slots(
    db: AsyncSession, 
    location_uid: str, 
    service_uid: str, 
    target_date: date
) -> list[str]:
    
    # ----------------------------------------------------
    # 步骤 1 & 2: 获取服务详情并计算总占用
    # ----------------------------------------------------
    db_service = (await db.execute(
        select(Service).where(Service.uid == service_uid)
    )).scalars().first()
    
    if not db_service:
        raise Exception("服务项目不存在") # 稍后在 router 层转为 HTTPException

    total_tech_duration = timedelta(minutes=(
        db_service.technician_operation_duration + db_service.buffer_time
    ))
    total_room_duration = timedelta(minutes=(
        db_service.room_operation_duration + db_service.buffer_time
    ))
    
    # ----------------------------------------------------
    # 步骤 3: 确定日期的时间范围
    # ----------------------------------------------------
    # 将 date 转换为 datetime (从当天 00:00 到 23:59:59)
    # 我们使用您服务器/业务的本地时区
    day_start = datetime.combine(target_date, time.min, tzinfo=LOCAL_TIMEZONE)
    day_end = datetime.combine(target_date, time.max, tzinfo=LOCAL_TIMEZONE)

    # ----------------------------------------------------
    # 步骤 4.1: 筛选合格的技师 (V6 逻辑)
    # ----------------------------------------------------
    # a. 找到能做该服务 (service_uid) 的所有技师
    capable_tech_query = (
        select(User)
        .join(User.service)
        .where(Service.uid == service_uid)
    )
    capable_techs = (await db.execute(capable_tech_query)).scalars().all()
    capable_tech_uids = [tech.uid for tech in capable_techs]

    if not capable_tech_uids:
        return [] # 没有任何技师能做这个服务

    # b. 在这些技师中，找到在 'target_date' 于 'location_uid' 有排班 (Shift) 的人
    # 并且预加载排班信息 (shifts)
    shift_query = (
        select(User)
        .options(joinedload(User.shifts)) # 预加载排班
        .where(
            User.uid.in_(capable_tech_uids),
            User.shifts.any(
                Shift.location_id == location_uid,
                Shift.start_time < day_end, # 排班开始 < 当天结束
                Shift.end_time > day_start   # 排班结束 > 当天开始
            )
        )
    )
    qualified_technicians = (await db.execute(shift_query)).scalars().unique().all()
    qualified_tech_uids = [tech.uid for tech in qualified_technicians]
    
    if not qualified_technicians:
        return [] # 今天这个地点，没有能做这个服务的技师在上班

    # ----------------------------------------------------
    # 步骤 4.2: 筛选合格的房间
    # ----------------------------------------------------
    room_query = select(Resource).where(Resource.location_id == location_uid)
    qualified_rooms = (await db.execute(room_query)).scalars().all()
    qualified_room_uids = [room.uid for room in qualified_rooms]

    if not qualified_rooms:
        return [] # 这个地点没有任何房间/床位

    # ----------------------------------------------------
    # 步骤 5: 获取当天的所有现有预约
    # ----------------------------------------------------
    
    # a. 技师的预约
    tech_bookings_query = select(AppointmentTechnicianLink).where(
        AppointmentTechnicianLink.technician_id.in_(qualified_tech_uids),
        AppointmentTechnicianLink.start_time < day_end,
        AppointmentTechnicianLink.end_time > day_start
    )
    tech_bookings = (await db.execute(tech_bookings_query)).scalars().all()

    # b. 房间的预约
    room_bookings_query = select(AppointmentResourceLink).where(
        AppointmentResourceLink.resource_id.in_(qualified_room_uids),
        AppointmentResourceLink.start_time < day_end,
        AppointmentResourceLink.end_time > day_start
    )
    room_bookings = (await db.execute(room_bookings_query)).scalars().all()

    # ----------------------------------------------------
    # 步骤 6: 迭代计算 (核心算法)
    # ----------------------------------------------------
    available_slots = []
    
    # 我们只在技师的最早排班时间和最晚排班时间之间搜索
    # (为简化，我们先从 8:00 到 20:00 搜索，后续可优化)
    
    # 确定当天的最早工作时间和最晚工作时间（基于所有排班）
    all_shifts_today = []
    for tech in qualified_technicians:
        for shift in tech.shifts:
            # 筛选出当天的排班
            if is_overlap(shift.start_time, shift.end_time, day_start, day_end):
                all_shifts_today.append(shift)
    
    if not all_shifts_today:
        return [] # 虽然查到了技师，但他们的排班可能不在今天 (逻辑冗余，以防万一)

    # 找到搜索的起点和终点
    search_start = max(day_start, min(s.start_time for s in all_shifts_today))
    search_end = min(day_end, max(s.end_time for s in all_shifts_today))

    current_slot_start = search_start
    
    while current_slot_start < search_end:
        
        # a. 计算此槽的技师和房间占用时段
        slot_tech_end = current_slot_start + total_tech_duration
        slot_room_end = current_slot_start + total_room_duration
        
        # b. 检查技师可用性
        found_tech = False
        for tech in qualified_technicians:
            # i. 检查技师是否正在排班
            is_on_shift = False
            for shift in tech.shifts:
                if (shift.start_time <= current_slot_start and 
                    shift.end_time >= slot_tech_end): # 技师的排班必须完全覆盖技师的操作时间
                    is_on_shift = True
                    break
            
            if not is_on_shift:
                continue # 技师不在班，看下一个技师
            
            # ii. 检查技师是否已有预约
            is_booked = False
            for booking in tech_bookings:
                if booking.technician_id == tech.uid:
                    if is_overlap(booking.start_time, booking.end_time, 
                                  current_slot_start, slot_tech_end):
                        is_booked = True
                        break # 技师被占用了，跳出预约循环
            
            if not is_booked:
                found_tech = True # 找到了一个空闲且在班的技师！
                break # 跳出技师循环
        
        if not found_tech:
            # 没有技师可用，跳到下一个时间槽
            current_slot_start += timedelta(minutes=SLOT_INTERVAL_MINUTES)
            continue

        # c. 检查房间可用性
        found_room = False
        for room in qualified_rooms:
            # i. 检查房间是否已有预约
            is_booked = False
            for booking in room_bookings:
                if booking.resource_id == room.uid:
                    if is_overlap(booking.start_time, booking.end_time, 
                                  current_slot_start, slot_room_end):
                        is_booked = True
                        break # 房间被占用了，跳出预约循环
            
            if not is_booked:
                found_room = True # 找到了一个空闲的房间！
                break # 跳出房间循环
        
        # d. 决策
        if found_tech and found_room:
            # 格式化时间 (例如 "09:00")
            slot_str = current_slot_start.strftime('%H:%M')
            available_slots.append(slot_str)
            
        # 移到下一个时间槽
        current_slot_start += timedelta(minutes=SLOT_INTERVAL_MINUTES)

    return available_slots

async def create_appointment(
    db: AsyncSession, 
    customer: User, # <-- 传入当前登录的用户
    appt_data: AppointmentCreate
) -> Appointment:
    
    # ----------------------------------------------------
    # 步骤 1 & 2: 获取服务详情并计算总占用
    # (与 get_available_slots 相同的逻辑)
    # ----------------------------------------------------
    db_service = (await db.execute(
        select(Service).where(Service.uid == appt_data.service_uid)
    )).scalars().first()
    
    if not db_service:
        raise Exception("服务项目不存在")

    total_tech_duration = timedelta(minutes=(
        db_service.technician_operation_duration + db_service.buffer_time
    ))
    total_room_duration = timedelta(minutes=(
        db_service.room_operation_duration + db_service.buffer_time
    ))
    
    # ----------------------------------------------------
    # 步骤 3: 确定预约的时间范围
    # ----------------------------------------------------
    appt_start = appt_data.start_time
    appt_tech_end = appt_start + total_tech_duration
    appt_room_end = appt_start + total_room_duration

    # ----------------------------------------------------
    # 步骤 4.1: (重构) 查找空闲的合格技师
    # ----------------------------------------------------
    # (这是 get_available_slots 逻辑的简化版)
    
    capable_tech_uids = [
        tech.uid for tech in (await db.execute(
            select(User).join(User.service).where(Service.uid == appt_data.service_uid)
        )).scalars().all()
    ]
    
    # (V6 逻辑) 找到在 'appt_start' 和 'appt_tech_end' 之间
    # 1. 正在排班
    # 2. 且没有被预约
    # 的技师
    
    # 使用 FOR UPDATE (Pessimistic Locking) 锁定技师的预约表
    # 这不是 SQL-Alchemy 异步的直接支持方式，
    # 我们使用简化的“先检查后创建”逻辑，并依赖事务的原子性
    
    # 找到所有合格的技师 (在班 + 能做服务)
    shift_query = (
        select(User)
        .join(User.shifts)
        .where(
            User.uid.in_(capable_tech_uids),
            Shift.location_id == appt_data.location_uid,
            Shift.start_time <= appt_start, # 技师的排班必须在预约开始前 *开始*
            Shift.end_time >= appt_tech_end   # 技师的排班必须在预约结束后 *结束*
        )
    )
    qualified_technicians = (await db.execute(shift_query)).scalars().unique().all()
    
    if not qualified_technicians:
        raise Exception("没有技师在此时间排班或排班时间不足")

    # 找到已被预约的技师
    booked_techs_query = select(AppointmentTechnicianLink.technician_id).where(
        AppointmentTechnicianLink.technician_id.in_([t.uid for t in qualified_technicians]),
        # 检查时间重叠
        AppointmentTechnicianLink.start_time < appt_tech_end,
        AppointmentTechnicianLink.end_time > appt_start
    )
    booked_tech_ids = (await db.execute(booked_techs_query)).scalars().all()

    # 找到第一个空闲的技师
    available_technician: User | None = None
    for tech in qualified_technicians:
        if tech.uid not in booked_tech_ids:
            available_technician = tech
            break # 找到一个！

    if not available_technician:
        raise Exception("该时间段的技师已被预约，请选择其他时间") # 竞态条件失败

    # ----------------------------------------------------
    # 步骤 4.2: (重构) 查找空闲的合格房间
    # ----------------------------------------------------
    qualified_rooms = (await db.execute(
        select(Resource).where(Resource.location_id == appt_data.location_uid)
    )).scalars().all()

    if not qualified_rooms:
        raise Exception("该地点没有可用的房间/床位")

    booked_rooms_query = select(AppointmentResourceLink.resource_id).where(
        AppointmentResourceLink.resource_id.in_([r.uid for r in qualified_rooms]),
        # 检查时间重叠
        AppointmentResourceLink.start_time < appt_room_end,
        AppointmentResourceLink.end_time > appt_start
    )
    booked_room_ids = (await db.execute(booked_rooms_query)).scalars().all()

    # 找到第一个空闲的房间
    available_room: Resource | None = None
    for room in qualified_rooms:
        if room.uid not in booked_room_ids:
            available_room = room
            break # 找到一个！

    if not available_room:
        raise Exception("该时间段的房间已被预约，请选择其他时间") # 竞态条件失败

    # ----------------------------------------------------
    # 步骤 5: 创建所有记录 (事务)
    # ----------------------------------------------------
    try:
        # 1. 创建 Appointment 主记录
        new_appointment = Appointment(
            customer_id=customer.uid,
            service_id=appt_data.service_uid,
            location_id=appt_data.location_uid,
            start_time=appt_start
            # status 默认为 'confirmed'
        )
        db.add(new_appointment)
        await db.flush() # 立即执行以获取 new_appointment.uid

        # 2. 创建 技师 占用记录
        tech_link = AppointmentTechnicianLink(
            appointment_id=new_appointment.uid,
            technician_id=available_technician.uid,
            start_time=appt_start,
            end_time=appt_tech_end
        )
        db.add(tech_link)

        # 3. 创建 房间 占用记录
        room_link = AppointmentResourceLink(
            appointment_id=new_appointment.uid,
            resource_id=available_room.uid,
            start_time=appt_start,
            end_time=appt_room_end
        )
        db.add(room_link)

        # 4. 提交事务
        await db.commit()
        
        return new_appointment

    except Exception as e:
        # 如果任何一步失败（例如数据库的唯一约束冲突），则全部回滚
        await db.rollback()
        print(f"创建预约时发生严重错误: {e}")
        raise Exception(f"预约失败，请重试。错误: {e}")