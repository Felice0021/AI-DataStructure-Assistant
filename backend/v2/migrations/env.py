from alembic import context
from backend.v2.core.config import get_settings
from backend.v2.core.logging import configure_logging
from backend.v2.db.base import Base
from backend.v2.db.session import build_engine
from backend.v2 import models  # noqa: F401 - register metadata for autogeneration

configure_logging()
config = context.config
target_metadata = Base.metadata


def run_migrations() -> None:
    # Tests may inject a connection to an isolated, newly-created test database.
    connection = config.attributes.get("connection")
    if context.is_offline_mode():
        context.configure(
            url=get_settings().database_url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
    elif connection is not None:
        migrate(connection)
    else:
        engine = build_engine(get_settings())
        try:
            with engine.connect() as connection:
                migrate(connection)
        finally:
            engine.dispose()


def migrate(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
