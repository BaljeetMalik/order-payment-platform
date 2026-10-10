from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, String , Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[UUID] = mapped_column(Uuid, unique=True, nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[UUID] = mapped_column(Uuid, unique=True, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())


