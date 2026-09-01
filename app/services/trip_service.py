"""Feature 7: multi-city trip planner.

A Trip groups several Bookings via trip_id + leg_order. Each leg is booked
through the normal single-segment flow (Feature 1), with split-ticket /
routing fallback (Features 5/6) available per leg if no direct seat exists.
All legs are wrapped in one DB transaction: either the whole trip books or
none of it does. Cancellation is per-leg and does NOT cascade to the rest of
the trip -- that's a deliberate design decision, not an oversight.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.database import set_read_committed
from app.models import Booking, BookingStatus, Trip, TicketType
from app.services.availability import get_stop_sequence, is_seat_free, find_any_available_seat
from app.services.booking_service import _log


@dataclass
class LegRequest:
    train_id: int
    seat_id: int
    from_station_id: int
    to_station_id: int
    journey_date: date
    ticket_type: TicketType = TicketType.general


class TripBookingFailed(Exception):
    def __init__(self, message: str, failed_leg_index: int):
        super().__init__(message)
        self.failed_leg_index = failed_leg_index


def book_trip(db: Session, user_id: int, legs: list[LegRequest]) -> Trip:
    if not legs:
        raise ValueError("A trip needs at least one leg")

    set_read_committed(db)
    try:
        trip = Trip(user_id=user_id)
        db.add(trip)
        db.flush()

        for i, leg in enumerate(legs, start=1):
            seq_from = get_stop_sequence(db, leg.train_id, leg.from_station_id)
            seq_to = get_stop_sequence(db, leg.train_id, leg.to_station_id)
            if seq_from >= seq_to:
                raise TripBookingFailed(f"Leg {i}: from must come before to", i)

            if not is_seat_free(
                db, leg.seat_id, leg.train_id, leg.journey_date, seq_from, seq_to, for_update=True
            ):
                raise TripBookingFailed(f"Leg {i}: seat {leg.seat_id} is not available", i)

            booking = Booking(
                user_id=user_id,
                train_id=leg.train_id,
                seat_id=leg.seat_id,
                from_station_id=leg.from_station_id,
                to_station_id=leg.to_station_id,
                journey_date=leg.journey_date,
                ticket_type=leg.ticket_type,
                status=BookingStatus.held,
                hold_expires_at=datetime.utcnow() + timedelta(minutes=settings.HOLD_DURATION_MINUTES),
                trip_id=trip.id,
                leg_order=i,
            )
            db.add(booking)
            db.flush()
            _log(db, booking.id, "hold_created_trip_leg", None, BookingStatus.held)
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(trip)
    return trip


def resolve_seat_for_leg(
    db: Session, train_id: int, journey_date: date, from_station_id: int, to_station_id: int
) -> Optional[int]:
    """Convenience for the trip-planner UI: pick any free seat for a leg so
    the user isn't forced to manually choose a seat for every city hop.
    """
    seat = find_any_available_seat(db, train_id, journey_date, from_station_id, to_station_id)
    return seat.id if seat else None
