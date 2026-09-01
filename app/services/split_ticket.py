"""Feature 5: split-ticket booking via mid-journey vacancy detection.

Reuses the Feature 4 segment-overlap query as a *search*, run twice: for a
direct A->B request with no single seat free the whole way, look for an
intermediate stop C such that some seat is free A->C and some seat (possibly
a different one) is free C->B — e.g. a passenger already booked on this seat
deboards at C, freeing it onward. Same train for both legs, so there's no
layover/timing concern (that's what distinguishes this from Feature 6).
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import set_read_committed
from app.models import Route, Booking, Trip, BookingStatus, TicketType
from app.services.availability import (
    get_stop_sequence,
    find_any_available_seat,
)
from app.services.booking_service import create_hold, SeatUnavailable, _log


@dataclass
class SplitPlan:
    via_station_id: int
    via_station_name: str
    seat_a_id: int  # from -> via
    seat_b_id: int  # via -> to


def find_split(
    db: Session, train_id: int, from_station_id: int, to_station_id: int, journey_date: date
) -> Optional[SplitPlan]:
    seq_from = get_stop_sequence(db, train_id, from_station_id)
    seq_to = get_stop_sequence(db, train_id, to_station_id)

    intermediate_stops = (
        db.execute(
            select(Route)
            .where(
                Route.train_id == train_id,
                Route.stop_sequence > seq_from,
                Route.stop_sequence < seq_to,
            )
            .order_by(Route.stop_sequence)
        )
        .scalars()
        .all()
    )

    for stop in intermediate_stops:
        seat_a = find_any_available_seat(db, train_id, journey_date, from_station_id, stop.station_id)
        if seat_a is None:
            continue
        seat_b = find_any_available_seat(db, train_id, journey_date, stop.station_id, to_station_id)
        if seat_b is None:
            continue
        return SplitPlan(
            via_station_id=stop.station_id,
            via_station_name=stop.station.name,
            seat_a_id=seat_a.id,
            seat_b_id=seat_b.id,
        )
    return None


def book_split(
    db: Session,
    user_id: int,
    train_id: int,
    plan: SplitPlan,
    from_station_id: int,
    to_station_id: int,
    journey_date: date,
    ticket_type: TicketType = TicketType.general,
) -> Trip:
    """Books both legs as one Trip in a single transaction: either both
    succeed or the whole split-booking fails (re-checks availability inside
    the transaction, since the plan above was computed outside one).
    """
    set_read_committed(db)
    try:
        trip = Trip(user_id=user_id)
        db.add(trip)
        db.flush()

        _hold_leg(
            db, user_id, train_id, plan.seat_a_id, from_station_id, plan.via_station_id,
            journey_date, ticket_type, trip.id, leg_order=1,
        )
        _hold_leg(
            db, user_id, train_id, plan.seat_b_id, plan.via_station_id, to_station_id,
            journey_date, ticket_type, trip.id, leg_order=2,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(trip)
    return trip


def _hold_leg(db, user_id, train_id, seat_id, from_id, to_id, journey_date, ticket_type, trip_id, leg_order):
    """Inline version of booking_service.create_hold that reuses the caller's
    open transaction instead of starting its own (create_hold opens its own
    `with db.begin()`, which can't be nested inside book_split's).
    """
    from app.services.availability import is_seat_free
    from datetime import datetime, timedelta
    from app.config import settings

    seq_from = get_stop_sequence(db, train_id, from_id)
    seq_to = get_stop_sequence(db, train_id, to_id)
    if not is_seat_free(db, seat_id, train_id, journey_date, seq_from, seq_to, for_update=True):
        raise SeatUnavailable(f"Seat {seat_id} became unavailable for leg {leg_order}")

    booking = Booking(
        user_id=user_id,
        train_id=train_id,
        seat_id=seat_id,
        from_station_id=from_id,
        to_station_id=to_id,
        journey_date=journey_date,
        ticket_type=ticket_type,
        status=BookingStatus.held,
        hold_expires_at=datetime.utcnow() + timedelta(minutes=settings.HOLD_DURATION_MINUTES),
        trip_id=trip_id,
        leg_order=leg_order,
    )
    db.add(booking)
    db.flush()
    _log(db, booking.id, "hold_created_split_leg", None, BookingStatus.held)
    return booking
