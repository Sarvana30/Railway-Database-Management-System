"""Feature 6: graph-based fallback routing, direct + 1 transfer only.

If A->B has no direct train with a free seat, look at every train departing
A; for each, walk its remaining stops as candidate transfer stations C. If a
direct C->B train exists (with a free seat, and departing at least
MIN_LAYOVER_MINUTES after the first train arrives at C), offer the
connection. We deliberately don't implement general multi-hop pathfinding
(Dijkstra/BFS over arbitrary depth) -- that's out of scope for the timeline.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Route, Train
from app.services.availability import find_any_available_seat


@dataclass
class DirectTrain:
    train_id: int
    train_name: str
    train_number: str
    departure_time: str
    arrival_time: str


@dataclass
class Connection:
    first: DirectTrain
    via_station_id: int
    via_station_name: str
    second: DirectTrain


def _time_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def find_direct_trains(
    db: Session, from_station_id: int, to_station_id: int, journey_date: Optional[date] = None,
    require_seat: bool = True,
) -> list[DirectTrain]:
    """Feature 1 search: trains whose route covers from->to in order."""
    from_stops = db.execute(
        select(Route).where(Route.station_id == from_station_id)
    ).scalars().all()

    results = []
    for stop in from_stops:
        to_stop = db.execute(
            select(Route).where(
                Route.train_id == stop.train_id,
                Route.station_id == to_station_id,
                Route.stop_sequence > stop.stop_sequence,
            )
        ).scalar_one_or_none()
        if to_stop is None:
            continue
        if require_seat and journey_date is not None:
            seat = find_any_available_seat(db, stop.train_id, journey_date, from_station_id, to_station_id)
            if seat is None:
                continue
        train = db.get(Train, stop.train_id)
        results.append(
            DirectTrain(
                train_id=train.id,
                train_name=train.name,
                train_number=train.number,
                departure_time=stop.departure_time,
                arrival_time=to_stop.arrival_time,
            )
        )
    return results


def find_connections(
    db: Session, from_station_id: int, to_station_id: int, journey_date: date
) -> list[Connection]:
    """1-hop fallback: only called when find_direct_trains returns nothing."""
    connections: list[Connection] = []

    from_stops = db.execute(
        select(Route).where(Route.station_id == from_station_id)
    ).scalars().all()

    seen_via: set[int] = set()

    for stop in from_stops:
        later_stops = db.execute(
            select(Route)
            .where(Route.train_id == stop.train_id, Route.stop_sequence > stop.stop_sequence)
            .order_by(Route.stop_sequence)
        ).scalars().all()

        for candidate_c in later_stops:
            via_id = candidate_c.station_id
            if via_id in seen_via or via_id == to_station_id:
                continue

            seat1 = find_any_available_seat(db, stop.train_id, journey_date, from_station_id, via_id)
            if seat1 is None:
                continue

            second_legs = find_direct_trains(db, via_id, to_station_id, journey_date)
            if not second_legs:
                continue

            arrival_minutes = _time_to_minutes(candidate_c.arrival_time or candidate_c.departure_time)
            for leg2 in second_legs:
                dep_minutes = _time_to_minutes(leg2.departure_time)
                layover = dep_minutes - arrival_minutes
                if layover < settings.MIN_LAYOVER_MINUTES:
                    continue

                train1 = db.get(Train, stop.train_id)
                connections.append(
                    Connection(
                        first=DirectTrain(
                            train_id=train1.id,
                            train_name=train1.name,
                            train_number=train1.number,
                            departure_time=stop.departure_time,
                            arrival_time=candidate_c.arrival_time,
                        ),
                        via_station_id=via_id,
                        via_station_name=candidate_c.station.name,
                        second=leg2,
                    )
                )
                seen_via.add(via_id)
                break  # nearest valid connection at this via station is enough
            if via_id in seen_via:
                break  # nearest reachable C for this first train found; stop walking further stops

    # "nearest" C = fewest stops from A, which is already the order later_stops/from_stops are visited in
    return connections
