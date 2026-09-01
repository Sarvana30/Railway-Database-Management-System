from datetime import datetime
from itertools import groupby

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_login
from app.models import Train, Station
from app.services.availability import get_seat_status_map, find_adjacent_available_seats

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/seatmap/{train_id}", response_class=HTMLResponse)
def seatmap(
    request: Request,
    train_id: int,
    from_station_id: int = Query(...),
    to_station_id: int = Query(...),
    journey_date: str = Query(...),
    group_size: int = Query(1, ge=1, le=6),
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    jdate = datetime.strptime(journey_date, "%Y-%m-%d").date()
    status_rows = get_seat_status_map(db, train_id, jdate, from_station_id, to_station_id)

    coaches = []
    for coach_number, rows in groupby(status_rows, key=lambda r: r["coach_number"]):
        rows = list(rows)
        coaches.append({"coach_number": coach_number, "coach_type": rows[0]["coach_type"], "seats": rows})

    suggested_group = find_adjacent_available_seats(status_rows, group_size) if group_size > 1 else None

    train = db.get(Train, train_id)
    from_station = db.get(Station, from_station_id)
    to_station = db.get(Station, to_station_id)

    return templates.TemplateResponse(
        "seatmap.html",
        {
            "request": request,
            "user": user,
            "train": train,
            "coaches": coaches,
            "from_station": from_station,
            "to_station": to_station,
            "journey_date": journey_date,
            "group_size": group_size,
            "suggested_group": suggested_group,
        },
    )
