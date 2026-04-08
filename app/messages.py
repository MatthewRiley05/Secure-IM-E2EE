import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_session
from app.db import get_db
from app.models import Block, Conversation, Message, MessageStatus, User
from app.schemas import (
    MarkReadResponse,
    MessageItemResponse,
    MessageListResponse,
    MessageSendRequest,
    MessageStatusResponse,
    PendingMessageResponse,
    SendMessageResponse,
)

router = APIRouter(prefix="/messages", tags=["messages"])


def build_conversation_tag(user_a: str, user_b: str) -> str:
    left, right = sorted([user_a, user_b])
    return f"e2ee:{left}:{right}"


def validate_ciphertext_payload(
    ciphertext: dict,
    sender_username: str,
    receiver_username: str,
    ttl_seconds: int | None,
) -> tuple[int, str, int | None]:
    if not isinstance(ciphertext, dict):
        raise HTTPException(status_code=422, detail="ciphertext must be an object")

    raw_ciphertext = ciphertext.get("ciphertext")
    raw_iv = ciphertext.get("iv")
    metadata = ciphertext.get("metadata")

    if not isinstance(raw_ciphertext, str) or not raw_ciphertext:
        raise HTTPException(status_code=422, detail="ciphertext.ciphertext must be a non-empty string")
    if not isinstance(raw_iv, str) or not raw_iv:
        raise HTTPException(status_code=422, detail="ciphertext.iv must be a non-empty string")
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=422, detail="ciphertext.metadata must be an object")

    aad_sender = metadata.get("sender")
    aad_receiver = metadata.get("receiver")
    aad_counter = metadata.get("counter")
    aad_conversation_tag = metadata.get("conversation")
    aad_ttl_seconds = metadata.get("ttl_seconds")

    if aad_sender != sender_username:
        raise HTTPException(status_code=422, detail="ciphertext.metadata.sender mismatch")
    if aad_receiver != receiver_username:
        raise HTTPException(status_code=422, detail="ciphertext.metadata.receiver mismatch")
    if not isinstance(aad_counter, int) or aad_counter < 1:
        raise HTTPException(status_code=422, detail="ciphertext.metadata.counter must be a positive integer")

    expected_tag = build_conversation_tag(sender_username, receiver_username)
    if aad_conversation_tag != expected_tag:
        raise HTTPException(status_code=422, detail="ciphertext.metadata.conversation mismatch")

    if ttl_seconds is None and aad_ttl_seconds is not None:
        raise HTTPException(status_code=422, detail="ciphertext.metadata.ttl_seconds must be null when ttl_seconds is not set")
    if ttl_seconds is not None:
        if not isinstance(aad_ttl_seconds, int):
            raise HTTPException(status_code=422, detail="ciphertext.metadata.ttl_seconds must be an integer")
        if aad_ttl_seconds != ttl_seconds:
            raise HTTPException(status_code=422, detail="ciphertext.metadata.ttl_seconds mismatch")

    return aad_counter, expected_tag, aad_ttl_seconds


def get_authenticated_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
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


def get_user_by_username(username: str, db: Session) -> User:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def get_username_map(user_ids: set[int], db: Session) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()
    return {uid: username for uid, username in rows}


def are_friends(user_id: int, other_id: int, db: Session) -> bool:
    conversation = db.query(Conversation).filter(
        Conversation.user1_id == min(user_id, other_id),
        Conversation.user2_id == max(user_id, other_id),
    ).first()
    return conversation is not None


def is_blocked(user_id: int, other_id: int, db: Session) -> bool:
    return db.query(Block).filter(
        or_(
            (Block.blocker_id == user_id) & (Block.blocked_id == other_id),
            (Block.blocker_id == other_id) & (Block.blocked_id == user_id),
        )
    ).first() is not None


