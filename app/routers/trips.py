from datetime import datetime

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_login
from app.models import Station, Trip, TicketType
from app.services.routing import find_direct_trains
from app.services.trip_service import book_trip, LegRequest, TripBookingFailed, resolve_seat_for_leg

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/trip-planner", response_class=HTMLResponse)
def trip_planner_form(request: Request, db: Session = Depends(get_db), user=Depends(require_login)):
    stations = db.execute(select(Station).order_by(Station.name)).scalars().all()
    return templates.TemplateResponse(
        "trip_planner.html", {"request": request, "user": user, "stations": stations, "error": None}
    )


@router.post("/trip-planner/book")
async def trip_planner_book(request: Request, db: Session = Depends(get_db), user=Depends(require_login)):
    """Each leg comes in as parallel form-array fields:
    leg_train_id[], leg_from[], leg_to[], leg_date[], leg_ticket_type[]
    A train must already have been chosen per leg (via the search step on the
    trip-planner page); we resolve a free seat for each leg server-side.
    """
    form = await request.form()
    train_ids = form.getlist("leg_train_id")
    froms = form.getlist("leg_from")
    tos = form.getlist("leg_to")
    dates = form.getlist("leg_date")
    ticket_types = form.getlist("leg_ticket_type")

    legs: list[LegRequest] = []
    for i in range(len(train_ids)):
        jdate = datetime.strptime(dates[i], "%Y-%m-%d").date()
        seat_id = resolve_seat_for_leg(db, int(train_ids[i]), jdate, int(froms[i]), int(tos[i]))
        if seat_id is None:
            stations = db.execute(select(Station).order_by(Station.name)).scalars().all()
            return templates.TemplateResponse(
                "trip_planner.html",
                {
                    "request": request,
                    "user": user,
                    "stations": stations,
                    "error": f"No seat available for leg {i + 1}. Nothing has been booked.",
                },
            )
        legs.append(
            LegRequest(
                train_id=int(train_ids[i]),
                seat_id=seat_id,
                from_station_id=int(froms[i]),
                to_station_id=int(tos[i]),
                journey_date=jdate,
                ticket_type=TicketType(ticket_types[i]) if i < len(ticket_types) else TicketType.general,
            )
        )

    try:
        trip = book_trip(db, user.id, legs)
    except TripBookingFailed as e:
        stations = db.execute(select(Station).order_by(Station.name)).scalars().all()
        return templates.TemplateResponse(
            "trip_planner.html",
            {"request": request, "user": user, "stations": stations, "error": str(e)},
        )

    return RedirectResponse(f"/trips/{trip.id}", status_code=303)


@router.get("/trip-planner/search-leg")
def search_leg(
    from_station_id: int, to_station_id: int, journey_date: str,
    db: Session = Depends(get_db), user=Depends(require_login),
):
    """Small JSON endpoint the trip-planner page calls (via fetch) to list
    direct trains for one leg, so the user can pick a train per city hop.
    """
    jdate = datetime.strptime(journey_date, "%Y-%m-%d").date()
    trains = find_direct_trains(db, from_station_id, to_station_id, jdate, require_seat=True)
    return [
        {
            "train_id": t.train_id,
            "name": t.train_name,
            "number": t.train_number,
            "departure_time": t.departure_time,
            "arrival_time": t.arrival_time,
        }
        for t in trains
    ]


@router.get("/trips/{trip_id}", response_class=HTMLResponse)
def trip_detail(request: Request, trip_id: int, db: Session = Depends(get_db), user=Depends(require_login)):
    trip = db.get(Trip, trip_id)
    return templates.TemplateResponse("trip_detail.html", {"request": request, "user": user, "trip": trip})
