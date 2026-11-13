"""Integração: as migrations Alembic reproduzem exatamente os modelos (exige PostgreSQL)."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.db.base import Base
from tests.conftest import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not TEST_DATABASE_URL.startswith("postgresql"),
        reason="defina TEST_DATABASE_URL apontando para um PostgreSQL de teste",
    ),
]


def test_upgrade_matches_models_and_downgrade_is_clean() -> None:
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    try:
        command.upgrade(config, "head")
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            assert tables == set(Base.metadata.tables) | {"alembic_version"}
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
            assert diff == [], f"modelos e migrations divergem: {diff}"

            # Garantias de "somente simulação" e "somente leitura" impostas pelo banco.
            checks = {
                row[0]
                for row in conn.execute(
                    text("SELECT conname FROM pg_constraint WHERE contype = 'c'")
                )
            }
            assert "ck_simulation_accounts_virtual_only" in checks
            assert "ck_data_sources_read_only_enforced" in checks

        command.downgrade(config, "base")
        with engine.connect() as conn:
            assert set(inspect(conn).get_table_names()) == {"alembic_version"}
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        engine.dispose()
