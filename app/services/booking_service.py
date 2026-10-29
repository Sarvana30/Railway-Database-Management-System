import secrets

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.services.fare_service import get_booking_fare


class BookingUnavailable(Exception):
    pass


HOLD_DURATION_MINUTES = 5


def create_booking_hold(
    db: Session,
    user_id: int,
    train_run_id: int,
    from_station_id: int,
    to_station_id: int,
    seat_ids: list[int],
    seat_category: str,
    ticket_type: str,
    passenger_count: int,
) -> dict:
    """Temporarily reserve direct journey seats while the user checks out."""
    if not seat_ids or passenger_count < 1 or len(seat_ids) != passenger_count:
        raise BookingUnavailable("Each passenger must have one seat.")
    if len(set(seat_ids)) != len(seat_ids):
        raise BookingUnavailable("Each passenger must have a different seat.")
    if ticket_type not in {"GENERAL", "TATKAL", "LADIES", "SENIOR"}:
        raise BookingUnavailable("Choose a valid ticket type.")
    if seat_category not in {
        "AC tier 1",
        "AC tier 2",
        "AC tier 3",
        "Sleeper",
        "2s",
        "cc",
    }:
        raise BookingUnavailable("Choose a valid seat category.")

    with db.begin_nested():
        train_run = db.execute(
            text(
                """
                SELECT trainRunId, trainId, status
                FROM train_run
                WHERE trainRunId = :train_run_id
                FOR UPDATE
                """
            ),
            {"train_run_id": train_run_id},
        ).mappings().first()
        if train_run is None or train_run["status"] != "SCHEDULED":
            raise BookingUnavailable("This train run is not available.")

        stops = db.execute(
            text(
                """
                SELECT stationId, stopSequence, arrivalAt, departureAt
                FROM trainStop
                WHERE trainRunId = :train_run_id
                    AND stationId IN :station_ids
                FOR UPDATE
                """
            ).bindparams(bindparam("station_ids", expanding=True)),
            {
                "train_run_id": train_run_id,
                "station_ids": [from_station_id, to_station_id],
            },
        ).mappings().all()
        stops_by_station = {stop["stationId"]: stop for stop in stops}
        origin = stops_by_station.get(from_station_id)
        destination = stops_by_station.get(to_station_id)
        if origin is None or destination is None:
            raise BookingUnavailable("The selected stations are not on this train.")
        if origin["stopSequence"] >= destination["stopSequence"]:
            raise BookingUnavailable("The origin must come before the destination.")
        if origin["departureAt"] is None or destination["arrivalAt"] is None:
            raise BookingUnavailable("Journey times are incomplete.")

        selected_seats = db.execute(
            text(
                """
                SELECT seat.seatId, compartment.compartmentType
                FROM seat
                JOIN compartment
                    ON compartment.trainId = seat.trainId
                    AND compartment.compartmentNo = seat.compartmentNo
                WHERE seat.trainId = :train_id
                    AND seat.seatId IN :seat_ids
                ORDER BY seat.seatId
                FOR UPDATE
                """
            ).bindparams(bindparam("seat_ids", expanding=True)),
            {"train_id": train_run["trainId"], "seat_ids": seat_ids},
        ).mappings().all()
        if {seat["seatId"] for seat in selected_seats} != set(seat_ids):
            raise BookingUnavailable("A selected seat does not belong to this train.")
        if any(seat["compartmentType"] != seat_category for seat in selected_seats):
            raise BookingUnavailable("A selected seat does not match the chosen category.")

        confirmed_rows = db.execute(
            text(
                """
                SELECT
                    seat_leg.seatId AS seat_id,
                    assigned_from.stopSequence AS from_sequence,
                    assigned_to.stopSequence AS to_sequence
                FROM seat_leg
                JOIN ticket
                    ON ticket.ticketId = seat_leg.ticketId
                    AND ticket.trainRunId = seat_leg.trainRunId
                    AND ticket.trainId = seat_leg.trainId
                JOIN trainStop AS assigned_from
                    ON assigned_from.trainRunId = seat_leg.trainRunId
                    AND assigned_from.stationId = seat_leg.fromStationId
                JOIN trainStop AS assigned_to
                    ON assigned_to.trainRunId = seat_leg.trainRunId
                    AND assigned_to.stationId = seat_leg.toStationId
                WHERE seat_leg.trainRunId = :train_run_id
                    AND ticket.status = 'CONFIRMED'
                FOR UPDATE
                """
            ),
            {"train_run_id": train_run_id},
        ).mappings().all()
        held_rows = db.execute(
            text(
                """
                SELECT
                    held_seat.seatId AS seat_id,
                    held_from.stopSequence AS from_sequence,
                    held_to.stopSequence AS to_sequence
                FROM booking_hold_seat AS held_seat
                JOIN booking_hold AS held
                    ON held.holdId = held_seat.holdId
                JOIN trainStop AS held_from
                    ON held_from.trainRunId = held_seat.trainRunId
                    AND held_from.stationId = held_seat.fromStationId
                JOIN trainStop AS held_to
                    ON held_to.trainRunId = held_seat.trainRunId
                    AND held_to.stationId = held_seat.toStationId
                WHERE held.trainRunId = :train_run_id
                    AND held.status = 'ACTIVE'
                    AND held.expiresAt > CURRENT_TIMESTAMP
                FOR UPDATE
                """
            ),
            {"train_run_id": train_run_id},
        ).mappings().all()
        occupied_rows = [*confirmed_rows, *held_rows]

        occupied_by_seat = {}
        for occupied in occupied_rows:
            occupied_by_seat.setdefault(occupied["seat_id"], []).append(
                (occupied["from_sequence"], occupied["to_sequence"])
            )
        for seat_id in seat_ids:
            if any(
                occupied_from < destination["stopSequence"]
                and occupied_to > origin["stopSequence"]
                for occupied_from, occupied_to in occupied_by_seat.get(seat_id, [])
            ):
                raise BookingUnavailable(
                    "One or more selected seats have just been booked or held."
                )

        hold_token = secrets.token_urlsafe(32)
        result = db.execute(
            text(
                """
                INSERT INTO booking_hold (
                    holdToken,
                    userId,
                    trainRunId,
                    trainId,
                    startStationId,
                    endStationId,
                    seatCategory,
                    ticketType,
                    passengerCount,
                    expiresAt
                )
                VALUES (
                    :hold_token,
                    :user_id,
                    :train_run_id,
                    :train_id,
                    :from_station_id,
                    :to_station_id,
                    :seat_category,
                    :ticket_type,
                    :passenger_count,
                    TIMESTAMPADD(MINUTE, :hold_minutes, CURRENT_TIMESTAMP)
                )
                """
            ),
            {
                "hold_token": hold_token,
                "user_id": user_id,
                "train_run_id": train_run_id,
                "train_id": train_run["trainId"],
                "from_station_id": from_station_id,
                "to_station_id": to_station_id,
                "seat_category": seat_category,
                "ticket_type": ticket_type,
                "passenger_count": passenger_count,
                "hold_minutes": HOLD_DURATION_MINUTES,
            },
        )
        hold_id = result.lastrowid

        for seat_id in seat_ids:
            db.execute(
                text(
                    """
                    INSERT INTO booking_hold_seat (
                        holdId,
                        trainRunId,
                        trainId,
                        seatId,
                        fromStationId,
                        toStationId
                    )
                    VALUES (
                        :hold_id,
                        :train_run_id,
                        :train_id,
                        :seat_id,
                        :from_station_id,
                        :to_station_id
                    )
                    """
                ),
                {
                    "hold_id": hold_id,
                    "train_run_id": train_run_id,
                    "train_id": train_run["trainId"],
                    "seat_id": seat_id,
                    "from_station_id": from_station_id,
                    "to_station_id": to_station_id,
                },
            )

        expires_at = db.execute(
            text("SELECT expiresAt FROM booking_hold WHERE holdId = :hold_id"),
            {"hold_id": hold_id},
        ).scalar_one()

    return {"hold_token": hold_token, "expires_at": expires_at}


