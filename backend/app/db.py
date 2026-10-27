from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or get_settings().database_url
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    return create_engine(url, **kw)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def add_missing_sqlite_columns(eng=None):
    """Dev-only: `create_all` makes new tables but never alters old ones, so add any new
    columns to an existing SQLite database. Postgres deployments use Alembic instead."""
    from sqlalchemy import inspect, text
    eng = eng or engine
    insp = inspect(eng)
    with eng.begin() as c:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {col["name"] for col in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(eng.dialect)}"
                default = getattr(col.default, "arg", None)
                if isinstance(default, bool):
                    ddl += f" NOT NULL DEFAULT {int(default)}"
                c.execute(text(ddl))


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
