# src/modules/schedule/service.py

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_

from src.shared.models.resource_models import Service, Resource, Location
from src.shared.models.user_models import User
from src.shared.models.schedule_models import Shift
from src.shared.models.appointment_models import AppointmentTechnicianLink, AppointmentResourceLink, Appointment

from .schemas import AppointmentCreate

# 默认的时间槽长度（分钟）
DEFAULT_SLOT_INTERVAL_MINUTES = 60
# 预设的班次时段（预留扩展能力）
DEFAULT_SHIFT_PERIODS = {
    "morning": {"start": time(8, 30), "end": time(12, 30)},
    "afternoon": {"start": time(14, 0), "end": time(18, 0)}
}
# 本地业务时区
LOCAL_TIMEZONE = timezone(timedelta(hours=8), 'Asia/Shanghai')
MAX_SHIFT_PLAN_DAYS = 30
DEFAULT_CALENDAR_DAYS = 14

# --- 辅助函数：时间范围重叠 ---
def is_overlap(range1_start, range1_end, range2_start, range2_end):
    """检查两个时间范围 [start, end) 是否重叠"""
    # 确保比较的是同类型（例如都是 aware datetime）
    return range1_start < range2_end and range1_end > range2_start

def get_slot_interval_minutes(service: Service) -> int:
    """
    获取服务对应的时间槽步长（分钟），预留未来扩展。
    优先使用自定义字段，其次使用技师耗时，最后回退到默认配置。
    """
    custom_interval = getattr(service, "slot_interval_minutes", None)
    if isinstance(custom_interval, int) and custom_interval > 0:
        return custom_interval

    duration = max(service.technician_operation_duration, 0)
    if duration > 0:
        return duration

    return DEFAULT_SLOT_INTERVAL_MINUTES


def compute_period_window(target_date: date, period: str) -> tuple[datetime, datetime]:
    config = DEFAULT_SHIFT_PERIODS.get(period)
    if not config:
        raise ValueError(f"未知班次时段: {period}")
    start_dt = datetime.combine(target_date, config["start"], tzinfo=LOCAL_TIMEZONE)
    end_dt = datetime.combine(target_date, config["end"], tzinfo=LOCAL_TIMEZONE)
    if end_dt <= start_dt:
        raise ValueError("班次结束时间必须晚于开始时间")
    return start_dt, end_dt


def infer_shift_period(start: datetime, end: datetime) -> str | None:
    if not start or not end:
        return None
    local_start = start.astimezone(LOCAL_TIMEZONE)
    local_end = end.astimezone(LOCAL_TIMEZONE)
    for key, config in DEFAULT_SHIFT_PERIODS.items():
        expected_start = datetime.combine(local_start.date(), config["start"], tzinfo=LOCAL_TIMEZONE)
        expected_end = datetime.combine(local_start.date(), config["end"], tzinfo=LOCAL_TIMEZONE)
        if local_start == expected_start and local_end == expected_end:
            return key
    return None


