from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import JSON, BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Place(Base):
    __tablename__ = "place"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String)          # hospital | pharmacy
    name: Mapped[str] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    location = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    is_night: Mapped[bool] = mapped_column(Boolean, default=False)
    is_24h: Mapped[bool] = mapped_column(Boolean, default=False)
    hours: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String)
    source_id: Mapped[str | None] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
