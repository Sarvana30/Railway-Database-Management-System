from app.database import SessionLocal


def get_db():
    """Provide a request-scoped session backed by the shared engine pool."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