def normalize_local_date(dt: datetime) -> date:
    return dt.astimezone(LOCAL_TIMEZONE).date()

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

    slot_step_minutes = get_slot_interval_minutes(db_service)
    slot_step_delta = timedelta(minutes=slot_step_minutes)

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
                and_(
                    Shift.location_id == location_uid,
                    Shift.is_cancelled == False,
                    Shift.start_time < day_end,
                    Shift.end_time > day_start
                )
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
    room_query = select(Resource).where(
        Resource.location_id == location_uid,
        Resource.services.any(Service.uid == service_uid)
    )
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
    tech_bookings_map = defaultdict(list)
    for booking in tech_bookings:
        tech_bookings_map[booking.technician_id].append(booking)

    # b. 房间的预约
    room_bookings_query = select(AppointmentResourceLink).where(
        AppointmentResourceLink.resource_id.in_(qualified_room_uids),
        AppointmentResourceLink.start_time < day_end,
        AppointmentResourceLink.end_time > day_start
    )
    room_bookings = (await db.execute(room_bookings_query)).scalars().all()
    room_bookings_map = defaultdict(list)
    for booking in room_bookings:
        room_bookings_map[booking.resource_id].append(booking)

    # ----------------------------------------------------
    # 步骤 6: 基于排班生成候选时间槽
    # ----------------------------------------------------
    candidate_slots: set[datetime] = set()
    for tech in qualified_technicians:
        for shift in getattr(tech, "shifts", []):
            if getattr(shift, "is_cancelled", False):
                continue
            if shift.location_id != location_uid:
                continue
            if shift.end_time <= day_start or shift.start_time >= day_end:
                continue

            window_start = max(shift.start_time.astimezone(LOCAL_TIMEZONE), day_start)
            window_end = min(shift.end_time.astimezone(LOCAL_TIMEZONE), day_end)
            if window_end <= window_start:
                continue

            if total_tech_duration > timedelta(0):
                last_start = window_end - total_tech_duration
            else:
                last_start = window_end - slot_step_delta

            if last_start < window_start:
                continue

            current = window_start
            while current <= last_start:
                candidate_slots.add(current)
                current += slot_step_delta

    if not candidate_slots:
        return []

    available_slots: list[str] = []
    for slot_start in sorted(candidate_slots):
        slot_start = slot_start.astimezone(LOCAL_TIMEZONE)
        slot_end_for_tech = slot_start + total_tech_duration
        slot_end_for_room = slot_start + total_room_duration

        if total_tech_duration == timedelta():
            slot_end_for_tech = slot_start

        if total_room_duration == timedelta():
            slot_end_for_room = slot_start + slot_step_delta

        found_tech = False
        for tech in qualified_technicians:
            on_shift = any(
                shift.location_id == location_uid and
                shift.start_time <= slot_start and
                shift.end_time >= (slot_end_for_tech if total_tech_duration > timedelta() else slot_start)
                for shift in getattr(tech, "shifts", [])
            )
            if not on_shift:
                continue

            bookings = tech_bookings_map.get(tech.uid, [])
            is_booked = any(
                is_overlap(
                    booking.start_time,
                    booking.end_time,
                    slot_start,
                    slot_end_for_tech if total_tech_duration > timedelta() else slot_start
                )
                for booking in bookings
            )
            if is_booked:
                continue

            found_tech = True
            break

        if not found_tech:
            continue

        found_room = False
        for room in qualified_rooms:
            bookings = room_bookings_map.get(room.uid, [])
            is_booked = any(
                is_overlap(
                    booking.start_time,
                    booking.end_time,
                    slot_start,
                    slot_end_for_room
                )
                for booking in bookings
            )
            if is_booked:
                continue

            found_room = True
            break

        if not found_room:
            continue

        available_slots.append(slot_start.strftime('%H:%M'))

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

    slot_step_minutes = get_slot_interval_minutes(db_service)
    slot_step_delta = timedelta(minutes=slot_step_minutes)

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
    if total_room_duration == timedelta():
        total_room_duration = slot_step_delta
    appt_room_end = appt_start + total_room_duration

    # ----------------------------------------------------
    # 步骤 4.1: 查找空闲的合格技师
    # ----------------------------------------------------
    capable_tech_uids = [
        tech.uid for tech in (await db.execute(
            select(User).join(User.service).where(Service.uid == appt_data.service_uid)
        )).scalars().all()
    ]

    required_tech_end = appt_start + total_tech_duration
    if total_tech_duration == timedelta():
        required_tech_end = appt_start

    shift_query = (
        select(Shift)
        .options(joinedload(Shift.technician))
        .where(
            Shift.technician_id.in_(capable_tech_uids),
            Shift.location_id == appt_data.location_uid,
            Shift.is_cancelled == False,
            Shift.start_time <= appt_start,
            Shift.end_time >= required_tech_end
        )
        .order_by(Shift.start_time)
    )
    candidate_shifts = (await db.execute(shift_query)).scalars().all()

    if not candidate_shifts:
        raise Exception("没有技师在此时间排班或排班时间不足")

    candidate_tech_ids = [shift.technician_id for shift in candidate_shifts]

    booked_techs_query = select(AppointmentTechnicianLink.technician_id).where(
        AppointmentTechnicianLink.technician_id.in_(candidate_tech_ids),
        AppointmentTechnicianLink.start_time < (required_tech_end if total_tech_duration > timedelta() else appt_start),
        AppointmentTechnicianLink.end_time > appt_start
    )
    booked_tech_ids = set((await db.execute(booked_techs_query)).scalars().all())

    chosen_shift: Shift | None = None
    for shift in candidate_shifts:
        if shift.technician_id not in booked_tech_ids:
            chosen_shift = shift
            break

    if not chosen_shift:
        raise Exception("该时间段的技师已被预约，请选择其他时间")

    available_technician = chosen_shift.technician

    # ----------------------------------------------------
    # 步骤 4.2: (重构) 查找空闲的合格房间
    # ----------------------------------------------------
    qualified_rooms_query = select(Resource).where(
        Resource.location_id == appt_data.location_uid,
        Resource.services.any(Service.uid == appt_data.service_uid)
    )
    qualified_rooms = (await db.execute(qualified_rooms_query)).scalars().all()

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


