from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_login
from app.services.booking_service import (
    BookingUnavailable,
    cancel_booking,
    confirm_booking_hold,
    create_booking_hold,
    get_booking_detail,
    release_booking_hold,
)
from app.services.fare_service import get_booking_fare

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.post("/bookings")
def create_booking_route(
    request: Request,
    train_run_id: int = Form(...),
    from_station_id: int = Form(...),
    to_station_id: int = Form(...),
    seat_ids: list[int] | None = Form(None),
    seat_category: str = Form(...),
    passenger_names: list[str] = Form(...),
    passenger_ages: list[int] = Form(...),
    passenger_genders: list[str] = Form(...),
    ticket_type: str = Form("GENERAL"),
    payment_confirmed: bool = Form(False),
    hold_token: str | None = Form(None),
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    seat_ids = seat_ids or []
    passenger_data_matches = (
        len(passenger_names) == len(passenger_ages) == len(passenger_genders)
    )
    seat_data_matches = len(seat_ids) == len(passenger_names)

    if not passenger_data_matches or not seat_data_matches:
        return RedirectResponse(
            f"/availability/{train_run_id}"
            f"?from_station_id={from_station_id}"
            f"&to_station_id={to_station_id}"
            "&error=booking_unavailable",
            status_code=303,
        )

    if not payment_confirmed:
        fare = get_booking_fare(
            db,
            train_run_id,
            from_station_id,
            to_station_id,
            seat_category,
            len(passenger_names),
        )
        if fare is None:
            return RedirectResponse(
                f"/availability/{train_run_id}"
                f"?from_station_id={from_station_id}"
                f"&to_station_id={to_station_id}"
                "&error=booking_unavailable",
                status_code=303,
            )

        journey = db.execute(
            text(
                """
                SELECT
                    train.id AS train_id,
                    train.trainNumber AS train_number,
                    train.name AS train_name,
                    origin.name AS origin_name,
                    destination.name AS destination_name,
                    origin_stop.departureAt AS departure_at,
                    destination_stop.arrivalAt AS arrival_at
                FROM train_run
                JOIN train ON train.id = train_run.trainId
                JOIN trainStop AS origin_stop
                    ON origin_stop.trainRunId = train_run.trainRunId
                    AND origin_stop.stationId = :from_station_id
                JOIN station AS origin ON origin.id = origin_stop.stationId
                JOIN trainStop AS destination_stop
                    ON destination_stop.trainRunId = train_run.trainRunId
                    AND destination_stop.stationId = :to_station_id
                JOIN station AS destination ON destination.id = destination_stop.stationId
                WHERE train_run.trainRunId = :train_run_id
                """
            ),
            {
                "train_run_id": train_run_id,
                "from_station_id": from_station_id,
                "to_station_id": to_station_id,
            },
        ).mappings().first()
        if journey is None:
            return RedirectResponse(
                f"/availability/{train_run_id}"
                f"?from_station_id={from_station_id}"
                f"&to_station_id={to_station_id}"
                "&error=booking_unavailable",
                status_code=303,
            )

        try:
            hold = create_booking_hold(
                db=db,
                user_id=user["id"],
                train_run_id=train_run_id,
                from_station_id=from_station_id,
                to_station_id=to_station_id,
                seat_ids=seat_ids,
                seat_category=seat_category,
                ticket_type=ticket_type,
                passenger_count=len(passenger_names),
            )
            db.commit()
        except BookingUnavailable:
            db.rollback()
            return RedirectResponse(
                f"/availability/{train_run_id}"
                f"?from_station_id={from_station_id}"
                f"&to_station_id={to_station_id}"
                "&error=booking_unavailable",
                status_code=303,
            )

        return templates.TemplateResponse(
            request=request,
            name="payment.html",
            context={
                "train_run_id": train_run_id,
                "from_station_id": from_station_id,
                "to_station_id": to_station_id,
                "seat_ids": seat_ids,
                "seat_category": seat_category,
                "passenger_names": passenger_names,
                "passenger_ages": passenger_ages,
                "passenger_genders": passenger_genders,
                "ticket_type": ticket_type,
                "hold_token": hold["hold_token"],
                "hold_expires_at": hold["expires_at"],
                "total_fare": fare["total_fare"],
                "fare": fare,
                "journey": journey,
            },
        )

    passengers = [
        {"name": name, "age": age, "gender": gender}
        for name, age, gender in zip(
            passenger_names,
            passenger_ages,
            passenger_genders,
        )
    ]

    try:
        if not hold_token:
            raise BookingUnavailable("The seat hold is missing. Start checkout again.")
        booking = confirm_booking_hold(
            db=db,
            user_id=user["id"],
            hold_token=hold_token,
            train_run_id=train_run_id,
            from_station_id=from_station_id,
            to_station_id=to_station_id,
            seat_ids=seat_ids,
            seat_category=seat_category,
            passengers=passengers,
            ticket_type=ticket_type,
        )
        db.commit()
    except BookingUnavailable as error:
        db.rollback()
        error_code = "hold_expired" if "expired" in str(error).lower() else "booking_unavailable"
        return RedirectResponse(
            f"/availability/{train_run_id}"
            f"?from_station_id={from_station_id}"
            f"&to_station_id={to_station_id}"
            f"&error={error_code}",
            status_code=303,
        )

    return RedirectResponse(
        f"/bookings/{booking['ticket_id']}",
        status_code=303,
    )

@router.get(
    "/bookings/{ticket_id}",
    response_class=HTMLResponse,
)
@router.get(
    "/booking_details/{ticket_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
@router.get(
    "/booking_detail/{ticket_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def booking_detail(
    request: Request,
    ticket_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    detail = get_booking_detail(db, ticket_id, user["id"])

    if detail is None:
        raise HTTPException(status_code=404, detail="Booking not found.")

    return templates.TemplateResponse(
    request=request,
    name="booking_detail.html",
    context={
        "booking": detail["booking"],
        "passengers": detail["passengers"],
        "error": (
            "This booking could not be cancelled. It may already be cancelled or the scheduled departure may have passed."
            if request.query_params.get("error") == "cancel_unavailable"
            else None
        ),
        "cancelled": request.query_params.get("cancelled") == "1",
    },
)


@router.post("/booking-holds/release")
def release_booking_hold_route(
    hold_token: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    hold = release_booking_hold(db, user["id"], hold_token)
    if hold is None:
        db.rollback()
        return RedirectResponse("/search", status_code=303)

    db.commit()
    return RedirectResponse(
        f"/availability/{hold['trainRunId']}"
        f"?from_station_id={hold['startStationId']}"
        f"&to_station_id={hold['endStationId']}",
        status_code=303,
    )


@router.get(
    "/bookings/{ticket_id}/cancel",
    response_class=HTMLResponse,
)
def cancel_booking_page(
    request: Request,
    ticket_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    detail = get_booking_detail(db, ticket_id, user["id"])

    if detail is None:
        raise HTTPException(status_code=404, detail="Booking not found.")

    return templates.TemplateResponse(
        request=request,
        name="cancel_booking.html",
        context={
            "booking": detail["booking"],
            "passengers": detail["passengers"],
        },
    )


@router.post("/bookings/{ticket_id}/cancel")
def cancel_booking_route(
    ticket_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    try:
        cancel_booking(db, ticket_id, user["id"])
        db.commit()
    except BookingUnavailable:
        db.rollback()
        return RedirectResponse(
            f"/bookings/{ticket_id}?error=cancel_unavailable",
            status_code=303,
        )

    return RedirectResponse(
        f"/bookings/{ticket_id}?cancelled=1",
        status_code=303,
    )


@router.get("/booking_detail", include_in_schema=False)
def booking_detail_redirect():
    return RedirectResponse("/my-bookings", status_code=303)


@router.get("/my_bookings", response_class=HTMLResponse, include_in_schema=False)
@router.get("/my-bookings", response_class=HTMLResponse)
def my_bookings(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    bookings = db.execute(
        text("""
            SELECT
                ticket.ticketId AS ticket_id,
                train.trainNumber AS train_number,
                train.name AS train_name,
                origin_station.name AS origin_name,
                destination_station.name AS destination_name,
                DATE(origin_stop.departureAt) AS service_date,
                origin_stop.departureAt AS departure_at,
                origin_stop.departureAt > CURRENT_TIMESTAMP AS can_cancel,
                destination_stop.arrivalAt AS arrival_at,
                ticket.ticketType AS ticket_type,
                ticket.status AS display_status,
                ticket.refundStatus AS refund_status,
                ticket.fareAmount AS fare_amount,
                (
                    SELECT COUNT(*)
                    FROM passenger
                    WHERE passenger.ticketId = ticket.ticketId
                ) AS passenger_count
            FROM ticket
            JOIN train_run
                ON train_run.trainRunId = ticket.trainRunId
                AND train_run.trainId = ticket.trainId
            JOIN train
                ON train.id = ticket.trainId
            JOIN trainStop AS origin_stop
                ON origin_stop.trainRunId = ticket.trainRunId
                AND origin_stop.trainId = ticket.trainId
                AND origin_stop.stationId = ticket.startStationId
            JOIN station AS origin_station
                ON origin_station.id = ticket.startStationId
            JOIN trainStop AS destination_stop
                ON destination_stop.trainRunId = ticket.trainRunId
                AND destination_stop.trainId = ticket.trainId
                AND destination_stop.stationId = ticket.endStationId
            JOIN station AS destination_station
                ON destination_station.id = ticket.endStationId
            WHERE ticket.userId = :user_id
            ORDER BY ticket.bookedAt DESC, ticket.ticketId DESC
        """),
        {"user_id": user["id"]},
    ).mappings().all()

    return templates.TemplateResponse(
    request=request,
    name="my_bookings.html",
    context={
        "user": user,
        "bookings": bookings,
    },
)
