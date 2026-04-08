from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, SessionToken
from app.schemas import (
    UserRegister,
    UserResponse,
    RegisterResponse,
    UserLogin,
    LogoutRequest,
    LoginResponse,
)
from app.security import (
    hash_password,
    verify_password,
    generate_otp_secret,
    verify_otp_code,
    build_otp_uri,
    check_rate_limit,
)

router = APIRouter()


def cleanup_expired_sessions(db: Session) -> None:
    now = datetime.now(timezone.utc)
    expired_sessions = db.query(SessionToken).filter(SessionToken.expires_at < now).all()
    for session in expired_sessions:
        db.delete(session)
    db.commit()


def get_current_session(token: str, db: Session) -> SessionToken:
    cleanup_expired_sessions(db)

    session = db.query(SessionToken).filter(SessionToken.token == token).first()
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return session


@router.post("/register", response_model=RegisterResponse)
def register_user(user: UserRegister, db: Session = Depends(get_db)):
    check_rate_limit(f"register:{user.username}", limit=5, window_seconds=60)

    existing_user = db.query(User).filter(User.username == user.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    if user.email:
        existing_email = db.query(User).filter(User.email == user.email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already exists")

    otp_secret = generate_otp_secret()

    new_user = User(
        username=user.username,
        email=user.email,
        password_hash=hash_password(user.password),
        otp_secret=otp_secret
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return RegisterResponse(
        id=new_user.id,
        username=new_user.username,
        email=new_user.email,
        otp_secret=otp_secret,
        otp_uri=build_otp_uri(otp_secret, new_user.username)
    )


@router.post("/login", response_model=LoginResponse)
def login_user(user: UserLogin, db: Session = Depends(get_db)):
    check_rate_limit(f"login:{user.username}", limit=10, window_seconds=60)

    db_user = db.query(User).filter(User.username == user.username).first()

    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not verify_password(user.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not verify_otp_code(db_user.otp_secret, user.otp_code):
        raise HTTPException(status_code=401, detail="Invalid OTP code")

    now = datetime.now(timezone.utc)

    expired_sessions = db.query(SessionToken).filter(SessionToken.expires_at < now).all()
    for session in expired_sessions:
        db.delete(session)

    existing_sessions = db.query(SessionToken).filter(SessionToken.user_id == db_user.id).all()
    for session in existing_sessions:
        db.delete(session)

    token = token_urlsafe(32)
    expires_at = now + timedelta(hours=1)

    session = SessionToken(
        user_id=db_user.id,
        token=token,
        expires_at=expires_at
    )

    db.add(session)
    db.commit()

    return LoginResponse(
        message="Login successful",
        token=token,
        expires_at=expires_at.isoformat()
    )


@router.post("/logout")
def logout_user(data: LogoutRequest, db: Session = Depends(get_db)):
    session = db.query(SessionToken).filter(SessionToken.token == data.token).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.delete(session)
    db.commit()

    return {"message": "Logout successful"}


@router.get("/me", response_model=UserResponse)
def get_me(token: str, db: Session = Depends(get_db)):
    session = get_current_session(token, db)

    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user
