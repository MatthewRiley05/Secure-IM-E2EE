from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.db import get_db
from app.models import (
    User,
    FriendRequest,
    FriendRequestStatus,
    Friendship,
    Block,
    Conversation,
)
from app.auth import get_current_session
from app.schemas import (
    FriendRequestSend,
    FriendRequestAction,
    FriendRequestResponse,
    FriendResponse,
    FriendListResponse,
    BlockUser,
    BlockResponse,
    ConversationResponse,
    ConversationListResponse,
    MessageCheckResponse,
)
from app.security import check_rate_limit

router = APIRouter(prefix="/friends", tags=["friends"])


def get_user_from_token(token: str, db: Session) -> User:
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


def are_friends(user_id: int, other_id: int, db: Session) -> bool:
    return db.query(Friendship).filter(
        or_(
            (Friendship.user_id == user_id) & (Friendship.friend_id == other_id),
            (Friendship.user_id == other_id) & (Friendship.friend_id == user_id),
        )
    ).first() is not None


def is_blocked(user_id: int, other_id: int, db: Session) -> bool:
    return db.query(Block).filter(
        or_(
            (Block.blocker_id == user_id) & (Block.blocked_id == other_id),
            (Block.blocker_id == other_id) & (Block.blocked_id == user_id),
        )
    ).first() is not None


# --- Friend Request Endpoints ---

@router.post("/request/send")
def send_friend_request(data: FriendRequestSend, token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)
    check_rate_limit(f"friend_request:{user.id}", limit=10, window_seconds=60)

    target = get_user_by_username(data.username, db)

    if user.id == target.id:
        raise HTTPException(status_code=400, detail="Cannot send request to yourself")

    if are_friends(user.id, target.id, db):
        raise HTTPException(status_code=400, detail="Already friends")

    if is_blocked(user.id, target.id, db):
        raise HTTPException(status_code=403, detail="User is blocked")

    existing = db.query(FriendRequest).filter(
        FriendRequest.from_user_id == user.id,
        FriendRequest.to_user_id == target.id,
    ).first()
    if existing:
        if existing.status == FriendRequestStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Friend request already sent")
        existing.status = FriendRequestStatus.PENDING.value
        db.commit()
        db.refresh(existing)
        return {"message": "Friend request resent", "request_id": existing.id}

    reverse = db.query(FriendRequest).filter(
        FriendRequest.from_user_id == target.id,
        FriendRequest.to_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).first()
    if reverse:
        raise HTTPException(status_code=400, detail="This user has already sent you a request")

    request = FriendRequest(
        from_user_id=user.id,
        to_user_id=target.id,
        status=FriendRequestStatus.PENDING.value,
    )
    db.add(request)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Friend request already exists")
    db.refresh(request)

    return {"message": "Friend request sent", "request_id": request.id}


