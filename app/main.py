import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

from app.dependencies import get_current_user
from app.routers import auth, availability, booking, search

app = FastAPI()
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
    name="static",
)
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET_KEY"],
    same_site="lax",
    https_only=os.environ.get("HTTPS_ONLY", "false").lower() == "true",
)

app.include_router(auth.router)
app.include_router(availability.router)
app.include_router(booking.router)
app.include_router(search.router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"user": user},
    )
