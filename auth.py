from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from pwdlib import PasswordHash

from db import engine

router = APIRouter(prefix="/auth")

password_hash = PasswordHash.recommended()


class SignupRequest(BaseModel):
    name: str
    email: str
    phone: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/signup", status_code=201)
def signup(user: SignupRequest):

    with engine.begin() as conn:
        existing_user = conn.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": user.email}
        ).first()

        if existing_user:
            raise HTTPException(
                status_code=409,
                detail="Email already registered"
            )

        hashed_password = password_hash.hash(user.password)

        conn.execute(
            text("""
                INSERT INTO users (name, email, phone, hashed_password)
                VALUES (:name, :email, :phone, :hashed_password)
            """),
            {
                "name": user.name,
                "email": user.email,
                "phone": user.phone,
                "hashed_password": hashed_password
            }
        )

    return {"message": "Signup successful"}



@router.post("/login")
def login(user: LoginRequest):

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT hashed_password
                FROM users
                WHERE email = :email
            """),
            {"email": user.email}
        ).first()

    if not result or not password_hash.verify(
        user.password, result[0]
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    return {"message": "Login successful"}