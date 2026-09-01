"""Concurrency-safe booking transactions (Features 1 & 4).

MySQL can't express "no overlapping station ranges on this seat" as a plain
unique constraint, so it's enforced in application code inside a
READ COMMITTED transaction that locks the seat's existing bookings with
SELECT ... FOR UPDATE before checking overlap. Two concurrent requests for
*overlapping* ranges on the same seat will serialize on that lock and only
one will see a free seat; two requests for *non-overlapping* ranges (e.g.
A->C and C->B) are both allowed to proceed, which is the point of Feature 4.
"""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.database import set_read_committed
from app.models import Booking, BookingStatus, RefundStatus, TicketType, AuditLog
from app.services.availability import get_stop_sequence, is_seat_free


class SeatUnavailable(Exception):
    pass


class BookingNotFound(Exception):
    pass


class NotYourBooking(Exception):
    pass


class HoldExpiredOrWrongState(Exception):
    pass


def _log(db: Session, booking_id: int, action: str, old_status, new_status):
    db.add(
        AuditLog(
            booking_id=booking_id,
            action=action,
            old_status=old_status.value if old_status else None,
            new_status=new_status.value if new_status else None,
        )
    )


def create_hold(
    db: Session,
    user_id: int,
    train_id: int,
    seat_id: int,
    from_station_id: int,
    to_station_id: int,
    journey_date: date,
    ticket_type: TicketType = TicketType.general,
) -> Booking:
    """Feature 1 + Feature 4: atomically check-and-hold one seat for one
    segment. Raises SeatUnavailable if the range overlaps an existing
    confirmed/held booking on that seat.
    """
    set_read_committed(db)
    try:
        seq_from = get_stop_sequence(db, train_id, from_station_id)
        seq_to = get_stop_sequence(db, train_id, to_station_id)
        if seq_from >= seq_to:
            raise ValueError("from_station must come before to_station on this train's route")

        if not is_seat_free(
            db, seat_id, train_id, journey_date, seq_from, seq_to, for_update=True
        ):
            raise SeatUnavailable(f"Seat {seat_id} is not free for this segment")

        booking = Booking(
            user_id=user_id,
            train_id=train_id,
            seat_id=seat_id,
            from_station_id=from_station_id,
            to_station_id=to_station_id,
            journey_date=journey_date,
            ticket_type=ticket_type,
            status=BookingStatus.held,
            hold_expires_at=datetime.utcnow() + timedelta(minutes=settings.HOLD_DURATION_MINUTES),
        )
        db.add(booking)
        db.flush()  # get booking.id before commit
        _log(db, booking.id, "hold_created", None, BookingStatus.held)
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(booking)
    return booking


def confirm_booking(db: Session, booking_id: int, user_id: int) -> Booking:
    """Flip held -> confirmed within the hold window. No payment step exists
    in this project, so this is the explicit action that stands in for it.
    """
    set_read_committed(db)
    expired = False
    try:
        booking = db.get(Booking, booking_id, with_for_update=True)
        if booking is None:
            raise BookingNotFound()
        if booking.user_id != user_id:
            raise NotYourBooking()
        if booking.status != BookingStatus.held:
            raise HoldExpiredOrWrongState(f"Booking is {booking.status}, not held")

        if booking.hold_expires_at is not None and booking.hold_expires_at < datetime.utcnow():
            booking.status = BookingStatus.cancelled
            _log(db, booking.id, "hold_expired", BookingStatus.held, BookingStatus.cancelled)
            expired = True
        else:
            old = booking.status
            booking.status = BookingStatus.confirmed
            _log(db, booking.id, "confirmed", old, booking.status)
        db.commit()
    except Exception:
        db.rollback()
        raise

    if expired:
        raise HoldExpiredOrWrongState("Hold expired")

    db.refresh(booking)
    return booking


def cancel_booking(db: Session, booking_id: int, user_id: int) -> Booking:
    """Feature 1: cancellation + refund. Since the availability query filters
    on status, setting status='cancelled' automatically frees the segment —
    no separate "release seat" step is needed. Refund is a status transition
    only; there's no real payment to reverse.
    """
    set_read_committed(db)
    try:
        booking = db.get(Booking, booking_id, with_for_update=True)
        if booking is None:
            raise BookingNotFound()
        if booking.user_id != user_id:
            raise NotYourBooking()
        if booking.status == BookingStatus.cancelled:
            db.commit()
            return booking  # idempotent

        old = booking.status
        booking.status = BookingStatus.cancelled
        if old == BookingStatus.confirmed:
            booking.refund_status = RefundStatus.refunded
        _log(db, booking.id, "cancelled", old, booking.status)
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(booking)
    return booking
