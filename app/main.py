from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exception_handlers import http_exception_handler

from app.config import settings
from app.routers import auth, search, seatmap, booking, trips

app = FastAPI(title="Railway Management System")

app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(search.router)
app.include_router(seatmap.router)
app.include_router(booking.router)
app.include_router(trips.router)


@app.exception_handler(StarletteHTTPException)
async def redirect_on_auth_required(request: Request, exc: StarletteHTTPException):
    # require_login() raises a 303 with a Location header when no one is
    # logged in; let that behave as a real redirect instead of an error page.
    if exc.status_code == 303 and "Location" in (exc.headers or {}):
        return RedirectResponse(exc.headers["Location"], status_code=303)
    return await http_exception_handler(request, exc)


@app.get("/")
def root():
    return RedirectResponse("/search")
