# src/modules/schedule/service.py

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from typing import Iterable, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_, func

from src.shared.models.resource_models import Service, Resource, Location
from src.shared.models.user_models import User
from src.shared.models.schedule_models import Shift
from src.shared.models.appointment_models import AppointmentTechnicianLink, AppointmentResourceLink, Appointment

from .schemas import AppointmentCreate
from . import business_rules

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
WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

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


def resolve_period_for_datetime(dt: datetime) -> Optional[str]:
    """Identify the configured period (morning/afternoon) for the given datetime."""
    local_dt = dt.astimezone(LOCAL_TIMEZONE)
    for period_key, config in DEFAULT_SHIFT_PERIODS.items():
        start_dt = datetime.combine(local_dt.date(), config["start"], tzinfo=LOCAL_TIMEZONE)
        end_dt = datetime.combine(local_dt.date(), config["end"], tzinfo=LOCAL_TIMEZONE)
        if start_dt <= local_dt < end_dt:
            return period_key
    return None


def ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TIMEZONE)
    return value.astimezone(LOCAL_TIMEZONE)
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
    policies_map = await business_rules.load_technician_policies(db, qualified_tech_uids, location_uid)

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

    tech_period_booking_counts: dict[tuple[str, str], int] = defaultdict(int)
    tech_daily_booking_counts: dict[str, int] = defaultdict(int)
    for tech_uid, bookings in tech_bookings_map.items():
        for booking in bookings:
            local_start = ensure_timezone(booking.start_time)
            period_key = resolve_period_for_datetime(local_start)
            if period_key:
                tech_period_booking_counts[(tech_uid, period_key)] += 1
            tech_daily_booking_counts[tech_uid] += 1

    def increment_counts(tech_uid: str, start: datetime):
        local_start = ensure_timezone(start)
        period_key = resolve_period_for_datetime(local_start)
        if period_key:
            tech_period_booking_counts[(tech_uid, period_key)] += 1
        tech_daily_booking_counts[tech_uid] += 1

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

    if holds:
        for hold in holds:
            start = hold.start_time if isinstance(hold.start_time, datetime) else datetime.fromisoformat(str(hold.start_time))
            end = hold.end_time if isinstance(hold.end_time, datetime) else datetime.fromisoformat(str(hold.end_time))
            start = ensure_timezone(start)
            end = ensure_timezone(end)

            if hold.technician_uid:
                tech_bookings_map[hold.technician_uid].append(
                    SimpleNamespace(
                        start_time=start,
                        end_time=end
                    )
                )
                increment_counts(hold.technician_uid, start)
            if hold.resource_uid:
                room_bookings_map[hold.resource_uid].append(
                    SimpleNamespace(
                        start_time=start,
                        end_time=end
                    )
                )

    sorted_technicians = sorted(
        qualified_technicians,
        key=lambda tech: (
            policies_map.get(tech.uid, business_rules.default_policy).priority,
            tech.nickname or "",
            tech.uid
        )
    )

    available_slots: list[str] = []
    for slot_start in sorted(candidate_slots):
        slot_start = slot_start.astimezone(LOCAL_TIMEZONE)
        slot_end_for_tech = slot_start + total_tech_duration
        slot_end_for_room = slot_start + total_room_duration

        if total_tech_duration == timedelta():
            slot_end_for_tech = slot_start

        if total_room_duration == timedelta():
            slot_end_for_room = slot_start + slot_step_delta

        slot_period = resolve_period_for_datetime(slot_start)

        found_tech = False
        for tech in sorted_technicians:
            policy = policies_map.get(tech.uid, business_rules.default_policy)
            if not policy.allow_public_booking:
                continue

            period_quota = business_rules.get_period_quota(policy, slot_period)
            if period_quota is not None and slot_period:
                if tech_period_booking_counts[(tech.uid, slot_period)] >= period_quota:
                    continue

            if policy.max_daily is not None:
                if tech_daily_booking_counts[tech.uid] >= policy.max_daily:
                    continue

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


