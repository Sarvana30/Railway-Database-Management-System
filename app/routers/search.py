from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.models import Station
from app.services.routing import find_direct_trains, find_connections

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/search", response_class=HTMLResponse)
def search_form(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    stations = db.execute(select(Station).order_by(Station.name)).scalars().all()
    return templates.TemplateResponse(
        "search.html", {"request": request, "stations": stations, "user": user, "today": date.today().isoformat()}
    )


@router.get("/search/results", response_class=HTMLResponse)
def search_results(
    request: Request,
    from_station_id: int,
    to_station_id: int,
    journey_date: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    jdate = datetime.strptime(journey_date, "%Y-%m-%d").date()

    direct = find_direct_trains(db, from_station_id, to_station_id, jdate, require_seat=True)
    connections = []
    if not direct:
        # Feature 6: only fall back to 1-hop connections when no direct
        # train has a free seat for the whole route.
        connections = find_connections(db, from_station_id, to_station_id, jdate)

    from_station = db.get(Station, from_station_id)
    to_station = db.get(Station, to_station_id)

    return templates.TemplateResponse(
        "search_results.html",
        {
            "request": request,
            "user": user,
            "direct": direct,
            "connections": connections,
            "from_station": from_station,
            "to_station": to_station,
            "journey_date": journey_date,
        },
    )
