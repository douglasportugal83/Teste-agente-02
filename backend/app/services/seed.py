"""Dados de referência idempotentes: papéis, fontes de dados e catálogo de ativos."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource, Role, Symbol
from app.models.enums import DataSourceKind, DataSourceStatus
from app.services.catalog import DEFAULT_ROLES, DEFAULT_SYMBOLS

SYNTHETIC_SOURCE = "Dados sintéticos"
MT5_SOURCE = "MetaTrader 5 (somente leitura)"


def seed_reference_data(db: Session) -> None:
    existing_roles = {r.name: r for r in db.scalars(select(Role))}
    for name, (description, permissions) in DEFAULT_ROLES.items():
        role = existing_roles.get(name)
        if role is None:
            db.add(Role(name=name, description=description, permissions=list(permissions)))
        else:
            role.permissions = list(permissions)

    sources = {s.name: s for s in db.scalars(select(DataSource))}
    synthetic = sources.get(SYNTHETIC_SOURCE)
    if synthetic is None:
        synthetic = DataSource(
            name=SYNTHETIC_SOURCE,
            kind=DataSourceKind.SYNTHETIC,
            status=DataSourceStatus.NOT_CONFIGURED,
            config={"note": "Gerador de candles sintéticos previsto para a Sprint 2."},
        )
        db.add(synthetic)
    if MT5_SOURCE not in sources:
        db.add(
            DataSource(
                name=MT5_SOURCE,
                kind=DataSourceKind.MT5,
                status=DataSourceStatus.NOT_CONFIGURED,
                config={"note": "Conector de leitura previsto para a Sprint 2."},
            )
        )
    db.flush()

    known = set(db.scalars(select(Symbol.name).where(Symbol.data_source_id == synthetic.id)))
    for name, description, category, base, quote, digits in DEFAULT_SYMBOLS:
        if name not in known:
            db.add(
                Symbol(
                    data_source_id=synthetic.id,
                    name=name,
                    canonical_name=name,
                    description=description,
                    category=category,
                    base_currency=base,
                    quote_currency=quote,
                    digits=digits,
                )
            )
    db.commit()