async def get_available_slots_for_package(
    db: AsyncSession,
    location_uid: str,
    ordered_services: list[Service],
    target_date: date,
    preferred_technician_uid: str | None = None,
    holds: list | None = None
):
    from . import schemas as schedule_schemas

    if not ordered_services:
        return []

    location_row = await db.execute(
        select(Location).where(Location.uid == location_uid)
    )
    location = location_row.scalars().first()
    if not location:
        raise ValueError("指定的地点不存在")

    service_uids = [service.uid for service in ordered_services]

    slot_intervals = [get_slot_interval_minutes(service) for service in ordered_services]
    slot_interval_candidates = [value for value in slot_intervals if value > 0]
    slot_step_minutes = min(slot_interval_candidates) if slot_interval_candidates else DEFAULT_SLOT_INTERVAL_MINUTES
    slot_step_delta = timedelta(minutes=slot_step_minutes)

    total_tech_minutes = 0
    total_room_minutes = 0
    for service in ordered_services:
        buffer_time = max(service.buffer_time or 0, 0)
        total_tech_minutes += max(service.technician_operation_duration or 0, 0) + buffer_time
        total_room_minutes += max(service.room_operation_duration or 0, 0) + buffer_time

    total_tech_duration = timedelta(minutes=total_tech_minutes)
    total_room_duration = timedelta(minutes=total_room_minutes)

    if total_tech_duration == timedelta(0) and total_room_duration == timedelta(0):
        total_tech_duration = slot_step_delta
        total_room_duration = slot_step_delta

    day_start = datetime.combine(target_date, time.min, tzinfo=LOCAL_TIMEZONE)
    day_end = datetime.combine(target_date, time.max, tzinfo=LOCAL_TIMEZONE)

    tech_query = (
        select(User)
        .options(joinedload(User.service))
        .where(User.role.in_(("technician", "admin")))
    )
    if preferred_technician_uid:
        tech_query = tech_query.where(User.uid == preferred_technician_uid)

    technicians = (await db.execute(tech_query)).scalars().unique().all()

    qualified_technicians = []
    for technician in technicians:
        technician_service_uids = {service.uid for service in technician.service}
        if set(service_uids).issubset(technician_service_uids):
            qualified_technicians.append(technician)

    if preferred_technician_uid and not qualified_technicians:
        return []

    if not qualified_technicians:
        return []

    qualified_technician_ids = [technician.uid for technician in qualified_technicians]

    resource_query = (
        select(Resource)
        .options(joinedload(Resource.location), joinedload(Resource.services))
        .where(Resource.location_id == location_uid)
    )
    resources = (await db.execute(resource_query)).scalars().unique().all()

    qualified_resources = []
    for resource in resources:
        resource_service_uids = {service.uid for service in resource.services}
        if set(service_uids).issubset(resource_service_uids):
            qualified_resources.append(resource)

    if not qualified_resources:
        return []

    qualified_resource_ids = [resource.uid for resource in qualified_resources]

    shift_query = (
        select(Shift)
        .options(joinedload(Shift.technician), joinedload(Shift.location))
        .where(
            Shift.technician_id.in_(qualified_technician_ids),
            Shift.location_id == location_uid,
            Shift.is_cancelled == False,
            Shift.start_time < day_end,
            Shift.end_time > day_start
        )
    )
    shifts = (await db.execute(shift_query)).scalars().all()

    if not shifts:
        return []

    shift_map = defaultdict(list)
    for shift in shifts:
        shift_map[shift.technician_id].append(shift)

    capable_technicians = [tech for tech in qualified_technicians if shift_map.get(tech.uid)]
    if not capable_technicians:
        return []

    technician_ids = [tech.uid for tech in capable_technicians]
    policies_map = await business_rules.load_technician_policies(db, technician_ids, location_uid)
    pricing_map = await business_rules.load_pricing_rules(
        db=db,
        service_ids=service_uids,
        technician_ids=technician_ids,
        location_uid=location_uid,
    )

    tech_bookings_query = (
        select(AppointmentTechnicianLink)
        .join(Appointment, Appointment.uid == AppointmentTechnicianLink.appointment_id)
        .where(
            AppointmentTechnicianLink.technician_id.in_(technician_ids),
            AppointmentTechnicianLink.start_time < day_end,
            AppointmentTechnicianLink.end_time > day_start,
            Appointment.location_id == location_uid,
            Appointment.status != 'cancelled'
        )
    )
    tech_bookings = (await db.execute(tech_bookings_query)).scalars().all()
    tech_bookings_map = defaultdict(list)
    for booking in tech_bookings:
        tech_bookings_map[booking.technician_id].append(booking)

    room_bookings_query = (
        select(AppointmentResourceLink)
        .join(Appointment, Appointment.uid == AppointmentResourceLink.appointment_id)
        .where(
            AppointmentResourceLink.resource_id.in_(qualified_resource_ids),
            AppointmentResourceLink.start_time < day_end,
            AppointmentResourceLink.end_time > day_start,
            Appointment.status != 'cancelled'
        )
    )
    room_bookings = (await db.execute(room_bookings_query)).scalars().all()
    room_bookings_map = defaultdict(list)
    for booking in room_bookings:
        room_bookings_map[booking.resource_id].append(booking)

    tech_period_booking_counts: dict[tuple[str, str], int] = defaultdict(int)
    tech_daily_booking_counts: dict[str, int] = defaultdict(int)
    for tech_uid, bookings in tech_bookings_map.items():
        for booking in bookings:
            local_start = ensure_timezone(booking.start_time)
            period_key = resolve_period_for_datetime(local_start)
            if period_key:
                tech_period_booking_counts[(tech_uid, period_key)] += 1
            tech_daily_booking_counts[tech_uid] += 1

    if holds:
        for hold in holds:
            start = hold.start_time if isinstance(hold.start_time, datetime) else datetime.fromisoformat(str(hold.start_time))
            end = hold.end_time if isinstance(hold.end_time, datetime) else datetime.fromisoformat(str(hold.end_time))
            start = ensure_timezone(start)
            end = ensure_timezone(end)

            if hold.technician_uid:
                tech_bookings_map[hold.technician_uid].append(
                    SimpleNamespace(
                        start_time=start,
                        end_time=end
                    )
                )
                period_key = resolve_period_for_datetime(start)
                if period_key:
                    tech_period_booking_counts[(hold.technician_uid, period_key)] += 1
                tech_daily_booking_counts[hold.technician_uid] += 1
            if hold.resource_uid:
                room_bookings_map[hold.resource_uid].append(
                    SimpleNamespace(
                        start_time=start,
                        end_time=end
                    )
                )

    candidate_slots: set[datetime] = set()
    for technician in capable_technicians:
        for shift in shift_map.get(technician.uid, []):
            window_start = max(shift.start_time.astimezone(LOCAL_TIMEZONE), day_start)
            window_end = min(shift.end_time.astimezone(LOCAL_TIMEZONE), day_end)
            if window_end <= window_start:
                continue

            last_start = window_end - total_tech_duration
            if last_start < window_start:
                continue

            current = window_start
            while current <= last_start:
                candidate_slots.add(current)
                current += slot_step_delta

    if not candidate_slots:
        return []

    technician_contexts = []
    for technician in capable_technicians:
        policy = policies_map.get(technician.uid, business_rules.default_policy)
        if not policy.allow_public_booking:
            continue
        technician_contexts.append({
            "technician": technician,
            "policy": policy,
            "priority": policy.priority,
        })

    if preferred_technician_uid:
        technician_contexts = [
            ctx for ctx in technician_contexts
            if ctx["technician"].uid == preferred_technician_uid
        ]
        if not technician_contexts:
            return []
    else:
        technician_contexts.sort(
            key=lambda ctx: (
                ctx["priority"],
                ctx["technician"].nickname or "",
                ctx["technician"].uid
            )
        )

    available_slot_payloads: list[schedule_schemas.PackageAvailabilitySlot] = []

    for slot_start in sorted(candidate_slots):
        slot_end_for_tech = slot_start + total_tech_duration
        slot_end_for_room = slot_start + total_room_duration
        period_key = resolve_period_for_datetime(slot_start)

        for ctx in technician_contexts:
            technician = ctx["technician"]
            policy = ctx["policy"]

            period_quota = business_rules.get_period_quota(policy, period_key)
            if period_quota is not None and period_key:
                if tech_period_booking_counts[(technician.uid, period_key)] >= period_quota:
                    continue

            if policy.max_daily is not None:
                if tech_daily_booking_counts[technician.uid] >= policy.max_daily:
                    continue

            on_shift = any(
                shift.start_time.astimezone(LOCAL_TIMEZONE) <= slot_start and
                shift.end_time.astimezone(LOCAL_TIMEZONE) >= slot_end_for_tech
                for shift in shift_map.get(technician.uid, [])
            )
            if not on_shift:
                continue

            bookings = tech_bookings_map.get(technician.uid, [])
            is_booked = any(
                is_overlap(
                    booking.start_time,
                    booking.end_time,
                    slot_start,
                    slot_end_for_tech
                )
                for booking in bookings
            )
            if is_booked:
                continue

            for resource in qualified_resources:
                bookings = room_bookings_map.get(resource.uid, [])
                is_room_booked = any(
                    is_overlap(
                        booking.start_time,
                        booking.end_time,
                        slot_start,
                        slot_end_for_room
                    )
                    for booking in bookings
                )
                if is_room_booked:
                    continue

                price = business_rules.calculate_total_price(
                    pricing_map=pricing_map,
                    service_ids=service_uids,
                    technician_id=technician.uid,
                    location_id=location.uid if location else None,
                )

                available_slot_payloads.append(
                    schedule_schemas.PackageAvailabilitySlot(
                        start_time=slot_start,
                        technician=schedule_schemas.PackageSlotTechnician(
                            uid=technician.uid,
                            nickname=technician.nickname,
                            phone=technician.phone
                        ),
                        resource=schedule_schemas.PackageSlotResource(
                            uid=resource.uid,
                            name=resource.name
                        ),
                        price=price
                    )
                )
                break

            if available_slot_payloads and available_slot_payloads[-1].start_time == slot_start:
                break

    return available_slot_payloads

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

    location_row = await db.execute(
        select(Location).where(Location.uid == appt_data.location_uid)
    )
    location = location_row.scalars().first()
    if not location:
        raise Exception("预约地点不存在")

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
    appt_start = ensure_timezone(appt_data.start_time)
    appt_tech_end = appt_start + total_tech_duration
    if total_room_duration == timedelta():
        total_room_duration = slot_step_delta
    appt_room_end = appt_start + total_room_duration

    # ----------------------------------------------------
    # 步骤 4.1: 查找空闲的合格技师（含优先级与限额）
    # ----------------------------------------------------
    tech_query = (
        select(User)
        .options(joinedload(User.service))
        .where(
            User.role.in_(("technician", "admin")),
            User.service.any(Service.uid == appt_data.service_uid)
        )
    )
    technicians = (await db.execute(tech_query)).scalars().unique().all()

    if not technicians:
        raise Exception("暂无可执行该服务的技师")

    required_tech_end = appt_start + total_tech_duration
    if total_tech_duration == timedelta():
        required_tech_end = appt_start

    shift_query = (
        select(Shift)
        .options(joinedload(Shift.technician))
        .where(
            Shift.technician_id.in_([tech.uid for tech in technicians]),
            Shift.location_id == appt_data.location_uid,
            Shift.is_cancelled == False,
            Shift.start_time <= appt_start,
            Shift.end_time >= required_tech_end
        )
    )
    shifts = (await db.execute(shift_query)).scalars().all()

    shift_map = defaultdict(list)
    for shift in shifts:
        shift_map[shift.technician_id].append(shift)

    capable_technicians = [tech for tech in technicians if shift_map.get(tech.uid)]
    if not capable_technicians:
        raise Exception("该时间段无排班技师")

    technician_ids = [tech.uid for tech in capable_technicians]
    policies_map = await business_rules.load_technician_policies(db, technician_ids, appt_data.location_uid)

    technician_contexts = []
    for technician in capable_technicians:
        policy = policies_map.get(technician.uid, business_rules.default_policy)
        if not policy.allow_public_booking:
            continue
        technician_contexts.append({
            "technician": technician,
            "policy": policy,
            "priority": policy.priority,
        })

    if not technician_contexts:
        raise Exception("当前时间段无可预约技师")

    technician_contexts.sort(
        key=lambda ctx: (
            ctx["priority"],
            ctx["technician"].nickname or "",
            ctx["technician"].uid
        )
    )

    tech_bookings_query = (
        select(AppointmentTechnicianLink)
        .join(Appointment, Appointment.uid == AppointmentTechnicianLink.appointment_id)
        .where(
            AppointmentTechnicianLink.technician_id.in_([ctx["technician"].uid for ctx in technician_contexts]),
            AppointmentTechnicianLink.start_time < (required_tech_end if total_tech_duration > timedelta() else appt_start),
            AppointmentTechnicianLink.end_time > appt_start,
            Appointment.location_id == appt_data.location_uid,
            Appointment.status != 'cancelled'
        )
    )
    tech_bookings = (await db.execute(tech_bookings_query)).scalars().all()
    tech_bookings_map = defaultdict(list)
    for booking in tech_bookings:
        tech_bookings_map[booking.technician_id].append(booking)

    tech_period_booking_counts: dict[tuple[str, str], int] = defaultdict(int)
    tech_daily_booking_counts: dict[str, int] = defaultdict(int)
    for tech_uid, bookings in tech_bookings_map.items():
        for booking in bookings:
            local_start = ensure_timezone(booking.start_time)
            booking_period = resolve_period_for_datetime(local_start)
            if booking_period:
                tech_period_booking_counts[(tech_uid, booking_period)] += 1
            tech_daily_booking_counts[tech_uid] += 1

    period_key = resolve_period_for_datetime(appt_start)

    available_technician: User | None = None
    for ctx in technician_contexts:
        technician = ctx["technician"]
        policy = ctx["policy"]

        period_quota = business_rules.get_period_quota(policy, period_key)
        if period_quota is not None and period_key:
            if tech_period_booking_counts[(technician.uid, period_key)] >= period_quota:
                continue

        if policy.max_daily is not None:
            if tech_daily_booking_counts[technician.uid] >= policy.max_daily:
                continue

        on_shift = any(
            ensure_timezone(shift.start_time) <= appt_start and
            ensure_timezone(shift.end_time) >= required_tech_end
            for shift in shift_map.get(technician.uid, [])
        )
        if not on_shift:
            continue

        bookings = tech_bookings_map.get(technician.uid, [])
        is_conflicted = any(
            is_overlap(
                ensure_timezone(booking.start_time),
                ensure_timezone(booking.end_time),
                appt_start,
                required_tech_end if total_tech_duration > timedelta() else appt_start
            )
            for booking in bookings
        )
        if is_conflicted:
            continue

        available_technician = technician
        break

    if not available_technician:
        raise Exception("该时间段的技师预约名额已满，请选择其他时间")

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

    booked_rooms_query = (
        select(AppointmentResourceLink.resource_id)
        .join(Appointment, Appointment.uid == AppointmentResourceLink.appointment_id)
        .where(
            AppointmentResourceLink.resource_id.in_([r.uid for r in qualified_rooms]),
            AppointmentResourceLink.start_time < appt_room_end,
            AppointmentResourceLink.end_time > appt_start,
            Appointment.status != 'cancelled'
        )
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


async def get_location_day_summary(
    db: AsyncSession,
    location_uid: str,
    days: int = DEFAULT_CALENDAR_DAYS,
):
    from . import schemas as schedule_schemas

    days = max(1, min(days, MAX_SHIFT_PLAN_DAYS))
    today = datetime.now(LOCAL_TIMEZONE).date()
    end_date = today + timedelta(days=days - 1)
    range_start_dt = datetime.combine(today, time.min, tzinfo=LOCAL_TIMEZONE)
    range_end_dt = datetime.combine(end_date, time.max, tzinfo=LOCAL_TIMEZONE)

    shift_rows = await db.execute(
        select(Shift)
        .where(
            Shift.location_id == location_uid,
            Shift.is_cancelled == False,
            Shift.start_time < range_end_dt,
            Shift.end_time > range_start_dt,
        )
    )
    shifts = shift_rows.scalars().all()

    active_map: dict[date, dict[str, bool]] = {}
    for shift in shifts:
        if not shift.start_time or not shift.end_time:
            continue
        normalized_date = normalize_local_date(shift.start_time)
        period = shift.period or infer_shift_period(shift.start_time, shift.end_time)
        period_map = active_map.setdefault(normalized_date, {})

        def append_slot(period_key: str):
            info = period_map.setdefault(period_key, {
                'active': True,
                'slots': set()
            })
            info['active'] = True
            local_start = shift.start_time.astimezone(LOCAL_TIMEZONE)
            local_end = shift.end_time.astimezone(LOCAL_TIMEZONE)
            cursor = local_start
            while cursor < local_end:
                info['slots'].add(cursor.strftime('%H:%M'))
                cursor += timedelta(hours=1)

        if period in ('morning', 'afternoon'):
            append_slot(period)
        else:
            append_slot('morning')
            append_slot('afternoon')

    summary: list[schedule_schemas.LocationDay] = []
    for offset in range(days):
        current_date = today + timedelta(days=offset)
        period_map = active_map.get(current_date, {})
        morning_info = period_map.get('morning', {'active': False, 'slots': set()})
        afternoon_info = period_map.get('afternoon', {'active': False, 'slots': set()})
        summary.append(
            schedule_schemas.LocationDay(
                date=current_date,
                weekday=WEEKDAY_NAMES[current_date.weekday()],
                has_any_shift=bool(period_map),
                morning_active=morning_info['active'],
                afternoon_active=afternoon_info['active'],
                morning_slots=sorted(morning_info['slots']),
                afternoon_slots=sorted(afternoon_info['slots'])
            )
        )

    return summary


async def list_services_for_location(
    db: AsyncSession,
    location_uid: str
) -> list[Service]:
    service_query = (
        select(Service)
        .options(joinedload(Service.resources), joinedload(Service.technicians))
        .where(Service.resources.any(Resource.location_id == location_uid))
        .order_by(Service.name)
    )
    services = (await db.execute(service_query)).scalars().unique().all()
    return services


async def list_service_options_for_location(
    db: AsyncSession,
    location_uid: str
):
    from . import schemas as schedule_schemas

    services = await list_services_for_location(db, location_uid)
    options: list[schedule_schemas.ServiceOption] = []
    for service in services:
        has_resource = any(res.location_id == location_uid for res in service.resources)
        has_technician = bool(service.technicians)
        options.append(
            schedule_schemas.ServiceOption(
                uid=service.uid,
                name=service.name,
                technician_duration=max(service.technician_operation_duration or 0, 0),
                room_duration=max(service.room_operation_duration or 0, 0),
                buffer_time=max(service.buffer_time or 0, 0),
                is_active=has_resource and has_technician
            )
        )
    return options


async def list_technicians_for_location_services(
    db: AsyncSession,
    location_uid: str,
    service_uids: Iterable[str]
):
    from . import schemas as schedule_schemas

    requested_service_set = {uid for uid in service_uids if uid}

    location_row = await db.execute(select(Location).where(Location.uid == location_uid))
    location = location_row.scalars().first()
    if not location:
        raise ValueError("地点不存在")

    requested_services: list[Service] = []
    if requested_service_set:
        services_rows = await db.execute(
            select(Service).where(Service.uid.in_(requested_service_set))
        )
        requested_services = services_rows.scalars().all()

    tech_query = (
        select(User)
        .options(joinedload(User.service))
        .where(User.role.in_(("technician", "admin")))
        .order_by(User.nickname)
    )
    technicians = (await db.execute(tech_query)).scalars().unique().all()

    service_id_list: list[str] = [service.uid for service in requested_services] if requested_services else []
    pricing_map = {}
    if service_id_list:
        pricing_map = await business_rules.load_pricing_rules(
            db=db,
            service_ids=service_id_list,
            technician_ids=[tech.uid for tech in technicians],
            location_uid=location_uid,
        )

    policies_map = await business_rules.load_technician_policies(
        db=db,
        technician_ids=[tech.uid for tech in technicians],
        location_uid=location_uid,
    )

    now_dt = datetime.now(LOCAL_TIMEZONE)
    shift_rows = await db.execute(
        select(Shift.technician_id)
        .where(
            Shift.location_id == location_uid,
            Shift.is_cancelled == False,
            Shift.end_time > now_dt
        )
    )
    technicians_with_shifts = {row[0] for row in shift_rows}

    options: list[schedule_schemas.TechnicianOption] = []
    for technician in technicians:
        service_set = {service.uid for service in technician.service}
        has_all_services = requested_service_set.issubset(service_set) if requested_service_set else True
        available_for_location = technician.uid in technicians_with_shifts

        is_available = has_all_services and available_for_location
        disabled_reason = None
        if not has_all_services and requested_service_set:
            disabled_reason = "未掌握所选服务"
        elif has_all_services and not available_for_location:
            disabled_reason = "近期无排班"

        policy = policies_map.get(technician.uid, business_rules.default_policy)
        if not policy.allow_public_booking:
            is_available = False
            if not disabled_reason:
                disabled_reason = "暂不开放线上预约"

        price = None
        if has_all_services and requested_services:
            price = business_rules.calculate_total_price(
                pricing_map=pricing_map,
                service_ids=service_id_list,
                technician_id=technician.uid,
                location_id=location.uid,
            )

        options.append(
            schedule_schemas.TechnicianOption(
                uid=technician.uid,
                nickname=technician.nickname,
                phone=technician.phone,
                is_available=is_available,
                disabled_reason=disabled_reason,
                price=price
            )
        )

    return options


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

    booking_intervals: list[tuple[datetime, datetime]] = []
    if shifts:
        bookings_query = (
            select(
                AppointmentTechnicianLink.start_time,
                AppointmentTechnicianLink.end_time
            )
            .join(Appointment, Appointment.uid == AppointmentTechnicianLink.appointment_id)
            .where(
                AppointmentTechnicianLink.technician_id == technician.uid,
                AppointmentTechnicianLink.start_time < range_end_dt,
                AppointmentTechnicianLink.end_time > range_start_dt,
                Appointment.status != 'cancelled'
            )
        )
        booking_rows = (await db.execute(bookings_query)).all()
        booking_intervals = [
            (
                row[0].astimezone(LOCAL_TIMEZONE) if row[0].tzinfo else row[0].replace(tzinfo=LOCAL_TIMEZONE),
                row[1].astimezone(LOCAL_TIMEZONE) if row[1].tzinfo else row[1].replace(tzinfo=LOCAL_TIMEZONE)
            )
            for row in booking_rows
        ]

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
                local_start = shift.start_time if shift.start_time.tzinfo else shift.start_time.replace(tzinfo=LOCAL_TIMEZONE)
                local_end = shift.end_time if shift.end_time.tzinfo else shift.end_time.replace(tzinfo=LOCAL_TIMEZONE)
                has_bookings = any(
                    is_overlap(
                        start,
                        end,
                        local_start,
                        local_end
                    )
                    for start, end in booking_intervals
                )
                slots[period_key] = schedule_schemas.TechnicianShiftSlot(
                    is_active=True,
                    shift_uid=shift.uid,
                    location_uid=shift.location_id,
                    location_name=shift.location.name if shift.location else None,
                    locked_by_admin=bool(shift.locked_by_admin),
                    has_bookings=has_bookings
                )
            else:
                slots[period_key] = schedule_schemas.TechnicianShiftSlot(
                    is_active=False,
                    locked_by_admin=False,
                    has_bookings=False
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
