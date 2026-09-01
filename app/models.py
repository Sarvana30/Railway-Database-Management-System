"""SQLAlchemy models.

This mirrors the schema in the project plan, with one addition: `journey_date`
on Booking. Trains run on a schedule every day, and the plan's segment-overlap
rule ("no two bookings on the same seat with overlapping station ranges") only
makes sense *per calendar day* of that train's run — without a date, a booking
made today would block the seat on every future date forever. So `journey_date`
is threaded through Booking and every availability query.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, ForeignKey, DateTime, Date, Enum, UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from app.database import Base


class TicketType(str, enum.Enum):
    general = "general"
    tatkal = "tatkal"
    ladies = "ladies"
    senior = "senior"


class BookingStatus(str, enum.Enum):
    held = "held"
    confirmed = "confirmed"
    cancelled = "cancelled"


class RefundStatus(str, enum.Enum):
    none = "none"
    refunded = "refunded"


class SeatPosition(str, enum.Enum):
    window = "window"
    middle = "middle"
    aisle = "aisle"


class Station(Base):
    __tablename__ = "stations"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    code = Column(String(10), nullable=False, unique=True)


class Train(Base):
    __tablename__ = "trains"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    number = Column(String(20), nullable=False, unique=True)
    total_seats = Column(Integer, nullable=False, default=0)

    routes = relationship("Route", back_populates="train", order_by="Route.stop_sequence")
    coaches = relationship("Coach", back_populates="train")


class Route(Base):
    """One stop of a train's ordered itinerary."""
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True)
    train_id = Column(Integer, ForeignKey("trains.id"), nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    stop_sequence = Column(Integer, nullable=False)  # 1, 2, 3... in travel order
    arrival_time = Column(String(5), nullable=True)   # "HH:MM", null for origin
    departure_time = Column(String(5), nullable=True)  # "HH:MM", null for terminus

    train = relationship("Train", back_populates="routes")
    station = relationship("Station")

    __table_args__ = (
        UniqueConstraint("train_id", "stop_sequence", name="uq_train_stop_sequence"),
        UniqueConstraint("train_id", "station_id", name="uq_train_station_once"),
        Index("ix_routes_train_station", "train_id", "station_id"),
    )


class Coach(Base):
    __tablename__ = "coaches"

    id = Column(Integer, primary_key=True)
    train_id = Column(Integer, ForeignKey("trains.id"), nullable=False)
    coach_number = Column(String(10), nullable=False)
    coach_type = Column(String(30), nullable=False, default="sleeper")

    train = relationship("Train", back_populates="coaches")
    seats = relationship("Seat", back_populates="coach", order_by="Seat.row_number")

    __table_args__ = (
        UniqueConstraint("train_id", "coach_number", name="uq_train_coach_number"),
    )


class Seat(Base):
    __tablename__ = "seats"

    id = Column(Integer, primary_key=True)
    coach_id = Column(Integer, ForeignKey("coaches.id"), nullable=False)
    seat_number = Column(String(10), nullable=False)
    row_number = Column(Integer, nullable=False)
    position = Column(Enum(SeatPosition), nullable=False, default=SeatPosition.middle)

    coach = relationship("Coach", back_populates="seats")

    __table_args__ = (
        UniqueConstraint("coach_id", "seat_number", name="uq_coach_seat_number"),
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Trip(Base):
    """Groups multiple Bookings into one multi-leg journey."""
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    bookings = relationship("Booking", back_populates="trip", order_by="Booking.leg_order")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    train_id = Column(Integer, ForeignKey("trains.id"), nullable=False)
    seat_id = Column(Integer, ForeignKey("seats.id"), nullable=False)

    from_station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    to_station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    journey_date = Column(Date, nullable=False)  # see module docstring

    ticket_type = Column(Enum(TicketType), nullable=False, default=TicketType.general)
    status = Column(Enum(BookingStatus), nullable=False, default=BookingStatus.held)
    refund_status = Column(Enum(RefundStatus), nullable=False, default=RefundStatus.none)

    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True)
    leg_order = Column(Integer, nullable=True)

    hold_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    train = relationship("Train")
    seat = relationship("Seat")
    from_station = relationship("Station", foreign_keys=[from_station_id])
    to_station = relationship("Station", foreign_keys=[to_station_id])
    trip = relationship("Trip", back_populates="bookings")

    __table_args__ = (
        Index("ix_bookings_seat_train_date", "seat_id", "train_id", "journey_date"),
        Index("ix_bookings_user", "user_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    action = Column(String(50), nullable=False)
    old_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
