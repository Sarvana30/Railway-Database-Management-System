from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.connection_service import find_connection_suggestions
from app.services.train_run_service import (
    TrainRunUnavailable,
    get_or_create_train_run,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


def get_stations(db: Session):
    return db.execute(
        text(
            """
            SELECT id, name, city, state
            FROM station
            ORDER BY city, name
            """
        )
    ).mappings().all()


def render_search_page(
    request,
    stations,
    error=None,
    from_station_id=None,
    to_station_id=None,
    journey_date=None,
    min_journey_date=None,
    max_journey_date=None,
):
    return templates.TemplateResponse(
    request=request,
    name="search.html",
    context={
        "stations": stations,
        "error": error,
        "from_station_id": from_station_id,
        "to_station_id": to_station_id,
        "journey_date": journey_date,
        "min_journey_date": min_journey_date or date.today(),
        "max_journey_date": max_journey_date or date.today() + timedelta(days=120),
    },
)


@router.get("/search", response_class=HTMLResponse)
def search_trains(
    request: Request,
    from_station_id: int | None = None,
    to_station_id: int | None = None,
    journey_date: date | None = None,
    db: Session = Depends(get_db),
):
    stations = get_stations(db)
    min_journey_date = date.today()
    max_journey_date = date.today() + timedelta(days=120)

    if from_station_id is None and to_station_id is None and journey_date is None:
        return render_search_page(
            request,
            stations,
            min_journey_date=min_journey_date,
            max_journey_date=max_journey_date,
        )

    if from_station_id is None or to_station_id is None or journey_date is None:
        return render_search_page(
            request,
            stations,
            error="Choose an origin, destination, and travel date.",
            from_station_id=from_station_id,
            to_station_id=to_station_id,
            journey_date=journey_date,
            min_journey_date=min_journey_date,
            max_journey_date=max_journey_date,
        )

    if journey_date < min_journey_date:
        return render_search_page(
            request,
            stations,
            error="Choose today or a future travel date.",
            from_station_id=from_station_id,
            to_station_id=to_station_id,
            journey_date=journey_date,
            min_journey_date=min_journey_date,
            max_journey_date=max_journey_date,
        )

    if journey_date > max_journey_date:
        return render_search_page(
            request,
            stations,
            error="Choose a travel date within the next 120 days.",
            from_station_id=from_station_id,
            to_station_id=to_station_id,
            journey_date=journey_date,
            min_journey_date=min_journey_date,
            max_journey_date=max_journey_date,
        )

    if from_station_id == to_station_id:
        return render_search_page(
            request,
            stations,
            error="Origin and destination must be different.",
            from_station_id=from_station_id,
            to_station_id=to_station_id,
            journey_date=journey_date,
            min_journey_date=min_journey_date,
            max_journey_date=max_journey_date,
        )

    rows = db.execute(
        text(
            """
            SELECT
                t.id AS train_id,
                t.trainNumber AS train_number,
                t.name AS train_name,
                service_day.serviceDay AS service_day,
                origin.departureDayOffset AS departure_day_offset
            FROM train AS t
            JOIN schedule_service_day AS service_day
                ON service_day.trainId = t.id
            JOIN train_schedule_stop AS origin
                ON origin.trainId = t.id
            JOIN train_schedule_stop AS destination
                ON destination.trainId = t.id
            WHERE origin.stationId = :from_station_id
                AND destination.stationId = :to_station_id
                AND origin.stopSequence < destination.stopSequence
                AND origin.departureTime IS NOT NULL
            ORDER BY service_day.trainId, service_day.serviceDay
            """
        ),
        {
            "from_station_id": from_station_id,
            "to_station_id": to_station_id,
        },
    ).mappings().all()

    results = []

    for row in rows:
        service_date = journey_date - timedelta(
            days=row["departure_day_offset"]
        )

        if row["service_day"] != service_date.isoweekday():
            continue

        try:
            train_run = get_or_create_train_run(
                db,
                row["train_id"],
                service_date,
            )
        except TrainRunUnavailable:
            continue

        run_times = db.execute(
            text(
                """
                SELECT
                    origin.departureAt AS departure_at,
                    destination.arrivalAt AS arrival_at,
                    origin.departureAt > CURRENT_TIMESTAMP AS departure_upcoming
                FROM trainStop AS origin
                JOIN trainStop AS destination
                    ON destination.trainRunId = origin.trainRunId
                WHERE origin.trainRunId = :train_run_id
                    AND origin.stationId = :from_station_id
                    AND destination.stationId = :to_station_id
                """
            ),
            {
                "train_run_id": train_run["trainRunId"],
                "from_station_id": from_station_id,
                "to_station_id": to_station_id,
            },
        ).mappings().first()

        if run_times is None:
            continue

        if not run_times["departure_upcoming"]:
            continue

        departure_at = run_times["departure_at"]
        arrival_at = run_times["arrival_at"]

        if departure_at is None or arrival_at is None or arrival_at <= departure_at:
            continue

        results.append(
            {
                "train_run_id": train_run["trainRunId"],
                "train_id": row["train_id"],
                "train_number": row["train_number"],
                "train_name": row["train_name"],
                "service_date": service_date,
                "departure_at": departure_at,
                "arrival_at": arrival_at,
            }
        )

    db.commit()
    results.sort(key=lambda result: result["departure_at"])
    connection_suggestions = find_connection_suggestions(
        db,
        from_station_id,
        to_station_id,
        journey_date,
        stations,
    )

    return templates.TemplateResponse(
    request=request,
    name="search_results.html",
    context={
        "results": results,
        "journey_date": journey_date,
        "connection_suggestions": connection_suggestions,
        "from_station": next(
            (station for station in stations if station["id"] == from_station_id),
            None,
        ),
        "to_station": next(
            (station for station in stations if station["id"] == to_station_id),
            None,
        ),
    },
)