def release_booking_hold(db: Session, user_id: int, hold_token: str) -> dict | None:
    hold_ref = db.execute(
        text(
            """
            SELECT holdId, trainRunId
            FROM booking_hold
            WHERE holdToken = :hold_token AND userId = :user_id
            """
        ),
        {"hold_token": hold_token, "user_id": user_id},
    ).mappings().first()
    if hold_ref is None:
        return None

    with db.begin_nested():
        db.execute(
            text("SELECT trainRunId FROM train_run WHERE trainRunId = :run_id FOR UPDATE"),
            {"run_id": hold_ref["trainRunId"]},
        ).first()
        hold = db.execute(
            text(
                """
                SELECT holdId, trainRunId, startStationId, endStationId, status
                FROM booking_hold
                WHERE holdId = :hold_id AND userId = :user_id
                FOR UPDATE
                """
            ),
            {"hold_id": hold_ref["holdId"], "user_id": user_id},
        ).mappings().first()
        if hold is None:
            return None
        if hold["status"] == "ACTIVE":
            db.execute(
                text("UPDATE booking_hold SET status = 'RELEASED' WHERE holdId = :hold_id"),
                {"hold_id": hold["holdId"]},
            )
        return dict(hold)


def create_booking(
    db: Session,
    user_id: int,
    train_run_id: int,
    from_station_id: int,
    to_station_id: int,
    seat_ids: list[int] | None,
    seat_category: str,
    passengers: list[dict],
    ticket_type: str,
) -> dict:
    allowed_ticket_types = {"GENERAL", "TATKAL", "LADIES", "SENIOR"}
    allowed_genders = {"F", "M", "OTHER", "UNSPECIFIED"}
    allowed_seat_categories = {
        "AC tier 1",
        "AC tier 2",
        "AC tier 3",
        "Sleeper",
        "2s",
        "cc",
    }

    if from_station_id == to_station_id:
        raise BookingUnavailable("Choose two different stations.")

    seat_ids = seat_ids or []
    if not passengers:
        raise BookingUnavailable("Add at least one passenger.")
    if len(seat_ids) != len(passengers):
        raise BookingUnavailable("Each passenger must have one seat.")
    if len(set(seat_ids)) != len(seat_ids):
        raise BookingUnavailable("Each passenger must have a different seat.")

    if ticket_type not in allowed_ticket_types:
        raise BookingUnavailable("Choose a valid ticket type.")

    if seat_category not in allowed_seat_categories:
        raise BookingUnavailable("Choose a valid seat category.")

    cleaned_passengers = []
    for passenger in passengers:
        name = passenger["name"].strip()
        age = passenger["age"]
        gender = passenger["gender"]

        if not name or len(name) > 100:
            raise BookingUnavailable("Enter a valid passenger name.")
        if age < 0 or age > 255:
            raise BookingUnavailable("Enter a valid passenger age.")
        if gender not in allowed_genders:
            raise BookingUnavailable("Choose a valid passenger gender.")

        cleaned_passengers.append({"name": name, "age": age, "gender": gender})

    with db.begin_nested():
        train_run = db.execute(
            text(
                """
                SELECT trainRunId, trainId, status
                FROM train_run
                WHERE trainRunId = :train_run_id
                FOR UPDATE
                """
            ),
            {"train_run_id": train_run_id},
        ).mappings().first()
        if train_run is None or train_run["status"] != "SCHEDULED":
            raise BookingUnavailable("This train run is not available.")

        fare = get_booking_fare(
            db,
            train_run_id,
            from_station_id,
            to_station_id,
            seat_category,
            len(cleaned_passengers),
        )
        if fare is None:
            raise BookingUnavailable("A fare or route distance is not configured.")

        stop_statement = text(
            """
            SELECT stationId, stopSequence, arrivalAt, departureAt
            FROM trainStop
            WHERE trainRunId = :train_run_id
                AND stationId IN :station_ids
            FOR UPDATE
            """
        ).bindparams(bindparam("station_ids", expanding=True))
        stops = db.execute(
            stop_statement,
            {
                "train_run_id": train_run_id,
                "station_ids": [from_station_id, to_station_id],
            },
        ).mappings().all()
        stops_by_station = {stop["stationId"]: stop for stop in stops}
        origin = stops_by_station.get(from_station_id)
        destination = stops_by_station.get(to_station_id)

        if origin is None or destination is None:
            raise BookingUnavailable("The selected stations are not on this train.")
        if origin["stopSequence"] >= destination["stopSequence"]:
            raise BookingUnavailable("The origin must come before the destination.")
        if origin["departureAt"] is None or destination["arrivalAt"] is None:
            raise BookingUnavailable("Journey times are incomplete.")

        seat_statement = text(
            """
            SELECT seat.seatId, compartment.compartmentType
            FROM seat
            JOIN compartment
                ON compartment.trainId = seat.trainId
                AND compartment.compartmentNo = seat.compartmentNo
            WHERE seat.trainId = :train_id
                AND seat.seatId IN :seat_ids
            ORDER BY seat.seatId
            FOR UPDATE
            """
        ).bindparams(bindparam("seat_ids", expanding=True))
        locked_seats = db.execute(
            seat_statement,
            {"train_id": train_run["trainId"], "seat_ids": seat_ids},
        ).mappings().all()
        if {seat["seatId"] for seat in locked_seats} != set(seat_ids):
            raise BookingUnavailable("A selected seat does not belong to this train.")
        if any(seat["compartmentType"] != seat_category for seat in locked_seats):
            raise BookingUnavailable("A selected seat does not match the chosen category.")

        occupied_statement = text(
            """
            SELECT
                seat_leg.seatId AS seat_id,
                assigned_from.stopSequence AS from_sequence,
                assigned_to.stopSequence AS to_sequence
            FROM seat_leg
            JOIN ticket
                ON ticket.ticketId = seat_leg.ticketId
                AND ticket.trainRunId = seat_leg.trainRunId
                AND ticket.trainId = seat_leg.trainId
            JOIN trainStop AS assigned_from
                ON assigned_from.trainRunId = seat_leg.trainRunId
                AND assigned_from.stationId = seat_leg.fromStationId
            JOIN trainStop AS assigned_to
                ON assigned_to.trainRunId = seat_leg.trainRunId
                AND assigned_to.stationId = seat_leg.toStationId
            WHERE seat_leg.trainRunId = :train_run_id
                AND ticket.status = 'CONFIRMED'
            FOR UPDATE
            """
        )
        occupied_seats = db.execute(
            occupied_statement,
            {"train_run_id": train_run_id},
        ).mappings().all()
        occupied_by_seat = {}
        for occupied in occupied_seats:
            occupied_by_seat.setdefault(occupied["seat_id"], []).append(
                (occupied["from_sequence"], occupied["to_sequence"])
            )

        for seat_id in seat_ids:
            overlaps_existing_booking = any(
                occupied_from < destination["stopSequence"]
                and occupied_to > origin["stopSequence"]
                for occupied_from, occupied_to in occupied_by_seat.get(seat_id, [])
            )
            if overlaps_existing_booking:
                raise BookingUnavailable(
                    "One or more selected seats are no longer available."
                )

        ticket_result = db.execute(
            text(
                """
                INSERT INTO ticket (
                    userId,
                    trainRunId,
                    trainId,
                    startStationId,
                    endStationId,
                    ticketType,
                    status,
                    paymentStatus,
                    fareModel,
                    distanceKm,
                    trainRouteDistanceKm,
                    trainTypeFareMultiplier,
                    routeLengthFareMultiplier,
                    baseFareAmount,
                    reservationFeeAmount,
                    superfastChargeAmount,
                    gstAmount,
                    fareRoundingAmount,
                    fareAmount
                )
                VALUES (
                    :user_id,
                    :train_run_id,
                    :train_id,
                    :from_station_id,
                    :to_station_id,
                    :ticket_type,
                    'CONFIRMED',
                    'PAID',
                    'DISTANCE_SLAB',
                    :distance_km,
                    :train_route_distance_km,
                    :train_type_multiplier,
                    :route_length_multiplier,
                    :base_fare,
                    :reservation_fee,
                    :superfast_charge,
                    :gst_amount,
                    :rounding_amount,
                    :fare_amount
                )
                """
            ),
            {
                "user_id": user_id,
                "train_run_id": train_run_id,
                "train_id": train_run["trainId"],
                "from_station_id": from_station_id,
                "to_station_id": to_station_id,
                "ticket_type": ticket_type,
                "distance_km": fare["distance_km"],
                "train_route_distance_km": fare["train_route_distance_km"],
                "train_type_multiplier": fare["train_type_multiplier"],
                "route_length_multiplier": fare["route_length_multiplier"],
                "base_fare": fare["base_fare"] * len(cleaned_passengers),
                "reservation_fee": fare["reservation_fee"] * len(cleaned_passengers),
                "superfast_charge": fare["superfast_charge"] * len(cleaned_passengers),
                "gst_amount": fare["gst_amount"] * len(cleaned_passengers),
                "rounding_amount": fare["rounding_amount"] * len(cleaned_passengers),
                "fare_amount": fare["total_fare"],
            },
        )
        ticket_id = ticket_result.lastrowid

        for passenger_no, (passenger, seat_id) in enumerate(
            zip(cleaned_passengers, seat_ids),
            start=1,
        ):
            db.execute(
                text(
                    """
                    INSERT INTO passenger (ticketId, passengerNo, name, age, gender)
                    VALUES (
                        :ticket_id,
                        :passenger_no,
                        :name,
                        :age,
                        :gender
                    )
                    """
                ),
                {
                    "ticket_id": ticket_id,
                    "passenger_no": passenger_no,
                    **passenger,
                },
            )
            db.execute(
                text(
                    """
                    INSERT INTO seat_leg (
                        ticketId,
                        passengerNo,
                        legNo,
                        trainRunId,
                        trainId,
                        seatId,
                        fromStationId,
                        toStationId
                    )
                    VALUES (
                        :ticket_id,
                        :passenger_no,
                        1,
                        :train_run_id,
                        :train_id,
                        :seat_id,
                        :from_station_id,
                        :to_station_id
                    )
                    """
                ),
                {
                    "ticket_id": ticket_id,
                    "passenger_no": passenger_no,
                    "train_run_id": train_run_id,
                    "train_id": train_run["trainId"],
                    "seat_id": seat_id,
                    "from_station_id": from_station_id,
                    "to_station_id": to_station_id,
                },
            )

    return {"ticket_id": ticket_id}

