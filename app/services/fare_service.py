from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from sqlalchemy import text
from sqlalchemy.orm import Session


CENT = Decimal("0.01")


def get_booking_fare(
    db: Session,
    train_run_id: int,
    from_station_id: int,
    to_station_id: int,
    compartment_type: str,
    passenger_count: int = 1,
) -> dict | None:
    if passenger_count < 1:
        return None

    journey = db.execute(
        text(
            """
            SELECT
                run.trainId AS train_id,
                train.trainType AS train_type,
                origin.stopSequence AS origin_sequence,
                destination.stopSequence AS destination_sequence
            FROM train_run AS run
            JOIN train ON train.id = run.trainId
            JOIN trainStop AS origin
                ON origin.trainRunId = run.trainRunId
                AND origin.stationId = :from_station_id
            JOIN trainStop AS destination
                ON destination.trainRunId = run.trainRunId
                AND destination.stationId = :to_station_id
            WHERE run.trainRunId = :train_run_id
                AND run.status = 'SCHEDULED'
            """
        ),
        {
            "train_run_id": train_run_id,
            "from_station_id": from_station_id,
            "to_station_id": to_station_id,
        },
    ).mappings().first()

    if journey is None or journey["origin_sequence"] >= journey["destination_sequence"]:
        return None

    segments = db.execute(
        text(
            """
            SELECT distance.distanceKm AS distance_km
            FROM schedule_segment_distance AS distance
            JOIN train_schedule_stop AS segment_from
                ON segment_from.trainId = distance.trainId
                AND segment_from.stationId = distance.fromStationId
            JOIN train_schedule_stop AS segment_to
                ON segment_to.trainId = distance.trainId
                AND segment_to.stationId = distance.toStationId
            WHERE distance.trainId = :train_id
                AND segment_from.stopSequence >= :origin_sequence
                AND segment_to.stopSequence <= :destination_sequence
                AND segment_to.stopSequence = segment_from.stopSequence + 1
            ORDER BY segment_from.stopSequence
            """
        ),
        {
            "train_id": journey["train_id"],
            "origin_sequence": journey["origin_sequence"],
            "destination_sequence": journey["destination_sequence"],
        },
    ).scalars().all()

    expected_segment_count = journey["destination_sequence"] - journey["origin_sequence"]
    if len(segments) != expected_segment_count:
        return None

    distance_km = sum(segments)
    route_totals = db.execute(
        text(
            """
            SELECT
                COALESCE(SUM(distanceKm), 0) AS route_distance_km,
                COUNT(*) AS segment_count
            FROM schedule_segment_distance
            WHERE trainId = :train_id
            """
        ),
        {"train_id": journey["train_id"]},
    ).mappings().one()
    stop_count = db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM train_schedule_stop
            WHERE trainId = :train_id
            """
        ),
        {"train_id": journey["train_id"]},
    ).scalar_one()
    if route_totals["segment_count"] != stop_count - 1:
        return None

    train_route_distance_km = route_totals["route_distance_km"]
    multipliers = db.execute(
        text(
            """
            SELECT
                train_factor.baseFareMultiplier AS train_type_multiplier,
                route_factor.fareMultiplier AS route_length_multiplier
            FROM train_type_fare_factor AS train_factor
            JOIN fare_route_length_factor AS route_factor
                ON route_factor.minRouteDistanceKm <= :route_distance_km
                AND (
                    route_factor.maxRouteDistanceKm IS NULL
                    OR route_factor.maxRouteDistanceKm >= :route_distance_km
                )
            WHERE train_factor.trainType = :train_type
            ORDER BY route_factor.minRouteDistanceKm DESC
            LIMIT 1
            """
        ),
        {
            "train_type": journey["train_type"],
            "route_distance_km": train_route_distance_km,
        },
    ).mappings().first()
    if multipliers is None:
        return None

    rates = db.execute(
        text(
            """
            SELECT
                slab.ratePerKm AS rate_per_km,
                slab.minimumBaseFare AS minimum_base_fare,
                reservation.feeAmount AS reservation_fee,
                type_charge.chargeAmount AS superfast_charge,
                tax.gstPercent AS gst_percent
            FROM fare_distance_slab AS slab
            JOIN reservation_fee AS reservation
                ON reservation.compartmentType = slab.compartmentType
            JOIN train_type_charge AS type_charge
                ON type_charge.trainType = :train_type
                AND type_charge.compartmentType = slab.compartmentType
            JOIN fare_tax_rate AS tax
                ON tax.compartmentType = slab.compartmentType
            WHERE slab.compartmentType = :compartment_type
                AND slab.minDistanceKm <= :distance_km
                AND (slab.maxDistanceKm IS NULL OR slab.maxDistanceKm >= :distance_km)
            ORDER BY slab.minDistanceKm DESC
            LIMIT 1
            """
        ),
        {
            "train_type": journey["train_type"],
            "compartment_type": compartment_type,
            "distance_km": distance_km,
        },
    ).mappings().first()

    if rates is None:
        return None

    combined_multiplier = (
        multipliers["train_type_multiplier"] * multipliers["route_length_multiplier"]
    )
    base_fare = max(
        Decimal(distance_km) * rates["rate_per_km"] * combined_multiplier,
        rates["minimum_base_fare"] * combined_multiplier,
    ).quantize(CENT, rounding=ROUND_HALF_UP)
    reservation_fee = rates["reservation_fee"]
    superfast_charge = rates["superfast_charge"]
    taxable_total = base_fare + reservation_fee + superfast_charge
    gst_amount = (
        taxable_total * rates["gst_percent"] / Decimal("100")
    ).quantize(CENT, rounding=ROUND_HALF_UP)
    unrounded_total = (taxable_total + gst_amount).quantize(CENT, rounding=ROUND_HALF_UP)
    total_fare = (
        (unrounded_total / Decimal("5")).quantize(Decimal("1"), rounding=ROUND_CEILING)
        * Decimal("5")
    )
    rounding_amount = total_fare - unrounded_total

    return {
        "distance_km": distance_km,
        "train_type": journey["train_type"],
        "train_route_distance_km": train_route_distance_km,
        "train_type_multiplier": multipliers["train_type_multiplier"],
        "route_length_multiplier": multipliers["route_length_multiplier"],
        "base_fare": base_fare,
        "base_fare_total": base_fare * passenger_count,
        "reservation_fee": reservation_fee,
        "reservation_fee_total": reservation_fee * passenger_count,
        "superfast_charge": superfast_charge,
        "superfast_charge_total": superfast_charge * passenger_count,
        "gst_percent": rates["gst_percent"],
        "gst_amount": gst_amount,
        "gst_total": gst_amount * passenger_count,
        "rounding_amount": rounding_amount,
        "rounding_total": rounding_amount * passenger_count,
        "total_fare": total_fare * passenger_count,
        "per_passenger_total": total_fare,
        "passenger_count": passenger_count,
    }
