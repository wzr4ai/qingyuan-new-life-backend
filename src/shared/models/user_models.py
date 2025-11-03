# src/shared/models/users_models.py
from __future__ import annotations
import datetime
from sqlalchemy import (
    Column, 
    Integer, 
    String, 
    Table,
    Enum,
    Boolean,
    DateTime,
    ForeignKey,
    func,
    UniqueConstraint
    )

from sqlalchemy.orm import relationship, Mapped, mapped_column
from src.core.database import Base  # <-- 导入 Base
import ulid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schedule_models import Shift

# 定义技师和服务的 多对多 关联表
technician_service_link_table = Table(
    "technician_service_link",
    Base.metadata,
    Column("user_id", String(26), ForeignKey("users.uid"), primary_key=True),
    Column("service_id", String(26), ForeignKey("services.uid"), primary_key=True),
)

class SocialAccount(Base):
    __tablename__ = "social_accounts"

    uid: Mapped[str] = mapped_column(String(26), primary_key=True, default=lambda: str(ulid.new()), index=True)
    user_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.uid"), index=True)
    provider: Mapped[str] = mapped_column(String(50), index=True, comment="e.g., wechat, xiaohongshu")
    provider_id: Mapped[str] = mapped_column(String(128), index=True, comment="OpenID, XHS OpenID, etc.")
    
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # 关联回 User
    user: Mapped["User"] = relationship("User", back_populates="social_accounts")

    __table_args__ = (
        # 确保 (provider, provider_id) 的组合是唯一的
        UniqueConstraint("provider", "provider_id", name="uq_provider_provider_id"),
    )

class User(Base):
    __tablename__ = "users"

    uid: Mapped[str] = mapped_column(String(26), primary_key=True, unique=True, default=lambda: str(ulid.new()), index=True)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False, default="微信用户")
    avatar_url: Mapped[str] = mapped_column(String(255),nullable=True)
    phone: Mapped[str] = mapped_column(String(15), unique=True, nullable=True)
    role: Mapped[str] = Column(Enum("customer", "technician", "admin", name="user_role_enum"), default="customer")
    level: Mapped[int] = mapped_column(Integer, default=1)

    password_hash: Mapped[str] = mapped_column(String(255), nullable=True)
    
    # 关联的第三方社交账号
    social_accounts: Mapped[list["SocialAccount"]] = relationship(
        "SocialAccount", 
        back_populates="user", 
        cascade="all, delete-orphan"
    )
    
    # 技师与服务的 多对多 关系
    service: Mapped[list["Service"]] = relationship(
        secondary=technician_service_link_table,
        back_populates="technicians"
    )

    # 作为客户的预约关系
    appointments_as_customer: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        foreign_keys='Appointment.customer_id',
        back_populates="customer"
    )

    shifts: Mapped[list["Shift"]] = relationship(
        "Shift",
        back_populates="technician",
        cascade="all, delete-orphan",
        foreign_keys="Shift.technician_id"
    )
    
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
