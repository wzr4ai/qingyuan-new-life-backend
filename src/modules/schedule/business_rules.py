"""
Dynamic scheduling policies and pricing helpers.

This module loads technician-specific configuration from the database so the
core scheduling service can remain declarative. Admins can update policies via
dedicated endpoints without redeploying code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models.schedule_models import TechnicianPolicy, TechnicianServicePricing


@dataclass
class PolicyData:
    priority: int = 50
    max_daily: Optional[int] = None
    max_morning: Optional[int] = None
    max_afternoon: Optional[int] = None
    allow_public_booking: bool = True


default_policy = PolicyData()


async def load_technician_policies(
    db: AsyncSession,
    technician_ids: Iterable[str],
    location_uid: Optional[str],
) -> Dict[str, PolicyData]:
    technician_ids = [tid for tid in technician_ids if tid]
    if not technician_ids:
        return {}

    base_query = select(TechnicianPolicy).where(TechnicianPolicy.technician_id.in_(technician_ids))
    if location_uid:
        base_query = base_query.where(
            or_(
                TechnicianPolicy.location_id == location_uid,
                TechnicianPolicy.location_id.is_(None),
            )
        )
    else:
        base_query = base_query.where(TechnicianPolicy.location_id.is_(None))

    rows = (await db.execute(base_query)).scalars().all()

    location_specific: Dict[str, PolicyData] = {}
    global_defaults: Dict[str, PolicyData] = {}

    for row in rows:
        policy = PolicyData(
            priority=row.auto_assign_priority,
            max_daily=row.max_daily_online,
            max_morning=row.max_morning_online,
            max_afternoon=row.max_afternoon_online,
            allow_public_booking=row.allow_public_booking,
        )
        if row.location_id == location_uid and location_uid is not None:
            location_specific[row.technician_id] = policy
        elif row.location_id is None:
            global_defaults[row.technician_id] = policy

    resolved: Dict[str, PolicyData] = {}
    for technician_id in technician_ids:
        if technician_id in location_specific:
            resolved[technician_id] = location_specific[technician_id]
        elif technician_id in global_defaults:
            resolved[technician_id] = global_defaults[technician_id]

    return resolved


def get_period_quota(policy: PolicyData, period: Optional[str]) -> Optional[int]:
    if period == "morning":
        return policy.max_morning
    if period == "afternoon":
        return policy.max_afternoon
    return policy.max_daily


@dataclass(frozen=True)
class PricingRule:
    service_id: str
    technician_id: Optional[str]
    location_id: Optional[str]
    price: int


async def load_pricing_rules(
    db: AsyncSession,
    service_ids: Iterable[str],
    technician_ids: Iterable[str],
    location_uid: Optional[str],
) -> Dict[tuple[str, Optional[str], Optional[str]], PricingRule]:
    service_ids = [sid for sid in service_ids if sid]
    if not service_ids:
        return {}

    technicians = [tid for tid in technician_ids if tid]

    criteria = [
        TechnicianServicePricing.service_id.in_(service_ids),
        TechnicianServicePricing.is_active == True,  # noqa: E712
    ]

    if technicians:
        criteria.append(
            or_(
                TechnicianServicePricing.technician_id.in_(technicians),
                TechnicianServicePricing.technician_id.is_(None),
            )
        )
    else:
        criteria.append(TechnicianServicePricing.technician_id.is_(None))

    if location_uid:
        criteria.append(
            or_(
                TechnicianServicePricing.location_id == location_uid,
                TechnicianServicePricing.location_id.is_(None),
            )
        )
    else:
        criteria.append(TechnicianServicePricing.location_id.is_(None))

    rows = (await db.execute(select(TechnicianServicePricing).where(*criteria))).scalars().all()

    pricing_map: Dict[tuple[str, Optional[str], Optional[str]], PricingRule] = {}
    for row in rows:
        key = (row.service_id, row.technician_id, row.location_id)
        pricing_map[key] = PricingRule(
            service_id=row.service_id,
            technician_id=row.technician_id,
            location_id=row.location_id,
            price=row.price,
        )
    return pricing_map


def resolve_service_price(
    pricing_map: Dict[tuple[str, Optional[str], Optional[str]], PricingRule],
    service_id: str,
    technician_id: Optional[str],
    location_id: Optional[str],
) -> Optional[int]:
    candidates = (
        (service_id, technician_id, location_id),
        (service_id, technician_id, None),
        (service_id, None, location_id),
        (service_id, None, None),
    )
    for key in candidates:
        rule = pricing_map.get(key)
        if rule:
            return rule.price
    return None


def calculate_total_price(
    pricing_map: Dict[tuple[str, Optional[str], Optional[str]], PricingRule],
    service_ids: Iterable[str],
    technician_id: Optional[str],
    location_id: Optional[str],
) -> Optional[int]:
    total = 0
    has_any = False
    for service_id in service_ids:
        price = resolve_service_price(pricing_map, service_id, technician_id, location_id)
        if price is None:
            return None
        total += price
        has_any = True
    return total if has_any else None
