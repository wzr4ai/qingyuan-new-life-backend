# src/shared/models/schedule_models.py

from __future__ import annotations
import datetime
from sqlalchemy import Column, String, ForeignKey, DateTime, func, Boolean, Integer, UniqueConstraint
from sqlalchemy.orm import relationship, Mapped, mapped_column
from src.core.database import Base
import ulid

class Shift(Base):
    """
    V6 新增：排班表
    用于指定一个技师在什么时间、什么地点工作
    """
    __tablename__ = "shifts"

    uid: Mapped[str] = mapped_column(String(26), primary_key=True, default=lambda: str(ulid.new()), index=True)
    
    # 关联到 User (技师)
    technician_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.uid"), index=True)
    
    # 关联到 Location (地点)
    location_id: Mapped[str] = mapped_column(String(26), ForeignKey("locations.uid"), index=True)

    start_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="排班开始时间")
    end_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="排班结束时间")
    period: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="班次时段标签 (morning/afternoon)")

    created_by_user_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("users.uid"),
        nullable=True,
        comment="创建排班的用户"
    )
    locked_by_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="0",
        default=False,
        comment="是否由管理员锁定，技师不可修改"
    )
    is_cancelled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="0",
        default=False,
        comment="排班是否取消"
    )
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="取消时间"
    )
    cancelled_by_user_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("users.uid"),
        nullable=True,
        comment="取消排班的管理员"
    )

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=func.now()
    )

    # --- Relationships (使用字符串前向引用) ---
    
    # 关联到技师 (User)
    technician: Mapped["User"] = relationship(
        "User", 
        back_populates="shifts",
        foreign_keys=[technician_id]
    )
    created_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[created_by_user_id],
        lazy="joined"
    )
    cancelled_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[cancelled_by_user_id],
        lazy="joined"
    )
    
    # 关联到地点 (Location)
    location: Mapped["Location"] = relationship(
        "Location", 
        back_populates="shifts"
    )


class TechnicianPolicy(Base):
    """
    管理后台可配置的技师预约策略，用于控制各时段的在线放号数量与排序优先级。
    """
    __tablename__ = "technician_policies"
    __table_args__ = (
        UniqueConstraint("technician_id", "location_id", name="uq_technician_policy"),
    )

    uid: Mapped[str] = mapped_column(String(26), primary_key=True, default=lambda: str(ulid.new()), index=True)
    technician_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.uid"), index=True, nullable=False)
    location_id: Mapped[str | None] = mapped_column(String(26), ForeignKey("locations.uid"), nullable=True, index=True)

    max_daily_online: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="整天可通过在线预约的最大数量")
    max_morning_online: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="上午可通过在线预约的最大数量")
    max_afternoon_online: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="下午可通过在线预约的最大数量")
    auto_assign_priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False, comment="自动分配优先级，数值越小越优先")
    allow_public_booking: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="1", comment="是否允许客户在线预约")

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    technician: Mapped["User"] = relationship("User", foreign_keys=[technician_id])
    location: Mapped["Location"] = relationship("Location")


class TechnicianServicePricing(Base):
    """
    管理后台可配置的技师/地点/服务定价策略。
    """
    __tablename__ = "technician_service_pricing"
    __table_args__ = (
        UniqueConstraint("service_id", "technician_id", "location_id", name="uq_technician_service_pricing"),
    )

    uid: Mapped[str] = mapped_column(String(26), primary_key=True, default=lambda: str(ulid.new()), index=True)
    service_id: Mapped[str] = mapped_column(String(26), ForeignKey("services.uid"), nullable=False, index=True)
    technician_id: Mapped[str | None] = mapped_column(String(26), ForeignKey("users.uid"), nullable=True, index=True)
    location_id: Mapped[str | None] = mapped_column(String(26), ForeignKey("locations.uid"), nullable=True, index=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="1")

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    service: Mapped["Service"] = relationship("Service")
    technician: Mapped["User"] = relationship("User", foreign_keys=[technician_id])
    location: Mapped["Location"] = relationship("Location")