# --- 技师排班管理 ---

async def list_schedule_locations(db: AsyncSession) -> list[Location]:
    result = await db.execute(select(Location).order_by(Location.name))
    return result.scalars().all()


async def create_shifts_for_technician(
    db: AsyncSession,
    technician: User,
    items: list,
    created_by_user: User | None = None,
    lock_created_by_admin: bool = False,
) -> list[Shift]:
    from . import schemas as schedule_schemas

    if not items:
        return []

    today = datetime.now(LOCAL_TIMEZONE).date()
    max_date = today + timedelta(days=MAX_SHIFT_PLAN_DAYS)

    normalized_items: list[schedule_schemas.TechnicianShiftCreateItem] = []
    for item in items:
        payload = (item if isinstance(item, schedule_schemas.TechnicianShiftCreateItem)
                   else schedule_schemas.TechnicianShiftCreateItem.model_validate(item))

        if payload.date < today or payload.date > max_date:
            continue
        normalized_items.append(payload)

    if not normalized_items:
        return []

    location_uids = {payload.location_uid for payload in normalized_items}
    location_map = {loc.uid: loc for loc in await list_schedule_locations(db)}
    if not location_uids.issubset(location_map.keys()):
        raise ValueError("存在无效的地点，无法创建排班")

    window_start = min(payload.date for payload in normalized_items)
    window_end = max(payload.date for payload in normalized_items)
    range_start_dt = datetime.combine(window_start, time.min, tzinfo=LOCAL_TIMEZONE)
    range_end_dt = datetime.combine(window_end, time.max, tzinfo=LOCAL_TIMEZONE)

    existing_shifts_query = (
        select(Shift)
        .where(
            Shift.technician_id == technician.uid,
            Shift.is_cancelled == False,
            Shift.start_time < range_end_dt,
            Shift.end_time > range_start_dt,
        )
    )
    existing_shifts = (await db.execute(existing_shifts_query)).scalars().all()

    existing_index: dict[tuple[date, str], Shift] = {}
    for shift in existing_shifts:
        period = shift.period or infer_shift_period(shift.start_time, shift.end_time)
        if not period:
            continue
        existing_index[(normalize_local_date(shift.start_time), period)] = shift

    created_shifts: list[Shift] = []
    for payload in normalized_items:
        period_key = payload.period.value
        key = (payload.date, period_key)
        if key in existing_index:
            continue

        start_time, end_time = compute_period_window(payload.date, period_key)

        conflict = False
        for shift in existing_shifts:
            if is_overlap(shift.start_time, shift.end_time, start_time, end_time):
                conflict = True
                break
        if conflict:
            continue

        new_shift = Shift(
            technician_id=technician.uid,
            location_id=payload.location_uid,
            start_time=start_time,
            end_time=end_time,
            period=period_key,
            created_by_user_id=(created_by_user.uid if created_by_user else technician.uid),
            locked_by_admin=lock_created_by_admin,
            is_cancelled=False,
        )
        db.add(new_shift)
        created_shifts.append(new_shift)

    if not created_shifts:
        await db.rollback()
        return []

    await db.commit()
    for shift in created_shifts:
        await db.refresh(shift, ["location"])
    return created_shifts


