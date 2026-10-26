from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.v2.db.base import Base


class LoginLimit(Base):
    __tablename__ = "auth_login_limits"
    __table_args__ = (CheckConstraint("failures >= 0", name="failures_nonnegative"),)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    failures: Mapped[int] = mapped_column(Integer, server_default=text("0"))
