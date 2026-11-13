"""Base declarativa e tipos compartilhados pelos modelos."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from sqlalchemy import JSON, DateTime, MetaData, Numeric, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONType = JSON().with_variant(JSONB(), "postgresql")
Money = Numeric(20, 8)


def utcnow() -> datetime:
    return datetime.now(UTC)


uuid_pk = Annotated[uuid.UUID, mapped_column(Uuid, primary_key=True, default=uuid.uuid4)]
created_at = Annotated[
    datetime, mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
]


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSONType, list[Any]: JSONType, Decimal: Money}


class TimestampMixin:
    created_at: Mapped[created_at]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
