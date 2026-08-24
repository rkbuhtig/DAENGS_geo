"""Alembic 실행 환경.

DB URL 은 앱과 **같은 곳**(`app.core.config.settings`)에서 온다. 마이그레이션이 앱과
다른 DB 를 보는 사고는 설정이 두 벌일 때 생긴다.

드라이버만 바꿔 낀다. 앱은 asyncpg 로 돌지만 마이그레이션은 동기 psycopg 로 돌린다 —
DDL 은 배포 시 한 번 순차 실행되는 것이라 async 로 얻을 게 없고, 동기 쪽이 원본 SQL 을
그대로 흘려보내기 쉽다.
"""

from logging.config import fileConfig

from sqlalchemy import create_engine

import app.geo.models  # noqa: F401  모델을 import 해야 Base.metadata 가 채워진다
from alembic import context
from app.core.config import settings
from app.core.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def migration_url() -> str:
    return settings.database_url.replace("+asyncpg", "+psycopg")


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(migration_url(), poolclass=None)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
