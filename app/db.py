"""SQLAlchemy engine/session + declarative Base.

Dùng sync engine (psycopg3) cho đơn giản ở MVP; FastAPI inject session qua
dependency `get_db`. Có thể nâng cấp async sau nếu cần.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Base cho mọi ORM model."""


_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: 1 session/request, đảm bảo đóng."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