def get_or_create_conversation(user_id: int, other_id: int, db: Session) -> Conversation:
    user1_id = min(user_id, other_id)
    user2_id = max(user_id, other_id)

    conversation = db.query(Conversation).filter(
        Conversation.user1_id == user1_id,
        Conversation.user2_id == user2_id,
    ).first()

    if conversation:
        return conversation

    conversation = Conversation(user1_id=user1_id, user2_id=user2_id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def cleanup_expired_messages(db: Session) -> int:
    now = datetime.now(timezone.utc)
    expired_messages = db.query(Message).filter(
        Message.destroyed_at.is_(None),
        Message.expires_at.is_not(None),
        Message.expires_at <= now,
    ).all()

    if not expired_messages:
        return 0

    conversation_ids = {msg.conversation_id for msg in expired_messages}
    count = len(expired_messages)
    for msg in expired_messages:
        msg.destroyed_at = now

    conversations = db.query(Conversation).filter(Conversation.id.in_(conversation_ids)).all()
    conv_map = {conv.id: conv for conv in conversations}
    for conv in conversations:
        conv.updated_at = now

    for msg in expired_messages:
        if msg.is_read:
            continue
        conv = conv_map.get(msg.conversation_id)
        if not conv:
            continue
        if conv.user1_id == msg.receiver_id:
            conv.user1_unread = max(conv.user1_unread - 1, 0)
        elif conv.user2_id == msg.receiver_id:
            conv.user2_unread = max(conv.user2_unread - 1, 0)

    db.commit()
    return count


def serialize_message(message: Message, username_map: dict[int, str]) -> MessageItemResponse:
    try:
        payload = json.loads(message.ciphertext_json)
    except Exception:
        payload = {}

    return MessageItemResponse(
        id=message.id,
        sender_username=username_map.get(message.sender_id, "unknown"),
        receiver_username=username_map.get(message.receiver_id, "unknown"),
        ciphertext=payload,
        status=message.status,
        created_at=message.created_at.isoformat() if message.created_at else "",
        delivered_at=message.delivered_at.isoformat() if message.delivered_at else None,
        read_at=message.read_at.isoformat() if message.read_at else None,
        expires_at=message.expires_at.isoformat() if message.expires_at else None,
    )


@router.post("/send", response_model=SendMessageResponse)
def send_message(
    data: MessageSendRequest,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    cleanup_expired_messages(db)

    receiver = get_user_by_username(data.receiver_username, db)
    if receiver.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot send message to yourself")

    if is_blocked(user.id, receiver.id, db):
        raise HTTPException(status_code=403, detail="One of you has blocked the other")

    if not are_friends(user.id, receiver.id, db):
        raise HTTPException(status_code=403, detail="You must be friends to message this user")

    aad_counter, aad_conversation_tag, aad_ttl_seconds = validate_ciphertext_payload(
        data.ciphertext,
        sender_username=user.username,
        receiver_username=receiver.username,
        ttl_seconds=data.ttl_seconds,
    )

    duplicate = db.query(Message).filter(
        Message.sender_id == user.id,
        Message.receiver_id == receiver.id,
        Message.aad_counter == aad_counter,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Replay or duplicate message counter detected")

    conversation = get_or_create_conversation(user.id, receiver.id, db)

    now = datetime.now(timezone.utc)
    expires_at = None
    if data.ttl_seconds:
        expires_at = now + timedelta(seconds=data.ttl_seconds)

    message = Message(
        conversation_id=conversation.id,
        sender_id=user.id,
        receiver_id=receiver.id,
        aad_sender=user.username,
        aad_receiver=receiver.username,
        aad_counter=aad_counter,
        aad_conversation_tag=aad_conversation_tag,
        aad_ttl_seconds=aad_ttl_seconds,
        ciphertext_json=json.dumps(data.ciphertext),
        status=MessageStatus.SENT.value,
        expires_at=expires_at,
    )
    db.add(message)

    if conversation.user1_id == receiver.id:
        conversation.user1_unread += 1
    else:
        conversation.user2_unread += 1
    conversation.updated_at = now

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Replay or duplicate message counter detected")
    db.refresh(message)

    return SendMessageResponse(
        message_id=message.id,
        status=message.status,
        created_at=message.created_at.isoformat() if message.created_at else now.isoformat(),
        expires_at=message.expires_at.isoformat() if message.expires_at else None,
    )


@router.get("/conversation/{username}", response_model=MessageListResponse)
def get_conversation_messages(
    username: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    cleanup_expired_messages(db)

    other = get_user_by_username(username, db)

    conversation = db.query(Conversation).filter(
        Conversation.user1_id == min(user.id, other.id),
        Conversation.user2_id == max(user.id, other.id),
    ).first()

    if not conversation:
        return MessageListResponse(messages=[], total=0, page=page, page_size=page_size)

    query = db.query(Message).filter(
        Message.conversation_id == conversation.id,
        Message.destroyed_at.is_(None),
    )

    total = query.count()
    messages = (
        query.order_by(Message.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    now = datetime.now(timezone.utc)
    delivered_changed = False
    read_changed = False

    for msg in messages:
        if msg.receiver_id == user.id and msg.status == MessageStatus.SENT.value:
            msg.status = MessageStatus.DELIVERED.value
            msg.delivered_at = now
            delivered_changed = True
        if msg.receiver_id == user.id and not msg.is_read:
            msg.is_read = True
            msg.read_at = now
            read_changed = True

    if read_changed:
        if conversation.user1_id == user.id:
            conversation.user1_unread = 0
        else:
            conversation.user2_unread = 0

    if delivered_changed or read_changed:
        db.commit()

    messages = list(reversed(messages))
    user_ids = {m.sender_id for m in messages} | {m.receiver_id for m in messages}
    username_map = get_username_map(user_ids, db)
    items = [serialize_message(m, username_map) for m in messages]

    return MessageListResponse(messages=items, total=total, page=page, page_size=page_size)


@router.get("/inbox/pending", response_model=PendingMessageResponse)
def get_pending_messages(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    cleanup_expired_messages(db)

    pending = db.query(Message).filter(
        Message.receiver_id == user.id,
        Message.status == MessageStatus.SENT.value,
        Message.destroyed_at.is_(None),
    ).order_by(Message.id.asc()).limit(limit).all()

    if not pending:
        return PendingMessageResponse(messages=[], total=0)

    now = datetime.now(timezone.utc)
    for msg in pending:
        msg.status = MessageStatus.DELIVERED.value
        msg.delivered_at = now

    db.commit()

    user_ids = {m.sender_id for m in pending} | {m.receiver_id for m in pending}
    username_map = get_username_map(user_ids, db)
    items = [serialize_message(m, username_map) for m in pending]

    return PendingMessageResponse(messages=items, total=len(items))


@router.post("/read/{username}", response_model=MarkReadResponse)
def mark_conversation_read(
    username: str,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    cleanup_expired_messages(db)

    other = get_user_by_username(username, db)
    conversation = db.query(Conversation).filter(
        Conversation.user1_id == min(user.id, other.id),
        Conversation.user2_id == max(user.id, other.id),
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    now = datetime.now(timezone.utc)
    unread_messages = db.query(Message).filter(
        Message.conversation_id == conversation.id,
        Message.receiver_id == user.id,
        Message.destroyed_at.is_(None),
        Message.is_read.is_(False),
    ).all()

    for msg in unread_messages:
        msg.is_read = True
        msg.read_at = now
        if msg.status == MessageStatus.SENT.value:
            msg.status = MessageStatus.DELIVERED.value
            msg.delivered_at = now

    if conversation.user1_id == user.id:
        conversation.user1_unread = 0
    else:
        conversation.user2_unread = 0

    db.commit()
    return MarkReadResponse(conversation_id=conversation.id, marked_read=len(unread_messages))


@router.get("/status/{message_id}", response_model=MessageStatusResponse)
def get_message_status(
    message_id: int,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message or message.destroyed_at is not None:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.sender_id != user.id and message.receiver_id != user.id:
        raise HTTPException(status_code=403, detail="Not allowed")

    return MessageStatusResponse(
        id=message.id,
        status=message.status,
        delivered_at=message.delivered_at.isoformat() if message.delivered_at else None,
        read_at=message.read_at.isoformat() if message.read_at else None,
    )


@router.post("/cleanup")
def cleanup_messages(
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    deleted = cleanup_expired_messages(db)
    return {"message": "Cleanup complete", "expired_messages": deleted}
