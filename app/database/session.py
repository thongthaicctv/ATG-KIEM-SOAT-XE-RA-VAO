from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker

from app.core.config import settings


def make_engine(url: str = settings.database_url):
    engine = create_engine(url, future=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
    return engine


engine = make_engine()
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, expire_on_commit=False))

