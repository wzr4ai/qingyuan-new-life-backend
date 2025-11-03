# src/shared/models/resource_models.py

from __future__ import annotations
from sqlalchemy import Column, Integer, String, Enum, ForeignKey
from sqlalchemy.orm import relationship, Mapped, mapped_column
from src.core.database import Base
from .user_models import technician_service_link_table # 这个 import 保持不变
import ulid # 确保 ulid 已导入
from enum import Enum as PyEnum


class ResourceType(str, PyEnum):
    technician = "technician"
    room = "room"

class Location(Base):
    __tablename__ = "locations"
    
    uid: Mapped[str] = mapped_column(String(26), primary_key=True, default=lambda: str(ulid.new()), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=True)
    resources: Mapped[list["Resource"]] = relationship("Resource", back_populates="location")
    shifts: Mapped[list["Shift"]] = relationship(
        "Shift",
        back_populates="location",
        cascade="all, delete-orphan"
    )

class Resource(Base):
    __tablename__ = "resources"
    
    uid: Mapped[str] = mapped_column(String(26), primary_key=True, default=lambda: str(ulid.new()), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="例如: 1号推拿床, 2号针灸室")
    type: Mapped[str] = mapped_column(
        Enum(ResourceType, name="resource_type_enum"),
        nullable=False,
        default=ResourceType.room.value,
        server_default=ResourceType.room.value
    )
    location_id: Mapped[str] = mapped_column(String(26), ForeignKey("locations.uid"))

    location: Mapped["Location"] = relationship("Location", back_populates="resources")
    
class Service(Base):
    __tablename__ = "services"

    uid: Mapped[str] = mapped_column(String(26), primary_key=True, default=lambda: str(ulid.new()), index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    technician_operation_duration: Mapped[int] = mapped_column(Integer, comment="in minutes")
    room_operation_duration: Mapped[int] = mapped_column(Integer, comment="in minutes")
    buffer_time: Mapped[int] = mapped_column(Integer, default=15, comment="in minutes")

    technicians: Mapped[list["User"]] = relationship(
        "User", secondary=technician_service_link_table, back_populates="service"
    )
