from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from db import engine

router = APIRouter()


@router.get("/search")
def search_trains(from_station_id: int, to_station_id: int, journey_date: date):
    if from_station_id == to_station_id:
        raise HTTPException(status_code=400, detail="From and To stations must differ")

    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT t.id AS train_id, t.name AS train_name,
                       ts1.departsAt AS departure_time,
                       ts2.arrivesAt AS arrival_time
                FROM train t
                JOIN trainStop ts1 ON ts1.trainId = t.id AND ts1.stationId = :from_id
                JOIN trainStop ts2 ON ts2.trainId = t.id AND ts2.stationId = :to_id
                WHERE ts1.stopSequence < ts2.stopSequence
                ORDER BY ts1.departsAt
            """),
            {"from_id": from_station_id, "to_id": to_station_id},
        ).fetchall()

    return [
        {
            "train_id": r.train_id,
            "train_name": r.train_name,
            "departure_time": r.departure_time,
            "arrival_time": r.arrival_time,
        }
        for r in rows
    ]