async def get_technician_shift_calendar(
    db: AsyncSession,
    technician: User,
    days: int = DEFAULT_CALENDAR_DAYS,
    include_cancelled: bool = False,
):
    from . import schemas as schedule_schemas

    days = max(1, min(days, MAX_SHIFT_PLAN_DAYS))
    today = datetime.now(LOCAL_TIMEZONE).date()
    end_date = today + timedelta(days=days - 1)
    range_start_dt = datetime.combine(today, time.min, tzinfo=LOCAL_TIMEZONE)
    range_end_dt = datetime.combine(end_date, time.max, tzinfo=LOCAL_TIMEZONE)

    shift_query = (
        select(Shift)
        .options(joinedload(Shift.location))
        .where(
            Shift.technician_id == technician.uid,
            Shift.start_time < range_end_dt,
            Shift.end_time > range_start_dt,
        )
    )
    if not include_cancelled:
        shift_query = shift_query.where(Shift.is_cancelled == False)

    shifts = (await db.execute(shift_query)).scalars().all()

    shift_map: dict[tuple[date, str], Shift] = {}
    for shift in shifts:
        if shift.is_cancelled:
            continue
        period = shift.period or infer_shift_period(shift.start_time, shift.end_time)
        if not period:
            continue
        shift_map[(normalize_local_date(shift.start_time), period)] = shift

    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    days_payload: list[schedule_schemas.TechnicianShiftDay] = []
    for offset in range(days):
        current_date = today + timedelta(days=offset)
        weekday = weekday_names[current_date.weekday()]

        slots = {}
        for period_key in ['morning', 'afternoon']:
            shift = shift_map.get((current_date, period_key))
            if shift:
                slots[period_key] = schedule_schemas.TechnicianShiftSlot(
                    is_active=True,
                    shift_uid=shift.uid,
                    location_uid=shift.location_id,
                    location_name=shift.location.name if shift.location else None,
                    locked_by_admin=bool(shift.locked_by_admin)
                )
            else:
                slots[period_key] = schedule_schemas.TechnicianShiftSlot(
                    is_active=False,
                    locked_by_admin=False
                )

        days_payload.append(
            schedule_schemas.TechnicianShiftDay(
                date=current_date,
                weekday=weekday,
                morning=slots['morning'],
                afternoon=slots['afternoon']
            )
        )

    location_options = [
        schedule_schemas.LocationOption(uid=loc.uid, name=loc.name or '未命名地点')
        for loc in await list_schedule_locations(db)
    ]

    return schedule_schemas.TechnicianShiftCalendar(
        generated_at=datetime.now(LOCAL_TIMEZONE),
        days=days_payload,
        locations=location_options
    )


async def cancel_shift_by_admin(
    db: AsyncSession,
    shift_uid: str,
    admin_user: User
) -> Shift:
    shift_query = (
        select(Shift)
        .options(joinedload(Shift.technician), joinedload(Shift.location))
        .where(Shift.uid == shift_uid)
    )
    shift = (await db.execute(shift_query)).scalars().first()
    if not shift:
        raise ValueError("排班不存在")

    if shift.is_cancelled:
        return shift

    # 检查是否存在未来预约
    conflict_query = (
        select(Appointment)
        .join(AppointmentTechnicianLink)
        .where(
            AppointmentTechnicianLink.technician_id == shift.technician_id,
            AppointmentTechnicianLink.start_time < shift.end_time,
            AppointmentTechnicianLink.end_time > shift.start_time,
            Appointment.status != 'cancelled'
        )
    )
    conflict = (await db.execute(conflict_query)).scalars().first()
    if conflict:
        raise ValueError("该排班已有预约，请先处理相关预约后再取消")

    shift.is_cancelled = True
    shift.cancelled_at = datetime.now(LOCAL_TIMEZONE)
    shift.cancelled_by_user_id = admin_user.uid
    shift.locked_by_admin = True

    db.add(shift)
    await db.commit()
    await db.refresh(shift, ["technician", "location"])
    return shift
