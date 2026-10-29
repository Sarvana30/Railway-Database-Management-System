from datetime import date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session


class TrainRunUnavailable(Exception):
    pass


def combine_service_time(
    service_date: date,
    day_offset: int,
    time_value: time | timedelta,
) -> datetime:
    service_datetime = datetime.combine(
        service_date + timedelta(days=day_offset),
        time.min,
    )

    if isinstance(time_value, timedelta):
        return service_datetime + time_value

    return datetime.combine(
        service_date + timedelta(days=day_offset),
        time_value,
    )


def get_or_create_train_run(
    db: Session,
    train_id: int,
    service_date: date,
) -> dict:
    train_exists = db.execute(
        text("SELECT id FROM train WHERE id = :train_id FOR UPDATE"),
        {"train_id": train_id},
    ).scalar_one_or_none()
    if train_exists is None:
        raise TrainRunUnavailable("Train does not exist.")

    service_day = db.execute(
        text(
            """
            SELECT serviceDay
            FROM schedule_service_day
            WHERE trainId = :train_id
              AND serviceDay = :service_day
            """
        ),
        {
            "train_id": train_id,
            "service_day": service_date.isoweekday(),
        },
    ).scalar_one_or_none()

    if service_day is None:
        raise TrainRunUnavailable("Train does not operate on this date.")

    existing_run = db.execute(
        text(
            """
            SELECT trainRunId, trainId, serviceDate, departureAt, status
            FROM train_run
            WHERE trainId = :train_id
              AND serviceDate = :service_date
            """
        ),
        {
            "train_id": train_id,
            "service_date": service_date,
        },
    ).mappings().first()

    if existing_run is not None:
        if existing_run["status"] != "SCHEDULED":
            raise TrainRunUnavailable("Train run is not available.")

        return dict(existing_run)

    stops = db.execute(
        text(
            """
            SELECT
                stationId,
                stopSequence,
                arrivalTime,
                departureTime,
                arrivalDayOffset,
                departureDayOffset
            FROM train_schedule_stop
            WHERE trainId = :train_id
            ORDER BY stopSequence
            """
        ),
        {"train_id": train_id},
    ).mappings().all()

    if not stops:
        raise TrainRunUnavailable("Train route has no stops.")

    if stops[0]["departureTime"] is None:
        raise TrainRunUnavailable("The first stop has no departure time.")

    departure_at = combine_service_time(
        service_date,
        stops[0]["departureDayOffset"],
        stops[0]["departureTime"],
    )

    previous_time = None
    run_stops = []

    for stop in stops:
        arrival_at = None
        stop_departure_at = None

        if stop["arrivalTime"] is not None:
            arrival_at = combine_service_time(
                service_date,
                stop["arrivalDayOffset"],
                stop["arrivalTime"],
            )
            if previous_time is not None and arrival_at < previous_time:
                raise TrainRunUnavailable("Schedule stop times are out of order.")
            previous_time = arrival_at

        if stop["departureTime"] is not None:
            stop_departure_at = combine_service_time(
                service_date,
                stop["departureDayOffset"],
                stop["departureTime"],
            )
            if previous_time is not None and stop_departure_at < previous_time:
                raise TrainRunUnavailable("Schedule stop times are out of order.")
            previous_time = stop_departure_at

        run_stops.append(
            {
                "station_id": stop["stationId"],
                "stop_sequence": stop["stopSequence"],
                "arrival_at": arrival_at,
                "departure_at": stop_departure_at,
            }
        )

    result = db.execute(
        text(
            """
            INSERT INTO train_run (trainId, serviceDate, departureAt)
            VALUES (:train_id, :service_date, :departure_at)
            """
        ),
        {
            "train_id": train_id,
            "service_date": service_date,
            "departure_at": departure_at,
        },
    )

    train_run_id = result.lastrowid

    for stop in run_stops:
        db.execute(
            text(
                """
                INSERT INTO trainStop (
                    trainRunId,
                    trainId,
                    stationId,
                    stopSequence,
                    arrivalAt,
                    departureAt
                )
                VALUES (
                    :train_run_id,
                    :train_id,
                    :station_id,
                    :stop_sequence,
                    :arrival_at,
                    :departure_at
                )
                """
            ),
            {
                "train_run_id": train_run_id,
                "train_id": train_id,
                **stop,
            },
        )

    db.flush()

    return {
        "trainRunId": train_run_id,
        "trainId": train_id,
        "serviceDate": service_date,
        "departureAt": departure_at,
        "status": "SCHEDULED",
    }
