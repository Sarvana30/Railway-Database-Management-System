from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.fare_service import get_booking_fare


class JourneySegmentUnavailable(Exception):
    pass


def get_seat_availability(
    db: Session,
    train_run_id: int,
    from_station_id: int,
    to_station_id: int,
) -> dict:
    journey = db.execute(
        text(
            """
            SELECT
                train_run.trainRunId AS train_run_id,
                train_run.trainId AS train_id,
                train_run.serviceDate AS service_date,
                origin.stopSequence AS origin_sequence,
                origin.departureAt AS departure_at,
                origin_station.name AS origin_name,
                destination.stopSequence AS destination_sequence,
                destination.arrivalAt AS arrival_at,
                destination_station.name AS destination_name
            FROM train_run
            JOIN trainStop AS origin
                ON origin.trainRunId = train_run.trainRunId
            JOIN station AS origin_station
                ON origin_station.id = origin.stationId
            JOIN trainStop AS destination
                ON destination.trainRunId = train_run.trainRunId
            JOIN station AS destination_station
                ON destination_station.id = destination.stationId
            WHERE train_run.trainRunId = :train_run_id
                AND train_run.status = 'SCHEDULED'
                AND origin.stationId = :from_station_id
                AND destination.stationId = :to_station_id
            """
        ),
        {
            "train_run_id": train_run_id,
            "from_station_id": from_station_id,
            "to_station_id": to_station_id,
        },
    ).mappings().first()

    if journey is None:
        raise JourneySegmentUnavailable("Train run or journey segment was not found.")

    if journey["origin_sequence"] >= journey["destination_sequence"]:
        raise JourneySegmentUnavailable("The origin must come before the destination.")

    if journey["departure_at"] is None or journey["arrival_at"] is None:
        raise JourneySegmentUnavailable("Journey times are incomplete.")

    if journey["arrival_at"] <= journey["departure_at"]:
        raise JourneySegmentUnavailable("Journey times are invalid.")

    seats = db.execute(
        text(
            """
            SELECT
                seat.seatId AS seat_id,
                seat.seatNo AS seat_number,
                seat.compartmentNo AS compartment_number,
                compartment.compartmentType AS compartment_type
            FROM seat
            JOIN compartment
                ON compartment.trainId = seat.trainId
                AND compartment.compartmentNo = seat.compartmentNo
            WHERE seat.trainId = :train_id
            ORDER BY compartment.compartmentNo, seat.seatNo
            """
        ),
        {"train_id": journey["train_id"]},
    ).mappings().all()

    fares_by_category = {
        category: get_booking_fare(
            db,
            train_run_id,
            from_station_id,
            to_station_id,
            category,
        )
        for category in {seat["compartment_type"] for seat in seats}
    }

    occupied_rows = db.execute(
        text(
            """
            SELECT occupancy.seat_id, occupancy.from_sequence, occupancy.to_sequence
            FROM (
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

                UNION ALL

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
            ) AS occupancy
            """
        ),
        {"train_run_id": train_run_id},
    ).mappings().all()

    occupied_intervals = defaultdict(list)
    for occupied in occupied_rows:
        occupied_intervals[occupied["seat_id"]].append(
            (occupied["from_sequence"], occupied["to_sequence"])
        )

    def seat_is_free(seat_id: int, from_sequence: int, to_sequence: int) -> bool:
        return not any(
            occupied_from < to_sequence and occupied_to > from_sequence
            for occupied_from, occupied_to in occupied_intervals[seat_id]
        )

    direct_available_seat_ids = {
        seat["seat_id"]
        for seat in seats
        if fares_by_category[seat["compartment_type"]] is not None
        and seat_is_free(
            seat["seat_id"],
            journey["origin_sequence"],
            journey["destination_sequence"],
        )
    }

    return {
        "train_run_id": journey["train_run_id"],
        "service_date": journey["service_date"],
        "departure_at": journey["departure_at"],
        "arrival_at": journey["arrival_at"],
        "origin_name": journey["origin_name"],
        "destination_name": journey["destination_name"],
        "seats": [
            {
                **dict(seat),
                "is_available": seat["seat_id"] in direct_available_seat_ids,
                "fare": fares_by_category[seat["compartment_type"]],
                "fare_per_passenger": (
                    fares_by_category[seat["compartment_type"]]["per_passenger_total"]
                    if fares_by_category[seat["compartment_type"]] is not None
                    else None
                ),
            }
            for seat in seats
        ],
    }
