"""SQLAlchemy engine / session setup.

Booking transactions need explicit control over isolation level and row
locking (SELECT ... FOR UPDATE), so we use plain SQLAlchemy sessions rather
than hiding transactions behind an ORM-managed unit-of-work pattern.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# pool_pre_ping avoids "MySQL server has gone away" on idle connections.
# pool_size/max_overflow: cheap connection pooling worth doing even at this scale.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def set_read_committed(session):
    """InnoDB defaults to REPEATABLE READ, which can let a booking transaction
    see a stale snapshot of the seat's bookings mid-transaction. We want
    READ COMMITTED for booking/cancellation transactions, same as Postgres's
    default, so the overlap check sees the latest committed state.

    Request-scoped sessions (see dependencies.get_db) may already have an
    implicit transaction open from an earlier read in the same request (e.g.
    the current-user lookup), and MySQL refuses `SET TRANSACTION ISOLATION
    LEVEL` while a transaction is in progress. Roll that back first -- it's
    safe, since it only ever contained read-only SELECTs.

    Note: session.connection(execution_options=...) itself opens ("autobegins")
    the Session's transaction as a side effect, so callers must NOT also call
    `with session.begin():` afterwards -- use plain session.commit() /
    session.rollback() to close out the transaction this starts.
    """
    session.rollback()
    session.connection(execution_options={"isolation_level": "READ COMMITTED"})
