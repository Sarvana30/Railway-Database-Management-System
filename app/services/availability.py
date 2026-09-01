"""The one query everything depends on.

A seat is free for a new booking (from_station -> to_station) if no existing
`confirmed` or `held-and-not-expired` booking on that seat, for that train and
journey date, has an overlapping station range.

Overlap is computed on `stop_sequence` (the stop's position in the train's
route), not station ids directly, because "does A→C overlap C→B" only makes
sense once both ranges are expressed as positions along the *same* ordered
route.

Every other feature — search, seat map, booking, split-ticket detection,
graph routing, cancellation checks — calls into `segments_overlap` or
`get_seat_status_map`, rather than re-deriving this logic.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Route, Booking, BookingStatus, Seat, Coach


class InvalidStationForTrain(ValueError):
    """Raised when a station isn't on the given train's route at all."""


def get_stop_sequence(db: Session, train_id: int, station_id: int) -> int:
    seq = db.execute(
        select(Route.stop_sequence).where(
            Route.train_id == train_id, Route.station_id == station_id
        )
    ).scalar_one_or_none()
    if seq is None:
        raise InvalidStationForTrain(
            f"Station {station_id} is not on train {train_id}'s route"
        )
    return seq


def segments_overlap(seq_a_from: int, seq_a_to: int, seq_b_from: int, seq_b_to: int) -> bool:
    """True if [seq_a_from, seq_a_to) overlaps [seq_b_from, seq_b_to).

    Both ranges are assumed to already be direction-normalized (from < to),
    which the route's stop_sequence guarantees since routes are ordered.
    """
    return seq_a_from < seq_b_to and seq_b_from < seq_a_to


def _active_bookings_for_seat(
    db: Session, seat_id: int, train_id: int, journey_date: date, for_update: bool = False
):
    """Bookings that currently occupy (or may occupy, if held) part of the
    seat's schedule on this train/date. Expired holds are treated as free
    (lazy expiry) rather than deleted by a background job.
    """
    stmt = select(Booking).where(
        Booking.seat_id == seat_id,
        Booking.train_id == train_id,
        Booking.journey_date == journey_date,
        Booking.status.in_([BookingStatus.confirmed, BookingStatus.held]),
    )
    if for_update:
        stmt = stmt.with_for_update()
    bookings = db.execute(stmt).scalars().all()

    now = datetime.utcnow()
    active = []
    for b in bookings:
        if b.status == BookingStatus.held and b.hold_expires_at is not None and b.hold_expires_at < now:
            continue  # expired hold: treat as free
        active.append(b)
    return active


def is_seat_free(
    db: Session,
    seat_id: int,
    train_id: int,
    journey_date: date,
    seq_from: int,
    seq_to: int,
    for_update: bool = False,
) -> bool:
    """Core availability check for one seat and one requested range.

    `for_update` should be True only inside a booking transaction that has
    already set isolation level READ COMMITTED — it takes row locks on the
    seat's existing bookings so a concurrent request for an overlapping range
    can't slip through (see booking_service.create_hold).
    """
    active = _active_bookings_for_seat(db, seat_id, train_id, journey_date, for_update)
    for b in active:
        existing_seq_from = get_stop_sequence(db, train_id, b.from_station_id)
        existing_seq_to = get_stop_sequence(db, train_id, b.to_station_id)
        if segments_overlap(seq_from, seq_to, existing_seq_from, existing_seq_to):
            return False
    return True


def get_seats_for_train(db: Session, train_id: int) -> list[Seat]:
    return (
        db.execute(
            select(Seat)
            .join(Coach, Seat.coach_id == Coach.id)
            .where(Coach.train_id == train_id)
            .order_by(Coach.coach_number, Seat.row_number, Seat.position)
        )
        .scalars()
        .all()
    )


def get_seat_status_map(
    db: Session, train_id: int, journey_date: date, from_station_id: int, to_station_id: int
) -> list[dict]:
    """Powers the seat map (Feature 3): every seat on the train with a
    computed status for the requested segment.
    """
    seq_from = get_stop_sequence(db, train_id, from_station_id)
    seq_to = get_stop_sequence(db, train_id, to_station_id)
    if seq_from >= seq_to:
        raise ValueError("from_station must come before to_station on this train's route")

    seats = get_seats_for_train(db, train_id)
    result = []
    for seat in seats:
        active = _active_bookings_for_seat(db, seat.id, train_id, journey_date)
        status = "available"
        for b in active:
            existing_seq_from = get_stop_sequence(db, train_id, b.from_station_id)
            existing_seq_to = get_stop_sequence(db, train_id, b.to_station_id)
            if segments_overlap(seq_from, seq_to, existing_seq_from, existing_seq_to):
                status = "booked" if b.status == BookingStatus.confirmed else "held"
                break
        result.append(
            {
                "seat": seat,
                "status": status,
                "coach_number": seat.coach.coach_number,
                "coach_type": seat.coach.coach_type,
            }
        )
    return result


def find_adjacent_available_seats(status_rows: list[dict], group_size: int) -> Optional[list[dict]]:
    """Feature 3: scan seats (already sorted coach/row/position) for
    `group_size` consecutive available seats in the same coach, so a group
    can book seats together.
    """
    if group_size <= 1:
        for row in status_rows:
            if row["status"] == "available":
                return [row]
        return None

    run: list[dict] = []
    for row in status_rows:
        if row["status"] != "available":
            run = []
            continue
        if run and row["coach_number"] != run[-1]["coach_number"]:
            run = []
        run.append(row)
        if len(run) == group_size:
            return run
    return None


def find_any_available_seat(
    db: Session, train_id: int, journey_date: date, from_station_id: int, to_station_id: int
) -> Optional[Seat]:
    """Used by search / split-ticket / routing: does *any* seat have this
    segment free? Returns the first free seat, or None.
    """
    seq_from = get_stop_sequence(db, train_id, from_station_id)
    seq_to = get_stop_sequence(db, train_id, to_station_id)
    for seat in get_seats_for_train(db, train_id):
        if is_seat_free(db, seat.id, train_id, journey_date, seq_from, seq_to):
            return seat
    return None
