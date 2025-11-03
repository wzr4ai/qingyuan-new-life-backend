# src/shared/models/schedule_models.py

from __future__ import annotations
import datetime
from sqlalchemy import Column, String, ForeignKey, DateTime, func, Boolean
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
