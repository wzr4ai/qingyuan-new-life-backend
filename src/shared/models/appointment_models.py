# src/shared/models/appointment_models.py

from __future__ import annotations
import datetime
from sqlalchemy import Column, String, Integer, Enum, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship, Mapped, mapped_column
from src.core.database import Base
import ulid

class AppointmentTechnicianLink(Base):
    """
    V4 新增表：专门用于记录预约对技师(User)时间的占用
    """
    __tablename__ = "appointment_technician_links"

    uid: Mapped[str] = mapped_column(String(26), primary_key=True, default=lambda: str(ulid.new()), index=True)
    appointment_id: Mapped[str] = mapped_column(String(26), ForeignKey("appointments.uid"))
    technician_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.uid")) # <-- 关联到 User 表
    
    start_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    appointment: Mapped["Appointment"] = relationship("Appointment", back_populates="technician_link")
    technician: Mapped["User"] = relationship("User") # 单向关联到 User

# 预约模型
class Appointment(Base):
    __tablename__ = "appointments"

    uid: Mapped[str] = mapped_column(String(26), primary_key=True, default=lambda: str(ulid.new()), index=True)
    customer_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.uid"))
    service_id: Mapped[str] = mapped_column(String(26), ForeignKey("services.uid"))
    location_id: Mapped[str] = mapped_column(String(26), ForeignKey("locations.uid"))
    status: Mapped[str] = mapped_column(Enum("confirmed", "completed", "cancelled", name="appointment_status_enum"), default="confirmed")
    start_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    customer: Mapped["User"] = relationship("User", foreign_keys=[customer_id], back_populates="appointments_as_customer")
    service: Mapped["Service"] = relationship("Service")
    location: Mapped["Location"] = relationship("Location")
    
    resources_link: Mapped[list["AppointmentResourceLink"]] = relationship(
        "AppointmentResourceLink", back_populates="appointment", cascade="all, delete-orphan"
    )

    # --- 新增 V4 关联 ---
    technician_link: Mapped["AppointmentTechnicianLink"] = relationship(
        "AppointmentTechnicianLink", 
        back_populates="appointment", 
        cascade="all, delete-orphan",
        uselist=False # 一个预约只关联一个技师
    )

# 预约与资源的关联模型
class AppointmentResourceLink(Base):
    """
    V4 语义变更：此表现在只用于记录物理资源 (房间/床位) 的占用
    """
    __tablename__ = "appointment_resource_links"

    uid: Mapped[str] = mapped_column(String(26), primary_key=True, default=lambda: str(ulid.new()), index=True)
    appointment_id: Mapped[str] = mapped_column(String(26), ForeignKey("appointments.uid"))
    resource_id: Mapped[str] = mapped_column(String(26), ForeignKey("resources.uid")) # 关联到 Resource (床位)
    
    start_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    appointment: Mapped["Appointment"] = relationship("Appointment", back_populates="resources_link")
    resource: Mapped["Resource"] = relationship("Resource") # 单向关联到 Resource