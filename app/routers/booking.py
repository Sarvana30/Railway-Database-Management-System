from datetime import datetime

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_login
from app.models import Booking, TicketType, Station, Train
from app.services import booking_service, split_ticket
from app.services.availability import find_any_available_seat

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.post("/book")
def book(
    request: Request,
    train_id: int = Form(...),
    seat_id: int = Form(...),
    from_station_id: int = Form(...),
    to_station_id: int = Form(...),
    journey_date: str = Form(...),
    ticket_type: str = Form("general"),
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    jdate = datetime.strptime(journey_date, "%Y-%m-%d").date()
    try:
        b = booking_service.create_hold(
            db, user.id, train_id, seat_id, from_station_id, to_station_id, jdate, TicketType(ticket_type)
        )
    except booking_service.SeatUnavailable:
        return RedirectResponse(
            f"/seatmap/{train_id}?from_station_id={from_station_id}&to_station_id={to_station_id}"
            f"&journey_date={journey_date}&error=unavailable",
            status_code=303,
        )
    return RedirectResponse(f"/bookings/{b.id}", status_code=303)


@router.post("/book/split")
def book_split(
    request: Request,
    train_id: int = Form(...),
    from_station_id: int = Form(...),
    to_station_id: int = Form(...),
    journey_date: str = Form(...),
    ticket_type: str = Form("general"),
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    """Feature 5 entry point: no single seat is free for the whole route, so
    find a mid-journey split and book both legs as one Trip.
    """
    jdate = datetime.strptime(journey_date, "%Y-%m-%d").date()
    plan = split_ticket.find_split(db, train_id, from_station_id, to_station_id, jdate)
    if plan is None:
        return RedirectResponse("/search", status_code=303)

    trip = split_ticket.book_split(
        db, user.id, train_id, plan, from_station_id, to_station_id, jdate, TicketType(ticket_type)
    )
    return RedirectResponse(f"/trips/{trip.id}", status_code=303)


@router.get("/bookings/{booking_id}", response_class=HTMLResponse)
def booking_detail(
    request: Request, booking_id: int, db: Session = Depends(get_db), user=Depends(require_login)
):
    b = db.get(Booking, booking_id)
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "booking_confirm.html", {"request": request, "user": user, "booking": b, "error": error}
    )


@router.post("/bookings/{booking_id}/confirm")
def confirm(booking_id: int, db: Session = Depends(get_db), user=Depends(require_login)):
    try:
        booking_service.confirm_booking(db, booking_id, user.id)
    except booking_service.HoldExpiredOrWrongState as e:
        return RedirectResponse(f"/bookings/{booking_id}?error={e}", status_code=303)
    except booking_service.NotYourBooking:
        return RedirectResponse("/my-bookings", status_code=303)
    return RedirectResponse(f"/bookings/{booking_id}", status_code=303)


@router.post("/bookings/{booking_id}/cancel")
def cancel(booking_id: int, db: Session = Depends(get_db), user=Depends(require_login)):
    try:
        booking_service.cancel_booking(db, booking_id, user.id)
    except booking_service.NotYourBooking:
        return RedirectResponse("/my-bookings", status_code=303)
    return RedirectResponse(f"/bookings/{booking_id}", status_code=303)


@router.get("/my-bookings", response_class=HTMLResponse)
def my_bookings(request: Request, db: Session = Depends(get_db), user=Depends(require_login)):
    bookings = (
        db.query(Booking)
        .filter(Booking.user_id == user.id)
        .order_by(Booking.created_at.desc())
        .all()
    )
    return templates.TemplateResponse("my_bookings.html", {"request": request, "user": user, "bookings": bookings})
