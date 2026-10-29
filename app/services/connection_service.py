from datetime import date, timedelta
from decimal import Decimal

import networkx as nx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.fare_service import get_booking_fare
from app.services.train_run_service import TrainRunUnavailable, get_or_create_train_run


# A transfer needs time to change trains; very long waits are not useful suggestions.
MIN_TRANSFER = timedelta(minutes=45)
MAX_TRANSFER = timedelta(hours=12)
SUGGESTED_CLASS = "Sleeper"
MAX_SUGGESTIONS = 3


def _load_route_graph(db: Session) -> nx.MultiDiGraph:
    """Build a directed, train-labelled graph from the saved timetable templates."""
    service_days: dict[int, set[int]] = {}
    for row in db.execute(
        text("SELECT trainId, serviceDay FROM schedule_service_day")
    ).mappings():
        service_days.setdefault(row["trainId"], set()).add(row["serviceDay"])

    rows = db.execute(
        text(
            """
            SELECT
                train.id AS train_id,
                train.trainNumber AS train_number,
                train.name AS train_name,
                origin.stationId AS from_station_id,
                destination.stationId AS to_station_id,
                origin.stopSequence AS from_sequence,
                destination.stopSequence AS to_sequence,
                origin.departureDayOffset AS departure_day_offset,
                destination.arrivalDayOffset AS arrival_day_offset
            FROM train
            JOIN train_schedule_stop AS origin
                ON origin.trainId = train.id
            JOIN train_schedule_stop AS destination
                ON destination.trainId = train.id
            WHERE origin.stopSequence < destination.stopSequence
                AND origin.departureTime IS NOT NULL
                AND destination.arrivalTime IS NOT NULL
            """
        )
    ).mappings()

    graph = nx.MultiDiGraph()
    for row in rows:
        graph.add_edge(
            row["from_station_id"],
            row["to_station_id"],
            key=row["train_id"],
            train_id=row["train_id"],
            train_number=row["train_number"],
            train_name=row["train_name"],
            departure_day_offset=row["departure_day_offset"],
            arrival_day_offset=row["arrival_day_offset"],
            service_days=service_days.get(row["train_id"], set()),
        )
    return graph


