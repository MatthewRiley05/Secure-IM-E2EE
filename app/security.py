from collections import defaultdict, deque
from datetime import datetime, timedelta

import pyotp
from fastapi import HTTPException
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

rate_limit_store = defaultdict(deque)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def generate_otp_secret() -> str:
    return pyotp.random_base32()


def verify_otp_code(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def build_otp_uri(secret: str, username: str, issuer: str = "IMServer") -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def check_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=window_seconds)

    timestamps = rate_limit_store[key]

    while timestamps and timestamps[0] < window_start:
        timestamps.popleft()

    if len(timestamps) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later."
        )

    timestamps.append(now)