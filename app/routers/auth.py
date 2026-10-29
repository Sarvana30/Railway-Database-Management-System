from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pwdlib import PasswordHash
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)
password_hash = PasswordHash.recommended()


@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="auth/signup.html",
        context={"error": request.query_params.get("error")},
    )


@router.post("/signup")
def signup(
    request: Request,
    name: str = Form(...),
    phone: str = Form(...),
    gmail: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    name = name.strip()
    phone = phone.strip()
    gmail = gmail.strip().lower()

    if (
        not name
        or len(name) > 100
        or not phone
        or len(phone) > 20
        or not gmail
        or len(gmail) > 254
        or len(password) < 8
    ):
        return RedirectResponse("/signup?error=invalid_input", status_code=303)

    hashed_password = password_hash.hash(password)

    try:
        with db.begin():
            result = db.execute(
                text(
                    """
                    INSERT INTO users (name, phone, gmail, passwordHash)
                    VALUES (:name, :phone, :gmail, :password_hash)
                    """
                ),
                {
                    "name": name,
                    "phone": phone,
                    "gmail": gmail,
                    "password_hash": hashed_password,
                },
            )
            user_id = result.lastrowid
    except IntegrityError:
        return RedirectResponse("/signup?error=account_exists", status_code=303)

    request.session.clear()
    request.session["user_id"] = user_id

    return RedirectResponse("/", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"error": request.query_params.get("error")},
    )


@router.post("/login")
def login(
    request: Request,
    gmail: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.execute(
        text(
            """
            SELECT id, passwordHash
            FROM users
            WHERE gmail = :gmail
            """
        ),
        {"gmail": gmail.strip().lower()},
    ).mappings().first()

    if user is None or not password_hash.verify(password, user["passwordHash"]):
        return RedirectResponse("/login?error=invalid_credentials", status_code=303)

    request.session.clear()
    request.session["user_id"] = user["id"]

    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)