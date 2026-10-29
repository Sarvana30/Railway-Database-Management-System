from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.availability_service import (
    JourneySegmentUnavailable,
    get_seat_availability,
)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get(
    "/availability/{train_run_id}",
    response_class=HTMLResponse,
)
def show_availability(
    request: Request,
    train_run_id: int,
    from_station_id: int,
    to_station_id: int,
    db: Session = Depends(get_db),
):
    try:
        availability = get_seat_availability(
            db,
            train_run_id,
            from_station_id,
            to_station_id,
        )
    except JourneySegmentUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    error = None
    if request.query_params.get("error") == "booking_unavailable":
        error = "The booking could not be completed. A seat may no longer be available, or passenger details may be invalid. Please review the form and try again."
    elif request.query_params.get("error") == "hold_expired":
        error = "Your five-minute seat hold expired. Check availability and begin checkout again."

    return templates.TemplateResponse(
    request=request,
    name="availability.html",
    context={
        "availability": availability,
        "error": error,
    },
)