def confirm_booking_hold(
    db: Session,
    user_id: int,
    hold_token: str,
    train_run_id: int,
    from_station_id: int,
    to_station_id: int,
    seat_ids: list[int],
    seat_category: str,
    passengers: list[dict],
    ticket_type: str,
) -> dict:
    hold_ref = db.execute(
        text(
            """
            SELECT holdId, trainRunId
            FROM booking_hold
            WHERE holdToken = :hold_token AND userId = :user_id
            """
        ),
        {"hold_token": hold_token, "user_id": user_id},
    ).mappings().first()
    if hold_ref is None or hold_ref["trainRunId"] != train_run_id:
        raise BookingUnavailable("The seat hold was not found. Start checkout again.")

    with db.begin_nested():
        db.execute(
            text("SELECT trainRunId FROM train_run WHERE trainRunId = :run_id FOR UPDATE"),
            {"run_id": train_run_id},
        ).first()
        hold = db.execute(
            text(
                """
                SELECT
                    holdId,
                    trainRunId,
                    startStationId,
                    endStationId,
                    seatCategory,
                    ticketType,
                    passengerCount,
                    status,
                    ticketId,
                    expiresAt <= CURRENT_TIMESTAMP AS is_expired
                FROM booking_hold
                WHERE holdId = :hold_id AND userId = :user_id
                FOR UPDATE
                """
            ),
            {"hold_id": hold_ref["holdId"], "user_id": user_id},
        ).mappings().first()
        if hold is None:
            raise BookingUnavailable("The seat hold was not found. Start checkout again.")

        # Make a repeated final submit return the ticket from the first submit.
        if hold["status"] == "CONSUMED" and hold["ticketId"] is not None:
            return {"ticket_id": hold["ticketId"]}

        if hold["status"] != "ACTIVE" or hold["is_expired"]:
            raise BookingUnavailable("The seat hold expired. Choose seats again.")

        if (
            hold["trainRunId"] != train_run_id
            or hold["startStationId"] != from_station_id
            or hold["endStationId"] != to_station_id
            or hold["seatCategory"] != seat_category
            or hold["ticketType"] != ticket_type
            or hold["passengerCount"] != len(passengers)
        ):
            raise BookingUnavailable("The checkout details do not match this seat hold.")

        held_seat_ids = db.execute(
            text(
                """
                SELECT seatId
                FROM booking_hold_seat
                WHERE holdId = :hold_id
                """
            ),
            {"hold_id": hold["holdId"]},
        ).scalars().all()
        if len(set(seat_ids)) != len(seat_ids) or set(seat_ids) != set(held_seat_ids):
            raise BookingUnavailable("The selected seats do not match this seat hold.")

        booking = create_booking(
            db=db,
            user_id=user_id,
            train_run_id=train_run_id,
            from_station_id=from_station_id,
            to_station_id=to_station_id,
            seat_ids=seat_ids,
            seat_category=seat_category,
            passengers=passengers,
            ticket_type=ticket_type,
        )
        db.execute(
            text(
                """
                UPDATE booking_hold
                SET status = 'CONSUMED', ticketId = :ticket_id
                WHERE holdId = :hold_id
                """
            ),
            {"hold_id": hold["holdId"], "ticket_id": booking["ticket_id"]},
        )
        return booking