def _run_leg(
    db: Session,
    edge: dict,
    from_station_id: int,
    to_station_id: int,
    departure_date: date,
    run_cache: dict[tuple[int, date], dict],
) -> dict | None:
    service_date = departure_date - timedelta(days=edge["departure_day_offset"])
    if service_date.isoweekday() not in edge["service_days"]:
        return None

    cache_key = (edge["train_id"], service_date)
    try:
        train_run = run_cache.get(cache_key)
        if train_run is None:
            train_run = get_or_create_train_run(db, edge["train_id"], service_date)
            run_cache[cache_key] = train_run
    except TrainRunUnavailable:
        return None

    times = db.execute(
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
                AND origin.stopSequence < destination.stopSequence
            """
        ),
        {
            "train_run_id": train_run["trainRunId"],
            "from_station_id": from_station_id,
            "to_station_id": to_station_id,
        },
    ).mappings().first()
    if times is None or times["departure_at"] is None or times["arrival_at"] is None:
        return None
    if times["arrival_at"] <= times["departure_at"]:
        return None

    return {
        "train_run_id": train_run["trainRunId"],
        "train_id": edge["train_id"],
        "train_number": edge["train_number"],
        "train_name": edge["train_name"],
        "departure_at": times["departure_at"],
        "arrival_at": times["arrival_at"],
        "departure_upcoming": bool(times["departure_upcoming"]),
    }


def find_connection_suggestions(
    db: Session,
    from_station_id: int,
    to_station_id: int,
    journey_date: date,
    stations: list,
) -> list[dict]:
    """Return up to three one-transfer timetable suggestions, ranked by estimated fare.

    These are informational connections only: the service does not check or reserve
    seats. Fare estimates use Sleeper because the current search form has no class field.
    """
    graph = _load_route_graph(db)
    if from_station_id not in graph or to_station_id not in graph:
        return []

    station_by_id = {station["id"]: station for station in stations}
    run_cache: dict[tuple[int, date], dict] = {}
    fare_cache: dict[tuple[int, int, int], Decimal | None] = {}
    suggestions = []

    # Each returned path is train-labelled because this is a MultiDiGraph;
    # requiring exactly two edges means exactly one transfer.
    for path in nx.all_simple_edge_paths(
        graph, from_station_id, to_station_id, cutoff=2
    ):
        if len(path) != 2:
            continue
        first_from, interchange_id, first_train_id = path[0]
        second_from, candidate_destination, second_train_id = path[1]
        first_edge = graph.get_edge_data(first_from, interchange_id, first_train_id)
        second_edge = graph.get_edge_data(
            second_from, candidate_destination, second_train_id
        )
        if interchange_id in (from_station_id, to_station_id):
            continue
        if second_from != interchange_id or candidate_destination != to_station_id:
            continue
        first_service_date = journey_date - timedelta(
            days=first_edge["departure_day_offset"]
        )
        if first_service_date.isoweekday() not in first_edge["service_days"]:
            continue

        first_leg = _run_leg(
            db,
            first_edge,
            from_station_id,
            interchange_id,
            journey_date,
            run_cache,
        )
        if first_leg is None or not first_leg["departure_upcoming"]:
            continue

        if second_edge["train_id"] == first_edge["train_id"]:
            continue

        earliest_departure = first_leg["arrival_at"] + MIN_TRANSFER
        latest_departure = first_leg["arrival_at"] + MAX_TRANSFER
        second_leg = None
        departure_day = earliest_departure.date()
        while departure_day <= latest_departure.date():
            second_leg = _run_leg(
                db,
                second_edge,
                interchange_id,
                to_station_id,
                departure_day,
                run_cache,
            )
            if (
                second_leg is not None
                and earliest_departure <= second_leg["departure_at"] <= latest_departure
            ):
                break
            second_leg = None
            departure_day += timedelta(days=1)

        if second_leg is None:
            continue

        first_fare_key = (
            first_leg["train_run_id"], from_station_id, interchange_id
        )
        second_fare_key = (
            second_leg["train_run_id"], interchange_id, to_station_id
        )
        for key in (first_fare_key, second_fare_key):
            if key not in fare_cache:
                fare_result = get_booking_fare(
                    db,
                    key[0],
                    key[1],
                    key[2],
                    SUGGESTED_CLASS,
                )
                fare_cache[key] = (
                    Decimal(fare_result["total_fare"])
                    if fare_result is not None
                    else None
                )
        first_fare = fare_cache[first_fare_key]
        second_fare = fare_cache[second_fare_key]
        if first_fare is None or second_fare is None:
            continue

        interchange = station_by_id.get(interchange_id)
        if interchange is None:
            continue
        suggestions.append(
            {
                "interchange": interchange,
                "first_leg": first_leg,
                "second_leg": second_leg,
                "transfer_wait": second_leg["departure_at"] - first_leg["arrival_at"],
                "total_duration": second_leg["arrival_at"] - first_leg["departure_at"],
                "estimated_fare": first_fare + second_fare,
                "fare_class": SUGGESTED_CLASS,
            }
        )

    db.commit()
    # Distinct train combinations can yield the same interchange and schedule.
    suggestions.sort(
        key=lambda item: (
            item["estimated_fare"],
            item["total_duration"],
            item["first_leg"]["departure_at"],
        )
    )
    unique = []
    seen = set()
    for item in suggestions:
        identity = (
            item["first_leg"]["train_run_id"],
            item["second_leg"]["train_run_id"],
            item["interchange"]["id"],
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(item)
        if len(unique) == MAX_SUGGESTIONS:
            break
    return unique