@router.post("/request/accept")
def accept_friend_request(data: FriendRequestAction, token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)

    request = db.query(FriendRequest).filter(
        FriendRequest.id == data.request_id,
        FriendRequest.to_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Friend request not found")

    request.status = FriendRequestStatus.ACCEPTED.value

    friendship1 = Friendship(user_id=request.from_user_id, friend_id=request.to_user_id)
    friendship2 = Friendship(user_id=request.to_user_id, friend_id=request.from_user_id)
    db.add(friendship1)
    db.add(friendship2)

    conversation = Conversation(
        user1_id=min(request.from_user_id, request.to_user_id),
        user2_id=max(request.from_user_id, request.to_user_id),
    )
    db.add(conversation)

    db.commit()
    return {"message": "Friend request accepted"}


@router.post("/request/decline")
def decline_friend_request(data: FriendRequestAction, token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)

    request = db.query(FriendRequest).filter(
        FriendRequest.id == data.request_id,
        FriendRequest.to_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Friend request not found")

    request.status = FriendRequestStatus.DECLINED.value
    db.commit()
    return {"message": "Friend request declined"}


@router.post("/request/cancel")
def cancel_friend_request(data: FriendRequestAction, token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)

    request = db.query(FriendRequest).filter(
        FriendRequest.id == data.request_id,
        FriendRequest.from_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Friend request not found")

    request.status = FriendRequestStatus.CANCELLED.value
    db.commit()
    return {"message": "Friend request cancelled"}


@router.get("/requests/incoming")
def get_incoming_requests(token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)

    requests = db.query(FriendRequest).filter(
        FriendRequest.to_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).all()

    results = []
    for req in requests:
        from_user = db.query(User).filter(User.id == req.from_user_id).first()
        results.append(FriendRequestResponse(
            id=req.id,
            from_user_id=req.from_user_id,
            to_user_id=req.to_user_id,
            status=req.status,
            created_at=req.created_at.isoformat(),
            from_username=from_user.username if from_user else None,
        ))
    return results


@router.get("/requests/outgoing")
def get_outgoing_requests(token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)

    requests = db.query(FriendRequest).filter(
        FriendRequest.from_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).all()

    results = []
    for req in requests:
        to_user = db.query(User).filter(User.id == req.to_user_id).first()
        results.append(FriendRequestResponse(
            id=req.id,
            from_user_id=req.from_user_id,
            to_user_id=req.to_user_id,
            status=req.status,
            created_at=req.created_at.isoformat(),
            to_username=to_user.username if to_user else None,
        ))
    return results


# --- Friend Management ---

@router.get("/list", response_model=FriendListResponse)
def list_friends(token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)

    friendships = db.query(Friendship).filter(Friendship.user_id == user.id).all()

    friends = []
    for f in friendships:
        friend = db.query(User).filter(User.id == f.friend_id).first()
        if friend:
            friends.append(FriendResponse(id=friend.id, username=friend.username))

    return FriendListResponse(friends=friends, total=len(friends))


@router.delete("/remove")
def remove_friend(data: FriendRequestSend, token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)
    friend = get_user_by_username(data.username, db)

    friendship1 = db.query(Friendship).filter(
        Friendship.user_id == user.id, Friendship.friend_id == friend.id
    ).first()
    friendship2 = db.query(Friendship).filter(
        Friendship.user_id == friend.id, Friendship.friend_id == user.id
    ).first()

    if not friendship1 and not friendship2:
        raise HTTPException(status_code=404, detail="Not friends")

    if friendship1:
        db.delete(friendship1)
    if friendship2:
        db.delete(friendship2)

    conv = db.query(Conversation).filter(
        or_(
            (Conversation.user1_id == min(user.id, friend.id)) & (Conversation.user2_id == max(user.id, friend.id)),
        )
    ).first()
    if conv:
        db.delete(conv)

    db.commit()
    return {"message": "Friend removed"}


# --- Block ---

@router.post("/block")
def block_user(data: BlockUser, token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)
    target = get_user_by_username(data.username, db)

    if user.id == target.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")

    existing = db.query(Block).filter(
        Block.blocker_id == user.id, Block.blocked_id == target.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already blocked")

    block = Block(blocker_id=user.id, blocked_id=target.id)
    db.add(block)

    friendship1 = db.query(Friendship).filter(
        Friendship.user_id == user.id, Friendship.friend_id == target.id
    ).first()
    friendship2 = db.query(Friendship).filter(
        Friendship.user_id == target.id, Friendship.friend_id == user.id
    ).first()
    if friendship1:
        db.delete(friendship1)
    if friendship2:
        db.delete(friendship2)

    pending = db.query(FriendRequest).filter(
        FriendRequest.status == FriendRequestStatus.PENDING.value,
        or_(
            (FriendRequest.from_user_id == user.id) & (FriendRequest.to_user_id == target.id),
            (FriendRequest.from_user_id == target.id) & (FriendRequest.to_user_id == user.id),
        ),
    ).all()
    for req in pending:
        db.delete(req)

    db.commit()
    return {"message": f"User {target.username} blocked"}


@router.delete("/unblock")
def unblock_user(data: BlockUser, token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)
    target = get_user_by_username(data.username, db)

    block = db.query(Block).filter(
        Block.blocker_id == user.id, Block.blocked_id == target.id
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="User is not blocked")

    db.delete(block)
    db.commit()
    return {"message": f"User {target.username} unblocked"}


@router.get("/blocked")
def list_blocked_users(token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)

    blocks = db.query(Block).filter(Block.blocker_id == user.id).all()

    results = []
    for b in blocks:
        blocked_user = db.query(User).filter(User.id == b.blocked_id).first()
        results.append(BlockResponse(
            id=b.id,
            blocker_id=b.blocker_id,
            blocked_id=b.blocked_id,
            blocked_username=blocked_user.username if blocked_user else "unknown",
            created_at=b.created_at.isoformat(),
        ))
    return results


# --- Anti-Spam Check ---

@router.get("/can-message/{username}", response_model=MessageCheckResponse)
def can_message(username: str, token: str, db: Session = Depends(get_db)):
    user = get_user_from_token(token, db)
    target = get_user_by_username(username, db)

    if user.id == target.id:
        return MessageCheckResponse(allowed=True)

    if is_blocked(user.id, target.id, db):
        return MessageCheckResponse(allowed=False, reason="One of you has blocked the other")

    if not are_friends(user.id, target.id, db):
        return MessageCheckResponse(allowed=False, reason="You must be friends to message this user")

    return MessageCheckResponse(allowed=True)


# --- Conversations ---

@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    token: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    user = get_user_from_token(token, db)

    query = db.query(Conversation).filter(
        or_(Conversation.user1_id == user.id, Conversation.user2_id == user.id)
    )

    total = query.count()
    conversations = query.order_by(Conversation.updated_at.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()

    results = []
    for conv in conversations:
        if conv.user1_id == user.id:
            other_id = conv.user2_id
            unread = conv.user1_unread
        else:
            other_id = conv.user1_id
            unread = conv.user2_unread

        other_user = db.query(User).filter(User.id == other_id).first()
        results.append(ConversationResponse(
            id=conv.id,
            other_user_id=other_id,
            other_username=other_user.username if other_user else "unknown",
            unread_count=unread,
            updated_at=conv.updated_at.isoformat(),
        ))

    return ConversationListResponse(
        conversations=results,
        total=total,
        page=page,
        page_size=page_size,
    )