def get_booking_detail(
    db: Session,
    ticket_id: int,
    user_id: int,
) -> dict | None:
    booking = db.execute(
        text(
            """
            SELECT
                ticket.ticketId AS ticket_id,
                ticket.status,
                ticket.ticketType AS ticket_type,
                ticket.bookedAt AS booked_at,
                ticket.paymentStatus AS payment_status,
                ticket.fareAmount AS fare_amount,
                ticket.fareModel AS fare_model,
                ticket.distanceKm AS distance_km,
                ticket.trainRouteDistanceKm AS train_route_distance_km,
                ticket.trainTypeFareMultiplier AS train_type_multiplier,
                ticket.routeLengthFareMultiplier AS route_length_multiplier,
                ticket.baseFareAmount AS base_fare_amount,
                ticket.reservationFeeAmount AS reservation_fee_amount,
                ticket.superfastChargeAmount AS superfast_charge_amount,
                ticket.gstAmount AS gst_amount,
                ticket.fareRoundingAmount AS rounding_amount,
                ticket.refundStatus AS refund_status,
                train.trainType AS train_type,
                origin.departureAt > CURRENT_TIMESTAMP AS can_cancel,
                train.trainNumber AS train_number,
                train.name AS train_name,
                origin_station.name AS origin_name,
                destination_station.name AS destination_name,
                origin.departureAt AS departure_at,
                destination.arrivalAt AS arrival_at
            FROM ticket
            JOIN train
                ON train.id = ticket.trainId
            JOIN trainStop AS origin
                ON origin.trainRunId = ticket.trainRunId
                AND origin.stationId = ticket.startStationId
            JOIN station AS origin_station
                ON origin_station.id = origin.stationId
            JOIN trainStop AS destination
                ON destination.trainRunId = ticket.trainRunId
                AND destination.stationId = ticket.endStationId
            JOIN station AS destination_station
                ON destination_station.id = destination.stationId
            WHERE ticket.ticketId = :ticket_id
                AND ticket.userId = :user_id
            """
        ),
        {
            "ticket_id": ticket_id,
            "user_id": user_id,
        },
    ).mappings().first()

    if booking is None:
        return None

    passengers = db.execute(
        text(
            """
            SELECT
                passenger.passengerNo AS passenger_no,
                passenger.name,
                passenger.age,
                passenger.gender,
                seat_leg.legNo AS leg_no,
                from_station.name AS from_station_name,
                to_station.name AS to_station_name,
                seat.seatNo AS seat_number,
                seat.compartmentNo AS compartment_number,
                compartment.compartmentType AS compartment_type
            FROM passenger
            JOIN seat_leg
                ON seat_leg.ticketId = passenger.ticketId
                AND seat_leg.passengerNo = passenger.passengerNo
            JOIN seat
                ON seat.seatId = seat_leg.seatId
            JOIN station AS from_station
                ON from_station.id = seat_leg.fromStationId
            JOIN station AS to_station
                ON to_station.id = seat_leg.toStationId
            JOIN compartment
                ON compartment.trainId = seat.trainId
                AND compartment.compartmentNo = seat.compartmentNo
            WHERE passenger.ticketId = :ticket_id
            ORDER BY passenger.passengerNo, seat_leg.legNo
            """
        ),
        {"ticket_id": ticket_id},
    ).mappings().all()

    return {
        "booking": dict(booking),
        "passengers": [dict(passenger) for passenger in passengers],
    }


