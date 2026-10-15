from fastapi import APIRouter
from sqlalchemy import text

from db import engine

router = APIRouter()


@router.get("/stations")
def list_stations():
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name, city, state FROM station ORDER BY name")
        ).fetchall()

    return [{"id": r.id, "name": r.name, "city": r.city, "state": r.state} for r in rows]
