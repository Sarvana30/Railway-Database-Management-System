from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db


def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")

    if user_id is None:
        return None

    return db.execute(
        text(
            """
            SELECT id, name, phone, gmail
            FROM users
            WHERE id = :user_id
            """
        ),
        {"user_id": user_id},
    ).mappings().first()


def require_login(user=Depends(get_current_user)):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )

    return user