def cancel_booking(db: Session, ticket_id: int, user_id: int) -> None:
    with db.begin_nested():
        ticket_ref = db.execute(
            text(
                """
                SELECT trainRunId
                FROM ticket
                WHERE ticketId = :ticket_id
                    AND userId = :user_id
                """
            ),
            {"ticket_id": ticket_id, "user_id": user_id},
        ).mappings().first()

        if ticket_ref is None:
            raise BookingUnavailable("Booking was not found.")

        # Booking creation also locks this row, so cancellation and a new
        # booking for the same train run serialize before checking seats.
        db.execute(
            text(
                """
                SELECT trainRunId
                FROM train_run
                WHERE trainRunId = :train_run_id
                FOR UPDATE
                """
            ),
            {"train_run_id": ticket_ref["trainRunId"]},
        ).first()

        ticket = db.execute(
            text(
                """
                SELECT status, trainRunId, startStationId
                FROM ticket
                WHERE ticketId = :ticket_id
                    AND userId = :user_id
                FOR UPDATE
                """
            ),
            {"ticket_id": ticket_id, "user_id": user_id},
        ).mappings().first()

        if ticket is None:
            raise BookingUnavailable("Booking was not found.")

        if ticket["status"] == "CANCELLED":
            return

        if ticket["status"] != "CONFIRMED":
            raise BookingUnavailable("This booking cannot be cancelled.")

        departure_passed = db.execute(
            text(
                """
                SELECT departureAt <= CURRENT_TIMESTAMP
                FROM trainStop
                WHERE trainRunId = :train_run_id
                    AND stationId = :station_id
                """
            ),
            {
                "train_run_id": ticket["trainRunId"],
                "station_id": ticket["startStationId"],
            },
        ).scalar_one_or_none()

        if departure_passed is None or departure_passed:
            raise BookingUnavailable("The scheduled train departure has passed.")

        db.execute(
            text(
                """
                UPDATE ticket
                SET status = 'CANCELLED',
                    paymentStatus = 'REFUNDED',
                    refundStatus = 'REFUNDED'
                WHERE ticketId = :ticket_id
                    AND userId = :user_id
                """
            ),
            {"ticket_id": ticket_id, "user_id": user_id},
        )
