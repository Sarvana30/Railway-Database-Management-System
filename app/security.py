"""Password hashing. Session state itself lives in the signed session cookie
(Starlette's SessionMiddleware, wired up in main.py) rather than a server-side
session table -- simpler for a beginner project, and the cookie is signed with
SESSION_SECRET so it can't be forged.
"""
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
