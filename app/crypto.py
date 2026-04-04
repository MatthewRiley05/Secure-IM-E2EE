import hashlib
import base64

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, UserPublicKey
from app.auth import get_current_session
from app.schemas import PublicKeyUpload, PublicKeyResponse, FingerprintResponse

router = APIRouter(prefix="/keys", tags=["keys"])


def get_authenticated_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    """pull the current user from the bearer token, same pattern as friends.py"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    session = get_current_session(token, db)
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def compute_fingerprint(public_key_b64: str) -> str:
    """SHA-256 hash of the raw public key bytes, formatted as hex groups for display"""
    raw = base64.b64decode(public_key_b64)
    digest = hashlib.sha256(raw).hexdigest()
    # split into groups of 4 for readability, like: abcd 1234 ef56 ...
    groups = [digest[i:i+4] for i in range(0, len(digest), 4)]
    return " ".join(groups)


@router.post("/upload", response_model=PublicKeyResponse)
def upload_public_key(
    data: PublicKeyUpload,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    # validate that it looks like valid base64
    try:
        raw_bytes = base64.b64decode(data.public_key)
        if len(raw_bytes) < 32:
            raise ValueError("key too short")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid public key format")

    existing = db.query(UserPublicKey).filter(UserPublicKey.user_id == user.id).first()
    key_changed = False

    if existing:
        if existing.public_key != data.public_key:
            # key is changing — store the old one so others can detect it
            existing.previous_key = existing.public_key
            existing.public_key = data.public_key
            key_changed = True
        db.commit()
        db.refresh(existing)
        return PublicKeyResponse(
            user_id=user.id,
            username=user.username,
            public_key=existing.public_key,
            key_type=existing.key_type,
            uploaded_at=existing.uploaded_at.isoformat(),
            key_changed=key_changed,
        )

    # first time uploading
    new_key = UserPublicKey(
        user_id=user.id,
        public_key=data.public_key,
        key_type="ecdh-p256",
    )
    db.add(new_key)
    db.commit()
    db.refresh(new_key)

    return PublicKeyResponse(
        user_id=user.id,
        username=user.username,
        public_key=new_key.public_key,
        key_type=new_key.key_type,
        uploaded_at=new_key.uploaded_at.isoformat(),
        key_changed=False,
    )


@router.get("/{username}", response_model=PublicKeyResponse)
def get_public_key(
    username: str,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    key_record = db.query(UserPublicKey).filter(UserPublicKey.user_id == target.id).first()
    if not key_record:
        raise HTTPException(status_code=404, detail="No public key found for this user")

    # check if the key changed compared to what was previously stored
    key_changed = key_record.previous_key is not None and key_record.previous_key != key_record.public_key

    return PublicKeyResponse(
        user_id=target.id,
        username=target.username,
        public_key=key_record.public_key,
        key_type=key_record.key_type,
        uploaded_at=key_record.uploaded_at.isoformat(),
        key_changed=key_changed,
    )


@router.get("/fingerprint/{username}", response_model=FingerprintResponse)
def get_fingerprint(
    username: str,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    key_record = db.query(UserPublicKey).filter(UserPublicKey.user_id == target.id).first()
    if not key_record:
        raise HTTPException(status_code=404, detail="No public key found for this user")

    fp = compute_fingerprint(key_record.public_key)

    return FingerprintResponse(
        username=target.username,
        fingerprint=fp,
        public_key=key_record.public_key,
    )
